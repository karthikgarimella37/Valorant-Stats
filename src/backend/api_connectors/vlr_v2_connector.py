"""HTTP client for self-hosted axsddlr/vlrggapi (/v2)."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend.api_connectors.ip_rotator_gateway import VlrIpRotator, ip_rotator_enabled
from backend.config.env import load_project_env

logger = logging.getLogger(__name__)

load_project_env()
SITE_BASE = "https://www.vlr.gg"

DEFAULT_API_BASE = "http://127.0.0.1:3001"


def _req_label(path: str, params: dict[str, Any] | None) -> str:
    """Human label so Dagster 429/wait logs show which match or event was in flight."""
    params = params or {}
    if params.get("match_id"):
        return f"match_id={params['match_id']}"
    if params.get("event_id"):
        return f"event_id={params['event_id']}"
    if params.get("id"):
        extra = params.get("q")
        return f"id={params['id']}" + (f" q={extra}" if extra else "")
    return path.lstrip("/")


class RateGate:
    """Pace /v2 calls so we stay under VLR's limit instead of bursting then cooling 100s."""

    def __init__(self) -> None:
        self._slots = threading.BoundedSemaphore(int(os.getenv("VLR_API_CONCURRENCY", "2")))
        self._lock = threading.Lock()
        self._cool_until = 0.0
        self._next_start = 0.0
        self._min_interval = float(os.getenv("VLR_API_INTERVAL_SEC", "0.8"))
        self._last_cool_log = 0.0

    def acquire(self, label: str = "") -> None:
        """Wait for cooldown + min gap between starts, then take one in-flight slot."""
        while True:
            with self._lock:
                now = time.monotonic()
                wait = max(self._cool_until, self._next_start) - now
            if wait <= 0:
                break
            if wait >= 5.0:
                with self._lock:
                    if now - self._last_cool_log >= 15.0:
                        self._last_cool_log = now
                        logger.warning(
                            "[vlr_v2] waiting %.0fs %s (pace or 429 cooldown)",
                            wait,
                            label or "(unknown)",
                        )
            time.sleep(min(wait, 2.0))
        with self._lock:
            self._next_start = time.monotonic() + self._min_interval
        self._slots.acquire()

    def release(self) -> None:
        self._slots.release()

    def ok(self) -> None:
        """Keep the current pace after a success (do not reset to a burst)."""
        return

    def trip_429(self, retry_after: float | None = None, *, label: str = "") -> float:
        """Pause everyone once; cap at 45s so one 429 does not become a 100s stall."""
        with self._lock:
            wait = retry_after if retry_after and retry_after > 0 else 30.0
            wait = min(wait, 45.0)
            self._cool_until = max(self._cool_until, time.monotonic() + wait)
            logger.warning(
                "[vlr_v2] 429 %s pause=%.0fs then resume paced calls",
                label or "(unknown)",
                wait,
            )
            return wait


