import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://be-prod.rib.gg/v1"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROBE_CANDIDATES: list[tuple[str, dict[str, Any]]] = [
    ("teams/all", {"take": 3}),
    ("teams", {"skip": 0, "take": 3}),
    ("events", {"skip": 0, "take": 2}),
    ("series", {"skip": 0, "take": 2}),
    ("players", {"skip": 0, "take": 2}),
    ("players/all", {"take": 3}),
    ("agents", {"skip": 0, "take": 5}),
    ("agents/all", {"take": 5}),
    ("maps", {"skip": 0, "take": 5}),
    ("maps/all", {"take": 5}),
    ("weapons", {"skip": 0, "take": 5}),
    ("weapons/all", {"take": 5}),
    ("matches/227686/details", {}),
]


class RibsSessionFactory:
    """
    Build requests sessions configured with retry behavior for the RIB.GG API.
    """

    def __init__(self, total_retries: int = 5, backoff_factor: int = 1):
        self.total_retries = total_retries
        self.backoff_factor = backoff_factor

    def create(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=self.total_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session


@dataclass
class PageFetchProgress:
    """Thread-safe progress tracker for paginated fetches."""

    resource: str
    total_pages: int
    completed_pages: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark_page_complete(self, *, skip: int, count: int, worker: str) -> None:
        with self.lock:
            self.completed_pages += 1
            logger.info(
                "[%s] %s skip=%s got %s rows (page %s/%s)",
                worker,
                self.resource,
                skip,
                count,
                self.completed_pages,
                self.total_pages,
            )


# Backward-compatible alias
SeriesFetchProgress = PageFetchProgress


class RibsConnector:
    """
    A connector for the public RIB.GG API.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        page_size: int = 100,
        max_workers: int = 10,
        timeout: int = 30,
        session_factory: RibsSessionFactory | None = None,
    ):
        logger.info("Initializing RibsConnector")
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.max_workers = max_workers
        self.timeout = timeout
        self.session_factory = session_factory or RibsSessionFactory()

    def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        session: requests.Session | None = None,
        raise_for_status: bool = True,
    ) -> Any:
        request_session = session or self.session_factory.create()
        response = request_session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            params=params,
            timeout=self.timeout,
        )
        if raise_for_status:
            response.raise_for_status()
        if response.status_code >= 400:
            return {
                "_error": True,
                "status_code": response.status_code,
                "text": response.text[:300],
            }
        return response.json()

    def get_series_head_to_head(self, team1_id: int, team2_id: int) -> dict[str, Any]:
        """Fetch head-to-head series data between two teams."""
        return self._request(
            "series/head-to-head",
            params={"team1Id": team1_id, "team2Id": team2_id},
        )

    def get_team(self, team_id: int) -> dict[str, Any]:
        """Fetch a single team by id (includes nested players when available)."""
        return self._request(f"teams/{team_id}")

    def get_match_details(self, match_id: int) -> dict[str, Any]:
        """
        Fetch match details for fact tables (Phase 2).

        Endpoint: GET /matches/{id}/details
        """
        return self._request(f"matches/{match_id}/details")

    def _fetch_page(
        self,
        path: str,
        skip: int,
        progress: PageFetchProgress,
    ) -> dict[str, Any]:
        worker = threading.current_thread().name
        session = self.session_factory.create()
        page = self._request(
            path,
            params={"skip": skip, "take": self.page_size},
            session=session,
        )
        progress.mark_page_complete(
            skip=skip,
            count=len(page.get("data", [])),
            worker=worker,
        )
        return page

    def get_all_paginated(self, path: str, *, parallel: bool = False) -> list[dict[str, Any]]:
        """
        Fetch all rows from a skip/take paginated list endpoint.

        Expects response shape: {data: [...], meta: {total: N}}.
        """
        path = path.lstrip("/")
        logger.info(
            "Fetching /%s (page_size=%s parallel=%s) — requesting first page...",
            path,
            self.page_size,
            parallel,
        )
        first_page = self._request(path, params={"skip": 0, "take": self.page_size})
        if not isinstance(first_page, dict) or "data" not in first_page:
            raise RuntimeError(f"Unexpected response from /{path}: missing data/meta")

        total = int(first_page.get("meta", {}).get("total", len(first_page.get("data", []))))
        rows = list(first_page.get("data", []))
        total_pages = max(1, (total + self.page_size - 1) // self.page_size)
        progress = PageFetchProgress(
            resource=path,
            total_pages=total_pages,
            completed_pages=1,
        )

        logger.info(
            "/%s first page OK: got %s rows; meta.total=%s => %s pages (parallel=%s workers=%s)",
            path,
            len(rows),
            total,
            total_pages,
            parallel,
            self.max_workers,
        )

        remaining_skips = list(range(self.page_size, total, self.page_size))
        if not remaining_skips:
            logger.info("Fetched %s / %s %s", len(rows), total, path)
            return rows

        if not parallel:
            session = self.session_factory.create()
            for skip in remaining_skips:
                page = self._request(
                    path,
                    params={"skip": skip, "take": self.page_size},
                    session=session,
                )
                batch = page.get("data", [])
                progress.mark_page_complete(
                    skip=skip,
                    count=len(batch),
                    worker=threading.current_thread().name,
                )
                rows.extend(batch)
            logger.info("Fetched %s / %s %s", len(rows), total, path)
            return rows

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._fetch_page, path, skip, progress): skip
                for skip in remaining_skips
            }
            for future in as_completed(futures):
                skip = futures[future]
                try:
                    page = future.result()
                except Exception:
                    logger.exception("Error fetching %s page at skip=%s", path, skip)
                    raise
                rows.extend(page.get("data", []))

        logger.info("Fetched %s / %s %s", len(rows), total, path)
        return rows

    def get_all_events(self, *, parallel: bool = False) -> list[dict[str, Any]]:
        return self.get_all_paginated("events", parallel=parallel)

    def get_all_series(self, *, parallel: bool = True) -> list[dict[str, Any]]:
        return self.get_all_paginated("series", parallel=parallel)

    def get_all_series_parallel(self) -> list[dict[str, Any]]:
        """Fetch all series using parallel pagination."""
        return self.get_all_series(parallel=True)

    def get_all_teams(self) -> list[dict[str, Any]]:
        """
        Prefer /teams/all?take=N; fall back to paginated /teams.
        """
        try:
            payload = self._request("teams/all", params={"take": 100000})
            if isinstance(payload, list):
                logger.info("Fetched %s teams from /teams/all", len(payload))
                return payload
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                rows = payload["data"]
                logger.info("Fetched %s teams from /teams/all", len(rows))
                return rows
        except Exception:
            logger.exception("/teams/all failed; falling back to paginated /teams")

        return self.get_all_paginated("teams", parallel=False)

    def probe_endpoints(self) -> list[dict[str, Any]]:
        """
        Probe known rib.gg endpoints and return status + sample column info.

        Soft-fails per endpoint (does not raise on 4xx/5xx) so Dagster can log availability.
        Uses a no-retry session so HTTP codes like 503 are reported instead of RetryError.
        """
        results: list[dict[str, Any]] = []
        # No retries: probe should report the raw status quickly.
        session = requests.Session()
        total = len(PROBE_CANDIDATES)
        logger.info("Starting endpoint probe against %s (%s candidates)", self.base_url, total)

        for index, (path, params) in enumerate(PROBE_CANDIDATES, start=1):
            url = f"{self.base_url}/{path}"
            entry: dict[str, Any] = {"path": path, "params": params, "url": url}
            logger.info("[%s/%s] Probing GET %s params=%s ...", index, total, url, params)
            try:
                response = session.get(url, params=params, timeout=min(self.timeout, 15))
                entry["status_code"] = response.status_code
                if response.status_code != 200:
                    entry["ok"] = False
                    entry["error"] = response.text[:300] or response.reason
                    results.append(entry)
                    logger.warning(
                        "[%s/%s] FAIL %s -> HTTP %s error=%s",
                        index,
                        total,
                        path,
                        response.status_code,
                        entry["error"],
                    )
                    continue

                data = response.json()
                sample: Any
                meta = None
                n_returned = 0
                if isinstance(data, dict) and isinstance(data.get("data"), list):
                    sample = data["data"][0] if data["data"] else {}
                    meta = data.get("meta")
                    n_returned = len(data["data"])
                elif isinstance(data, list):
                    sample = data[0] if data else {}
                    n_returned = len(data)
                elif isinstance(data, dict):
                    sample = data
                    n_returned = 1
                else:
                    sample = {}

                columns = sorted(sample.keys()) if isinstance(sample, dict) else []
                nested = {
                    key: type(value).__name__
                    for key, value in sample.items()
                    if isinstance(value, (dict, list))
                } if isinstance(sample, dict) else {}

                entry.update(
                    {
                        "ok": True,
                        "meta": meta,
                        "n_returned": n_returned,
                        "columns": columns,
                        "nested": nested,
                    }
                )
                logger.info(
                    "[%s/%s] OK %s -> HTTP 200 rows=%s meta=%s columns=%s nested=%s",
                    index,
                    total,
                    path,
                    n_returned,
                    meta,
                    columns,
                    list(nested.keys()),
                )
            except Exception as exc:
                entry["ok"] = False
                entry["status_code"] = None
                entry["error"] = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "[%s/%s] ERROR %s -> no HTTP status (network/timeout/retry). %s",
                    index,
                    total,
                    path,
                    entry["error"],
                )

            results.append(entry)

        ok_count = sum(1 for r in results if r.get("ok"))
        logger.info(
            "Probe finished: %s/%s endpoints healthy. Downstream extract will fail if core "
            "endpoints (teams/events/series) are down.",
            ok_count,
            total,
        )
        return results
