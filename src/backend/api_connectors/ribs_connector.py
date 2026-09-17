import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import requests

from backend.api_connectors.rotating_http import rotating_session

BASE_URL = "https://be-prod.rib.gg/v1"
RIB_SITE = "https://be-prod.rib.gg"

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
    """Build rib.gg sessions that leave through AWS API Gateway, never the host IP."""

    def __init__(self, total_retries: int = 5, backoff_factor: int = 1):
        self.total_retries = total_retries
        self.backoff_factor = backoff_factor

    def create(self) -> requests.Session:
        """rib.gg via AWS rotator so the host IP is never used."""
        return rotating_session(RIB_SITE)


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

    def get_all_weapons(self) -> list[dict[str, Any]]:
        """Fetch the rib.gg gun catalog for dim_weapons (VLR has no weapon list)."""
        logger.info("[rib] Weapons start")
        try:
            payload = self._request("weapons/all", params={"take": 100000})
            if isinstance(payload, list) and payload:
                logger.info("[rib] Weapons done source=/weapons/all rows=%s", len(payload))
                return [row for row in payload if isinstance(row, dict)]
            if isinstance(payload, dict) and isinstance(payload.get("data"), list) and payload["data"]:
                rows = [row for row in payload["data"] if isinstance(row, dict)]
                logger.info("[rib] Weapons done source=/weapons/all rows=%s", len(rows))
                return rows
            logger.warning("[rib] /weapons/all empty or unexpected; trying paginated /weapons")
        except Exception:
            logger.exception("[rib] /weapons/all failed; trying paginated /weapons")
        rows = self.get_all_paginated("weapons", parallel=True)
        logger.info("[rib] Weapons done source=/weapons rows=%s", len(rows))
        if not rows:
            raise RuntimeError(
                "rib.gg returned 0 weapons from /weapons/all and /weapons. "
                "Check https://be-prod.rib.gg/v1/weapons"
            )
        return rows

    def probe_endpoints(self) -> list[dict[str, Any]]:
        """
        Probe known rib.gg endpoints and return status + sample column info.

        Soft-fails per endpoint (does not raise on 4xx/5xx) so Dagster can log availability.
        Uses a no-retry session so HTTP codes like 503 are reported instead of RetryError.
        """
        results: list[dict[str, Any]] = []
        # No retries: probe should report the raw status quickly.
        session = rotating_session(RIB_SITE)
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


RIB_GG_SITE = "https://rib.gg"
RIB_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.6 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://rib.gg",
}


class RibSiteSessionFactory:
    """rib.gg site sessions through AWS API Gateway so the host IP is never used."""

    def create(self) -> requests.Session:
        """High-volume match/replay extract uses the full rotator region list."""
        from backend.api_connectors.ip_rotator_gateway import extract_rotator_regions

        return rotating_session(
            RIB_GG_SITE,
            headers=RIB_BROWSER_HEADERS,
            regions=extract_rotator_regions(),
        )


