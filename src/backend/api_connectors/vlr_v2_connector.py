"""HTTP client for self-hosted axsddlr/vlrggapi (/v2)."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "http://127.0.0.1:3001"
RANKING_REGIONS = (
    "na",
    "eu",
    "ap",
    "la",
    "la-s",
    "la-n",
    "oce",
    "kr",
    "mn",
    "gc",
    "br",
    "cn",
    "jp",
    "col",
)


def vlr_api_base() -> str:
    """Read the wrapper URL so Compose (`http://vlrggapi:3001`) and local runs share one env."""
    return os.getenv("VLR_API_BASE", DEFAULT_API_BASE).rstrip("/")


class VlrV2Connector:
    """Fetch JSON from vlrggapi /v2 for warehouse extracts."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int = 45,
        max_workers: int | None = None,
    ):
        self.base_url = (base_url or vlr_api_base()).rstrip("/")
        self.timeout = timeout
        self.max_workers = max_workers or int(os.getenv("VLR_API_MAX_WORKERS", "8"))
        self._lock = threading.Lock()
        logger.info(
            "[vlr_v2] Connector ready base=%s workers=%s",
            self.base_url,
            self.max_workers,
        )

    def _session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=4,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=max(self.max_workers, 4))
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"Accept": "application/json", "User-Agent": "valorant-stats-extract/1.0"})
        return session

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET one /v2 path and unwrap `{status, data}` so callers see the payload only."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        logger.debug("[vlr_v2] GET %s params=%s", url, params)
        response = self._session().get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    def health(self) -> dict[str, Any]:
        """Fail fast if the self-hosted wrapper is down."""
        return self.get_json("v2/health")

    def get_events_page(self, page: int, query: str) -> list[dict[str, Any]]:
        """One events list page (`q=completed|upcoming|live`)."""
        data = self.get_json("v2/events", params={"q": query, "page": page})
        if isinstance(data, dict):
            return list(data.get("segments") or [])
        return []

    def get_event_detail(self, event_id: str) -> dict[str, Any]:
        """Event prizes + participating teams/rosters."""
        data = self.get_json(f"v2/event/{event_id}")
        if isinstance(data, dict) and "segments" in data:
            inner = data["segments"]
            return inner if isinstance(inner, dict) else {"raw": inner}
        return data if isinstance(data, dict) else {}

    def get_event_matches(self, event_id: str) -> list[dict[str, Any]]:
        """All series for one event."""
        data = self.get_json("v2/events/matches", params={"event_id": event_id})
        if isinstance(data, dict):
            return list(data.get("matches") or [])
        return []

    def get_match_details(self, match_id: str) -> dict[str, Any]:
        """Map stats, rounds, performance, economy for one series."""
        data = self.get_json("v2/match/details", params={"match_id": match_id})
        return data if isinstance(data, dict) else {}

    def get_team_profile(self, team_id: str) -> dict[str, Any]:
        """Roster + country for a VLR team id."""
        data = self.get_json("v2/team", params={"id": team_id, "q": "profile"})
        return data if isinstance(data, dict) else {}

    def get_rankings(self, region: str) -> list[dict[str, Any]]:
        """Regional ranking rows (name/country; often no team id)."""
        data = self.get_json("v2/rankings", params={"region": region})
        if isinstance(data, dict):
            return list(data.get("segments") or [])
        return []

    def map_parallel(self, items: list[Any], worker_fn, *, desc: str) -> list[Any]:
        """Run independent /v2 item fetches on a thread pool."""
        if not items:
            return []
        logger.info("[vlr_v2] Parallel %s items=%s workers=%s", desc, len(items), self.max_workers)
        results: list[Any] = []
        done = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(worker_fn, item): item for item in items}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    results.append(future.result())
                except Exception:
                    logger.exception("[vlr_v2] %s failed for item=%s", desc, item)
                    raise
                done += 1
                if done % 25 == 0 or done == len(items):
                    logger.info("[vlr_v2] %s progress %s/%s", desc, done, len(items))
        return results
