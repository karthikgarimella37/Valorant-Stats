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
class SeriesFetchProgress:
    """
    Thread-safe progress tracker for paginated series fetches.
    """

    total_pages: int
    completed_pages: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark_page_complete(self, *, skip: int, count: int, worker: str) -> None:
        with self.lock:
            self.completed_pages += 1
            logger.info(
                "[%s] skip=%s got %s series (page %s/%s)",
                worker,
                skip,
                count,
                self.completed_pages,
                self.total_pages,
            )


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
    ) -> dict[str, Any]:
        request_session = session or self.session_factory.create()
        response = request_session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_series_head_to_head(self, team1_id: int, team2_id: int) -> dict[str, Any]:
        """
        Fetch head-to-head series data between two teams.
        """
        return self._request(
            "series/head-to-head",
            params={"team1Id": team1_id, "team2Id": team2_id},
        )

    def _fetch_series_page(self, skip: int, progress: SeriesFetchProgress) -> dict[str, Any]:
        worker = threading.current_thread().name
        session = self.session_factory.create()
        page = self._request(
            "series",
            params={"skip": skip, "take": self.page_size},
            session=session,
        )
        progress.mark_page_complete(
            skip=skip,
            count=len(page.get("data", [])),
            worker=worker,
        )
        return page

    def get_all_series_parallel(self) -> list[dict[str, Any]]:
        """
        Fetch all series using parallel pagination.
        """
        first_page = self._request("series", params={"skip": 0, "take": self.page_size})
        total = first_page["meta"]["total"]
        all_series = list(first_page.get("data", []))
        total_pages = (total + self.page_size - 1) // self.page_size
        progress = SeriesFetchProgress(total_pages=total_pages, completed_pages=1)

        logger.info(
            "Total series: %s (%s pages) fetching with %s workers",
            total,
            total_pages,
            self.max_workers,
        )

        remaining_skips = list(range(self.page_size, total, self.page_size))
        if not remaining_skips:
            logger.info("Fetched %s / %s series", len(all_series), total)
            return all_series

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._fetch_series_page, skip, progress): skip
                for skip in remaining_skips
            }
            for future in as_completed(futures):
                skip = futures[future]
                try:
                    page = future.result()
                except Exception:
                    logger.exception("Error fetching series page at skip=%s", skip)
                    raise
                all_series.extend(page.get("data", []))

        logger.info("Fetched %s / %s series", len(all_series), total)
        return all_series