class RibSiteConnector:
    """Live rib.gg RSC pages + replay-data JSON. be-prod is stale; do not use it here."""

    def __init__(self, timeout: int = 60, max_retries: int = 10):
        logger.info("[rib_site] Init timeout=%s retries=%s", timeout, max_retries)
        self.timeout = timeout
        self.max_retries = max_retries
        self.session_factory = RibSiteSessionFactory()

    def _warm_session(self, request_session: requests.Session) -> None:
        """One homepage hit so Vercel sees a browser-like first request on this AWS IP."""
        if getattr(request_session, "_rib_warmed", False):
            return
        try:
            logger.info("[rib_site] Warm GET /")
            request_session.get(
                f"{RIB_GG_SITE}/",
                headers=dict(RIB_BROWSER_HEADERS),
                timeout=self.timeout,
            )
        except Exception:
            logger.warning("[rib_site] Warm GET / failed", exc_info=True)
        request_session._rib_warmed = True  # type: ignore[attr-defined]

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        session: requests.Session | None = None,
        expect_json: bool = False,
    ) -> requests.Response:
        """GET with 429/5xx backoff. Rotate to a new AWS IP after each 429."""
        url = f"{RIB_GG_SITE}{path}"
        request_session = session or self.session_factory.create()
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            merged = dict(RIB_BROWSER_HEADERS)
            if headers:
                merged.update(headers)
            try:
                self._warm_session(request_session)
                logger.info("[rib_site] GET %s attempt=%s/%s", path, attempt, self.max_retries)
                response = request_session.get(
                    url,
                    params=params,
                    headers=merged,
                    timeout=self.timeout,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    wait = min(2 ** attempt, 45)
                    snippet = (response.text or "").replace("\n", " ")[:180]
                    last_error = RuntimeError(
                        f"rib.gg HTTP {response.status_code} path={path} body={snippet}"
                    )
                    logger.warning(
                        "[rib_site] HTTP %s path=%s attempt=%s/%s sleep=%ss body=%s",
                        response.status_code,
                        path,
                        attempt,
                        self.max_retries,
                        wait,
                        snippet,
                    )
                    time.sleep(wait)
                    if response.status_code == 429:
                        request_session = self.session_factory.create()
                    continue
                response.raise_for_status()
                if expect_json:
                    response.json()
                logger.info("[rib_site] GET %s HTTP %s bytes=%s", path, response.status_code, len(response.content))
                return response
            except Exception as exc:
                last_error = exc
                wait = min(2 ** attempt, 45)
                logger.warning(
                    "[rib_site] Error path=%s attempt=%s/%s sleep=%ss err=%s",
                    path,
                    attempt,
                    self.max_retries,
                    wait,
                    exc,
                )
                if attempt == self.max_retries:
                    break
                time.sleep(wait)
                request_session = self.session_factory.create()
                if session is not None:
                    session = request_session
        raise RuntimeError(f"rib.gg GET failed path={path}") from last_error

    def rsc_text(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        referer: str | None = None,
        session: requests.Session | None = None,
    ) -> str:
        """RSC flight payload (header rsc=1). Needed for events/matches/roundStats."""
        query = dict(params or {})
        query.setdefault("_rsc", "1")
        headers = {"rsc": "1", "Accept": "*/*"}
        if referer:
            headers["Referer"] = referer
        response = self._get(path, params=query, headers=headers, session=session)
        return response.text

    def list_events(self, session: requests.Session | None = None) -> list[dict[str, Any]]:
        """Event cards from /events. Deduped by id."""
        from backend.rib_gg.rsc import extract_json_after

        logger.info("[rib_site] Events start")
        text = self.rsc_text("/events", referer=f"{RIB_GG_SITE}/events", session=session)
        events: list[dict[str, Any]] = []
        seen: set[str] = set()
        for payload in extract_json_after(text, "events"):
            if not isinstance(payload, list):
                continue
            for row in payload:
                if not isinstance(row, dict):
                    continue
                event_id = row.get("id")
                if event_id is None or not row.get("name"):
                    continue
                key = str(event_id)
                if key in seen:
                    continue
                seen.add(key)
                events.append(row)
        logger.info("[rib_site] Events done n=%s", len(events))
        return events

    def list_event_matches(
        self,
        event_id: str,
        slug: str,
        session: requests.Session | None = None,
    ) -> list[dict[str, Any]]:
        """Matches listed on one event page."""
        from backend.rib_gg.rsc import extract_json_after

        path = f"/events/{event_id}/{slug}"
        text = self.rsc_text(path, referer=f"{RIB_GG_SITE}{path}", session=session)
        by_id: dict[str, dict[str, Any]] = {}
        for payload in extract_json_after(text, "matches"):
            if not isinstance(payload, list) or not payload:
                continue
            first = payload[0]
            if not isinstance(first, dict) or "id" not in first:
                continue
            if "teamA" not in first and "team1" not in first:
                continue
            for row in payload:
                if isinstance(row, dict) and row.get("id") is not None:
                    by_id[str(row["id"])] = row
        return list(by_id.values())

    def get_match_page(
        self,
        match_id: str,
        *,
        map_id: str | None = None,
        tab: str | None = None,
        session: requests.Session | None = None,
    ) -> str:
        """Match HTML first (has `initial` JSON). RSC only if the document missed it."""
        from backend.rib_gg.rsc import first_initial

        params: dict[str, Any] = {}
        if map_id:
            params["map"] = map_id
        if tab:
            params["mstab"] = tab
        referer = f"{RIB_GG_SITE}/matches/{match_id}"
        html_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer,
        }
        text = self._get(
            f"/matches/{match_id}",
            params=params or None,
            headers=html_headers,
            session=session,
        ).text
        if first_initial(text):
            return text
        logger.info("[rib_site] HTML missed initial; retry RSC match=%s", match_id)
        return self.rsc_text(
            f"/matches/{match_id}",
            params=params,
            referer=referer,
            session=session,
        )

    def get_replay_data(
        self,
        match_id: str,
        map_id: str,
        session: requests.Session | None = None,
    ) -> dict[str, Any]:
        """Full replay blob for one map. Parse later into event + snapshot warehouse tables."""
        params = {"mapId": map_id}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{RIB_GG_SITE}/matches/{match_id}?map={map_id}&mstab=Replay",
        }
        response = self._get(
            f"/api/matches/{match_id}/replay-data",
            params=params,
            headers=headers,
            session=session,
            expect_json=True,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"replay-data not an object match={match_id} map={map_id}")
        return payload

