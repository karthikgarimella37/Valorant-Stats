"""
Rate-limited client for vlr.orlandomm.net (catalog) and www.vlr.gg (HTML).

HTML scrapes optionally route through AWS API Gateway IP rotation
(requests-ip-rotator) so www.vlr.gg does not connection-refuse a single IP.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend.api_connectors.ip_rotator_gateway import VlrIpRotator, ip_rotator_enabled

API_BASE = "https://vlr.orlandomm.net/api/v1"
SITE_BASE = "https://www.vlr.gg"

logger = logging.getLogger(__name__)


class VlrSessionFactory:
    """Build requests sessions (direct or IP-rotated for www.vlr.gg)."""

    def __init__(
        self,
        site_base: str = SITE_BASE,
        total_retries: int = 3,
        backoff_factor: float = 1.5,
        pool_maxsize: int = 4,
        use_ip_rotator: bool | None = None,
        user_agent: str = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    ):
        self.site_base = site_base.rstrip("/")
        self.total_retries = total_retries
        self.backoff_factor = backoff_factor
        self.pool_maxsize = pool_maxsize
        self.user_agent = user_agent
        self.use_ip_rotator = ip_rotator_enabled() if use_ip_rotator is None else use_ip_rotator

    def create(self, *, for_html: bool = False) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        retry = Retry(
            total=self.total_retries,
            connect=1,
            read=self.total_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=self.pool_maxsize,
            pool_maxsize=self.pool_maxsize,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        if for_html and self.use_ip_rotator:
            mounted = VlrIpRotator.mount(session, self.site_base)
            if mounted:
                logger.debug("Session mounted on IP rotator for %s", self.site_base)
            else:
                logger.warning("IP rotator enabled but mount failed for %s", self.site_base)
        return session


@dataclass
class PageFetchProgress:
    """Thread-safe progress tracker for paginated fetches."""

    resource: str
    total_pages: int
    completed_pages: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark_page_complete(self, *, page: int, count: int, worker: str) -> None:
        with self.lock:
            self.completed_pages += 1
            logger.info(
                "[%s] %s page=%s got %s rows (page %s/%s)",
                worker,
                self.resource,
                page,
                count,
                self.completed_pages,
                self.total_pages,
            )


class VlrConnector:
    """HTTP client for VLR unofficial API + HTML pages."""

    def __init__(
        self,
        api_base: str = API_BASE,
        site_base: str = SITE_BASE,
        request_delay_sec: float | None = None,
        timeout: int = 45,
        max_workers: int | None = None,
        api_max_workers: int | None = None,
        html_max_workers: int | None = None,
        session_factory: VlrSessionFactory | None = None,
        use_ip_rotator: bool | None = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.site_base = site_base.rstrip("/")
        self.use_ip_rotator = ip_rotator_enabled() if use_ip_rotator is None else use_ip_rotator

        default_delay = "0.1" if self.use_ip_rotator else "0.35"
        default_html_workers = "10" if self.use_ip_rotator else "3"
        self.request_delay_sec = (
            float(os.getenv("VLR_REQUEST_DELAY_SEC", default_delay))
            if request_delay_sec is None
            else request_delay_sec
        )
        self.timeout = timeout
        self.api_max_workers = api_max_workers or int(
            os.getenv("VLR_API_MAX_WORKERS", os.getenv("VLR_MAX_WORKERS", "10"))
        )
        self.html_max_workers = html_max_workers or int(
            os.getenv("VLR_HTML_MAX_WORKERS", default_html_workers)
        )
        self.max_workers = max_workers or self.html_max_workers
        self.session_factory = session_factory or VlrSessionFactory(
            site_base=self.site_base,
            pool_maxsize=max(self.html_max_workers, 4),
            use_ip_rotator=self.use_ip_rotator,
        )
        self._html_semaphore = threading.Semaphore(self.html_max_workers)
        self._cooldown_lock = threading.Lock()
        self._cooldown_until = 0.0
        self._html_attempts = int(os.getenv("VLR_HTML_ATTEMPTS", "4" if self.use_ip_rotator else "6"))

        if self.use_ip_rotator:
            # Ensure gateway is provisioned once up front (fail fast if bad creds).
            VlrIpRotator.get_gateway(self.site_base)

        logger.info(
            "VlrConnector ready api_workers=%s html_workers=%s delay=%ss ip_rotator=%s",
            self.api_max_workers,
            self.html_max_workers,
            self.request_delay_sec,
            self.use_ip_rotator,
        )

    def shutdown(self) -> None:
        """Tear down AWS API Gateway endpoints for this site."""
        if self.use_ip_rotator:
            VlrIpRotator.shutdown(self.site_base)

    def _throttle(self) -> None:
        if self.request_delay_sec > 0:
            time.sleep(self.request_delay_sec)

    def _wait_cooldown(self) -> None:
        with self._cooldown_lock:
            wait = self._cooldown_until - time.monotonic()
        if wait > 0:
            logger.warning("HTML cooldown: sleeping %.1fs", wait)
            time.sleep(wait)

    def _trip_cooldown(self, seconds: float = 8.0) -> None:
        with self._cooldown_lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        session: requests.Session | None = None,
    ) -> dict[str, Any]:
        self._throttle()
        request_session = session or self.session_factory.create(for_html=False)
        url = f"{self.api_base}/{path.lstrip('/')}"
        logger.debug("GET JSON %s params=%s", url, params)
        response = request_session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_html(
        self,
        path_or_url: str,
        *,
        session: requests.Session | None = None,
    ) -> str:
        if path_or_url.startswith("http"):
            url = path_or_url
        else:
            url = urljoin(self.site_base + "/", path_or_url.lstrip("/"))

        request_session = session or self.session_factory.create(for_html=True)
        last_error: Exception | None = None

        with self._html_semaphore:
            for attempt in range(1, self._html_attempts + 1):
                self._wait_cooldown()
                self._throttle()
                try:
                    logger.debug(
                        "GET HTML %s (attempt %s rotator=%s)",
                        url,
                        attempt,
                        self.use_ip_rotator,
                    )
                    response = request_session.get(url, timeout=self.timeout)
                    if response.status_code == 429:
                        self._trip_cooldown(5.0 if self.use_ip_rotator else 12.0)
                        last_error = requests.HTTPError(
                            f"429 Too Many Requests for {url}", response=response
                        )
                        time.sleep(min(1.5 * attempt, 10.0))
                        continue
                    response.raise_for_status()
                    return response.text
                except (requests.ConnectionError, requests.Timeout) as exc:
                    last_error = exc
                    refused = "Connection refused" in str(exc) or "Errno 61" in str(exc)
                    # With IP rotation, brief pause then try again (new egress IP).
                    if self.use_ip_rotator:
                        cooldown = 2.0 if refused else 1.0
                        sleep_for = min(1.5 * attempt, 8.0)
                    else:
                        cooldown = 30.0 if refused else 8.0
                        sleep_for = min((3.0 ** (attempt - 1)), 45.0)
                    self._trip_cooldown(cooldown)
                    logger.warning(
                        "HTML fetch failed attempt %s/%s url=%s (%s); retry in %.1fs",
                        attempt,
                        self._html_attempts,
                        url,
                        exc.__class__.__name__,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                except requests.HTTPError:
                    raise

        assert last_error is not None
        raise last_error

    def get_events_page(
        self,
        page: int = 1,
        *,
        status: str = "completed",
        region: str | None = None,
        session: requests.Session | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"page": page, "status": status}
        if region:
            params["region"] = region
        payload = self._get_json("events", params=params, session=session)
        return list(payload.get("data") or [])

    def _fetch_events_page(
        self,
        page: int,
        *,
        status: str,
        region: str | None,
        progress: PageFetchProgress,
    ) -> tuple[int, list[dict[str, Any]]]:
        worker = threading.current_thread().name
        session = self.session_factory.create(for_html=False)
        batch = self.get_events_page(page, status=status, region=region, session=session)
        progress.mark_page_complete(page=page, count=len(batch), worker=worker)
        return page, batch

    def get_all_events(
        self,
        *,
        status: str = "completed",
        page_start: int = 1,
        page_end: int = 59,
        region: str | None = None,
        parallel: bool = True,
    ) -> list[dict[str, Any]]:
        pages = list(range(page_start, page_end + 1))
        if not pages:
            return []

        total_pages = len(pages)
        progress = PageFetchProgress(resource="events", total_pages=total_pages)
        logger.info(
            "Fetching events status=%s pages %s-%s parallel=%s workers=%s",
            status,
            page_start,
            page_end,
            parallel,
            self.api_max_workers,
        )

        page_batches: dict[int, list[dict[str, Any]]] = {}

        if not parallel or len(pages) == 1:
            session = self.session_factory.create(for_html=False)
            for page in pages:
                batch = self.get_events_page(page, status=status, region=region, session=session)
                progress.mark_page_complete(
                    page=page,
                    count=len(batch),
                    worker=threading.current_thread().name,
                )
                page_batches[page] = batch
                if not batch:
                    break
        else:
            with ThreadPoolExecutor(max_workers=self.api_max_workers) as pool:
                futures = {
                    pool.submit(
                        self._fetch_events_page,
                        page,
                        status=status,
                        region=region,
                        progress=progress,
                    ): page
                    for page in pages
                }
                for future in as_completed(futures):
                    page = futures[future]
                    try:
                        page_num, batch = future.result()
                    except Exception:
                        logger.exception("Error fetching events page=%s", page)
                        raise
                    page_batches[page_num] = batch

        events: list[dict[str, Any]] = []
        for page in pages:
            batch = page_batches.get(page, [])
            if not batch:
                break
            events.extend(batch)

        logger.info(
            "Fetched %s events (status=%s pages %s-%s)",
            len(events),
            status,
            page_start,
            page_end,
        )
        return events

    def get_teams_page(self, page: int = 1, limit: int = 50) -> dict[str, Any]:
        return self._get_json("teams", params={"page": page, "limit": limit})

    def get_all_teams(self, *, max_pages: int | None = None, parallel: bool = True) -> list[dict[str, Any]]:
        first = self.get_teams_page(page=1, limit=50)
        teams = list(first.get("data") or [])
        pagination = first.get("pagination") or {}
        total_pages = int(pagination.get("totalPages") or 1)
        if max_pages is not None:
            total_pages = min(total_pages, max_pages)
        if total_pages <= 1:
            return teams

        pages = list(range(2, total_pages + 1))
        progress = PageFetchProgress(resource="teams", total_pages=total_pages, completed_pages=1)

        def _fetch(page: int) -> tuple[int, list[dict[str, Any]]]:
            session = self.session_factory.create(for_html=False)
            payload = self._get_json("teams", params={"page": page, "limit": 50}, session=session)
            batch = list(payload.get("data") or [])
            progress.mark_page_complete(
                page=page,
                count=len(batch),
                worker=threading.current_thread().name,
            )
            return page, batch

        page_batches: dict[int, list[dict[str, Any]]] = {}
        if parallel:
            with ThreadPoolExecutor(max_workers=self.api_max_workers) as pool:
                futures = {pool.submit(_fetch, page): page for page in pages}
                for future in as_completed(futures):
                    page_num, batch = future.result()
                    page_batches[page_num] = batch
        else:
            for page in pages:
                page_num, batch = _fetch(page)
                page_batches[page_num] = batch

        for page in pages:
            teams.extend(page_batches.get(page, []))
        return teams

    def get_players_page(self, page: int = 1, limit: int = 50) -> dict[str, Any]:
        return self._get_json("players", params={"page": page, "limit": limit})

    def get_event_matches_html(self, event_id: str | int, *, session: requests.Session | None = None) -> str:
        return self.get_html(f"/event/matches/{event_id}/", session=session)

    def get_match_html(
        self,
        match_id: str | int,
        *,
        tab: str | None = None,
        session: requests.Session | None = None,
    ) -> str:
        path = f"/{match_id}"
        if tab and tab != "overview":
            path = f"/{match_id}/?tab={tab}"
        return self.get_html(path, session=session)

    def map_parallel(
        self,
        items: list[Any],
        worker_fn,
        *,
        desc: str,
    ) -> list[Any]:
        if not items:
            return []
        results: list[Any] = []
        workers = self.html_max_workers
        logger.info("Parallel %s: %s items workers=%s", desc, len(items), workers)

        def _run(item: Any) -> Any:
            session = self.session_factory.create(for_html=True)
            return worker_fn(item, session)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run, item): item for item in items}
            done = 0
            for future in as_completed(futures):
                item = futures[future]
                try:
                    results.append(future.result())
                except Exception:
                    logger.exception("Parallel %s failed for item=%s", desc, item)
                    raise
                done += 1
                if done % 25 == 0 or done == len(items):
                    logger.info("Parallel %s progress %s/%s", desc, done, len(items))
        return results