_GATE = RateGate()
# VLR /v2/rankings query params only (local grain). Aliases cn/la-n/la-s normalize in extract.
RANKING_REGIONS = (
    "na",
    "eu",
    "br",
    "ap",
    "kr",
    "cn",
    "jp",
    "la-n",
    "la-s",
    "oce",
    "mn",
    "gc",
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
        self._session_obj: requests.Session | None = None
        host = (urlparse(self.base_url).hostname or "").lower()
        self._rotate_api = ip_rotator_enabled() and host.endswith("vlr.gg")
        logger.info(
            "[vlr_v2] Connector ready base=%s workers=%s ip_rotator=%s (vlr.gg host only)",
            self.base_url,
            self.max_workers,
            self._rotate_api,
        )

    def _session(self) -> requests.Session:
        """Reuse one session so the AWS gateway mounts once when the API host is vlr.gg."""
        with self._lock:
            if self._session_obj is not None:
                return self._session_obj
            session = requests.Session()
            # Status retries live in get_json (short cap). urllib3 429 retries stacked and stalled workers.
            retry = Retry(total=0, connect=2, read=0, status=0, allowed_methods=["GET"])
            adapter = HTTPAdapter(max_retries=retry, pool_maxsize=max(self.max_workers, 64))
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update({"Accept": "application/json", "User-Agent": "valorant-stats-extract/1.0"})
            if self._rotate_api:
                mounted = VlrIpRotator.mount(session, SITE_BASE)
                logger.info("[vlr_v2] IP rotator mounted=%s site=%s", mounted, SITE_BASE)
            self._session_obj = session
            return session

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET one /v2 path and unwrap `{status, data}` so callers see the payload only."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempts = int(os.getenv("VLR_API_ATTEMPTS", "10"))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            pause = 0.0
            retry = False
            _GATE.acquire()
            try:
                logger.debug("[vlr_v2] GET %s params=%s attempt=%s", url, params, attempt)
                try:
                    response = self._session().get(url, params=params, timeout=self.timeout)
                except (requests.ConnectionError, requests.Timeout) as exc:
                    last_error = exc
                    pause = min(2.0 * attempt, 20.0)
                    retry = True
                    logger.warning(
                        "[vlr_v2] Connection failed %s attempt=%s/%s; sleep=%.0fs",
                        url,
                        attempt,
                        attempts,
                        pause,
                    )
                else:
                    if response.status_code in {429, 502, 503, 504}:
                        retry_after = None
                        raw = response.headers.get("Retry-After")
                        if raw:
                            try:
                                retry_after = float(raw)
                            except ValueError:
                                retry_after = None
                        if response.status_code == 429:
                            _GATE.trip_429(retry_after)
                        else:
                            pause = min(5.0 * attempt, 30.0)
                            logger.warning(
                                "[vlr_v2] status=%s %s attempt=%s/%s; sleep=%.0fs",
                                response.status_code,
                                url,
                                attempt,
                                attempts,
                                pause,
                            )
                        last_error = requests.HTTPError(
                            f"{response.status_code} for {url}", response=response
                        )
                        retry = True
                    elif response.status_code == 422:
                        response.raise_for_status()
                    else:
                        response.raise_for_status()
                        _GATE.ok()
                        payload = response.json()
                        if isinstance(payload, dict) and "data" in payload:
                            return payload["data"]
                        return payload
            finally:
                _GATE.release()
            if retry and pause:
                time.sleep(pause)
        assert last_error is not None
        raise last_error

    def _first_segment(self, data: Any) -> dict[str, Any]:
        """Unwrap vlrggapi `{status, segments:[...]}` so callers get one entity dict."""
        if isinstance(data, dict) and isinstance(data.get("segments"), list) and data["segments"]:
            first = data["segments"][0]
            return first if isinstance(first, dict) else {}
        return data if isinstance(data, dict) else {}

    def health(self) -> dict[str, Any]:
        """Fail fast if the self-hosted wrapper is down."""
        return self.get_json("v2/health")

    def get_events_page(self, page: int, query: str) -> list[dict[str, Any]]:
        """One events list page (`q=completed|upcoming|live`). Empty list past the last page."""
        try:
            data = self.get_json("v2/events", params={"q": query, "page": page})
        except requests.HTTPError as exc:
            # vlrggapi returns 422 when page is past the last catalog page.
            if exc.response is not None and exc.response.status_code == 422:
                logger.info("[vlr_v2] Events page past end q=%s page=%s", query, page)
                return []
            raise
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
        """All series for one event (`segments` is the match list)."""
        data = self.get_json("v2/events/matches", params={"event_id": event_id})
        if isinstance(data, dict):
            rows = data.get("segments") or data.get("matches") or []
            return [row for row in rows if isinstance(row, dict)]
        return []

    def get_match_details(self, match_id: str) -> dict[str, Any]:
        """Map stats, rounds, performance, economy for one series."""
        return self._first_segment(self.get_json("v2/match/details", params={"match_id": match_id}))

    def get_team_profile(self, team_id: str) -> dict[str, Any]:
        """Roster + country + socials for a VLR team id."""
        return self._first_segment(self.get_json("v2/team", params={"id": team_id, "q": "profile"}))

    def get_team_roster(self, team_id: str) -> dict[str, Any]:
        """Grouped active/staff/former/benched roster (staff flag is often wrong; use role)."""
        return self._first_segment(self.get_json("v2/team", params={"id": team_id, "q": "roster"}))

    def get_team_transactions(self, team_id: str) -> list[dict[str, Any]]:
        """Join/leave log for watermarked team history."""
        data = self.get_json("v2/team", params={"id": team_id, "q": "transactions"})
        if isinstance(data, dict) and isinstance(data.get("segments"), list):
            return [row for row in data["segments"] if isinstance(row, dict)]
        return []

    def get_player_profile(self, player_id: str, timespan: str = "all") -> dict[str, Any]:
        """Career/agent stats so player JSON landings have a stable id."""
        return self._first_segment(
            self.get_json("v2/player", params={"id": player_id, "q": "profile", "timespan": timespan})
        )

    def search(self, query: str) -> dict[str, Any]:
        """Resolve names to VLR ids when a match payload omits event_id."""
        data = self.get_json("v2/search", params={"q": query})
        if isinstance(data, dict) and isinstance(data.get("segments"), dict):
            return data["segments"]
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
