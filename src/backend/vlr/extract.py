"""
VLR extract pipeline: events → event matches → match details → parquet landings.

Scrapes run in parallel via VlrConnector (ThreadPoolExecutor), same pattern as RibsConnector.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import polars as pl

from backend.api_connectors.vlr_connector import VlrConnector
from backend.vlr.checkpoints import CheckpointStore
from backend.vlr.event_matches import parse_event_matches_html
from backend.vlr.match_parser import VLRMatchParser

logger = logging.getLogger(__name__)


def landing_dir_for(repo_root: Path, entity: str, run_date: date | None = None) -> Path:
    run_date = run_date or date.today()
    path = repo_root / "data" / "vlr" / entity / f"dt={run_date.isoformat()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_parquet(rows: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        # empty schema-less frame still useful as marker
        pl.DataFrame({"_empty": []}).write_parquet(path)
        logger.info("Wrote empty parquet -> %s", path)
        return path
    df = pl.DataFrame(rows, infer_schema_length=None, strict=False)
    df.write_parquet(path)
    logger.info("Wrote %s rows x %s cols -> %s", df.height, df.width, path)
    return path


def append_parquet(rows: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return path
    new_df = pl.DataFrame(rows, infer_schema_length=None, strict=False)
    if path.exists():
        try:
            old = pl.read_parquet(path)
            if "_empty" in old.columns and old.height == 0:
                df = new_df
            else:
                df = pl.concat([old, new_df], how="diagonal_relaxed")
        except Exception:
            df = new_df
    else:
        df = new_df
    df.write_parquet(path)
    logger.info("Appended to %s (now %s rows)", path, df.height)
    return path


def normalize_event_record(event: dict[str, Any]) -> dict[str, Any]:
    dates_raw = event.get("dates")
    start_date = end_date = None
    if isinstance(dates_raw, str):
        # e.g. "May 10 Jul 26" — keep raw; optional parse later
        parts = dates_raw.split()
        if len(parts) >= 2:
            start_date = " ".join(parts[:2]) if len(parts) >= 4 else dates_raw
            end_date = " ".join(parts[-2:]) if len(parts) >= 4 else None
    event_id = str(event.get("id"))
    return {
        "id": event_id,
        "name": event.get("name"),
        "status": event.get("status"),
        "prizepool": event.get("prizepool"),
        "dates_raw": dates_raw,
        "start_date": start_date,
        "end_date": end_date,
        "country": event.get("country"),
        "img": event.get("img"),
        "url": f"https://www.vlr.gg/event/{event_id}",
    }


class VlrExtractPipeline:
    def __init__(
        self,
        repo_root: Path,
        connector: VlrConnector | None = None,
        run_date: date | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.connector = connector or VlrConnector()
        self.run_date = run_date or date.today()
        self.checkpoint_dir = self.repo_root / "data" / "vlr" / "_checkpoints" / f"dt={self.run_date.isoformat()}"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._io_lock = threading.Lock()

    def _path(self, entity: str, filename: str = "data.parquet") -> Path:
        return landing_dir_for(self.repo_root, entity, self.run_date) / filename

    def extract_events(self) -> Path:
        page_start = int(os.getenv("VLR_EVENT_PAGE_START", "1"))
        page_end = int(os.getenv("VLR_EVENT_PAGE_END", "59"))
        status = os.getenv("VLR_EVENT_STATUS", "completed")
        parallel = os.getenv("VLR_PARALLEL", "1") not in ("0", "false", "False")
        logger.info(
            "[vlr_extract_events] Fetching events status=%s pages %s-%s parallel=%s workers=%s",
            status,
            page_start,
            page_end,
            parallel,
            self.connector.max_workers,
        )
        events = self.connector.get_all_events(
            status=status,
            page_start=page_start,
            page_end=page_end,
            parallel=parallel,
        )
        rows = [normalize_event_record(e) for e in events]
        path = write_parquet(rows, self._path("dim_events"))
        # also keep ndjson for resume consumers
        ndjson = self._path("dim_events", "data.ndjson")
        with ndjson.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row))
                handle.write("\n")
        logger.info("[vlr_extract_events] Done: %s events -> %s", len(rows), path)
        return path

    def extract_event_matches(self, event_ids: Iterable[str] | None = None) -> Path:
        if event_ids is None:
            events_path = self._path("dim_events")
            if not events_path.exists():
                raise FileNotFoundError(f"Missing events parquet at {events_path}")
            df = pl.read_parquet(events_path)
            event_ids = [str(x) for x in df["id"].to_list()]

        event_ids = [eid for eid in event_ids]
        ckpt = CheckpointStore(self.checkpoint_dir / "event_matches_done.json")
        out_path = self._path("event_match_queue")
        pending = [eid for eid in event_ids if not ckpt.is_done(eid)]
        parallel = os.getenv("VLR_PARALLEL", "1") not in ("0", "false", "False")
        html_workers = self.connector.html_max_workers
        logger.info(
            "[vlr_extract_event_matches] %s events pending=%s done=%s parallel=%s html_workers=%s",
            len(event_ids),
            len(pending),
            ckpt.done_count,
            parallel,
            html_workers,
        )

        def _scrape_one(event_id: str, session) -> list[dict[str, Any]]:
            html = self.connector.get_event_matches_html(event_id, session=session)
            return parse_event_matches_html(html, event_id=event_id)

        batch: list[dict[str, Any]] = []
        completed = 0

        def _handle_rows(event_id: str, rows: list[dict[str, Any]]) -> None:
            nonlocal batch, completed
            with self._io_lock:
                batch.extend(rows)
                ckpt.mark_done(event_id)
                completed += 1
                if completed % 25 == 0 or completed == len(pending):
                    if batch:
                        append_parquet(batch, out_path)
                        batch = []
                    logger.info(
                        "[vlr_extract_event_matches] progress %s/%s checkpointed=%s",
                        completed,
                        len(pending),
                        ckpt.done_count,
                    )

        if not pending:
            if not out_path.exists():
                write_parquet([], out_path)
            logger.info("[vlr_extract_event_matches] Nothing pending -> %s", out_path)
            return out_path

        if not parallel:
            session = self.connector.session_factory.create(for_html=True)
            for event_id in pending:
                try:
                    rows = _scrape_one(event_id, session)
                    _handle_rows(event_id, rows)
                except Exception:
                    logger.exception("Failed event matches scrape for event_id=%s", event_id)
        else:
            with ThreadPoolExecutor(max_workers=html_workers) as pool:
                futures = {
                    pool.submit(
                        lambda eid=event_id: _scrape_one(
                            eid, self.connector.session_factory.create(for_html=True)
                        )
                    ): event_id
                    for event_id in pending
                }
                for future in as_completed(futures):
                    event_id = futures[future]
                    try:
                        rows = future.result()
                        _handle_rows(event_id, rows)
                    except Exception:
                        logger.exception("Failed event matches scrape for event_id=%s", event_id)

        with self._io_lock:
            if batch:
                append_parquet(batch, out_path)
        if not out_path.exists():
            write_parquet([], out_path)
        logger.info("[vlr_extract_event_matches] Done -> %s", out_path)
        return out_path

    def extract_match_details(self, match_ids: Iterable[str] | None = None) -> dict[str, Path]:
        if match_ids is None:
            queue_path = self._path("event_match_queue")
            if not queue_path.exists():
                raise FileNotFoundError(f"Missing match queue at {queue_path}")
            df = pl.read_parquet(queue_path)
            if "match_id" not in df.columns:
                match_ids = []
            else:
                match_ids = [str(x) for x in df["match_id"].unique().to_list()]

        match_ids = list(dict.fromkeys(match_ids))
        max_matches = os.getenv("VLR_MAX_MATCHES")
        if max_matches:
            match_ids = match_ids[: int(max_matches)]

        ckpt = CheckpointStore(self.checkpoint_dir / "match_details_done.json")
        pending = [mid for mid in match_ids if not ckpt.is_done(mid)]
        parallel = os.getenv("VLR_PARALLEL", "1") not in ("0", "false", "False")
        html_workers = self.connector.html_max_workers
        logger.info(
            "[vlr_extract_match_details] %s matches pending=%s done=%s parallel=%s html_workers=%s",
            len(match_ids),
            len(pending),
            ckpt.done_count,
            parallel,
            html_workers,
        )

        buffers: dict[str, list[dict[str, Any]]] = {
            "dim_matches": [],
            "dim_teams": [],
            "dim_players": [],
            "dim_agents": [],
            "dim_maps": [],
            "fact_match_maps": [],
            "fact_map_pickban": [],
            "fact_player_overview": [],
            "fact_player_performance": [],
            "fact_player_economy": [],
            "fact_rounds": [],
        }
        paths = {key: self._path(key) for key in buffers}
        completed = 0

        def flush() -> None:
            for key, rows in buffers.items():
                if rows:
                    append_parquet(rows, paths[key])
                    buffers[key] = []

        def _fetch_tab(match_id: str, tab: str) -> tuple[str, str | None]:
            session = self.connector.session_factory.create(for_html=True)
            try:
                return tab, self.connector.get_match_html(match_id, tab=tab, session=session)
            except Exception:
                logger.warning("No %s tab for match %s", tab, match_id)
                return tab, None

        def _scrape_one(match_id: str) -> dict[str, list[dict[str, Any]]]:
            # Tabs run sequentially per match; cross-match parallelism + HTML
            # semaphore already keep www.vlr.gg under the concurrent cap.
            tab_html: dict[str, str | None] = {}
            for tab in ("overview", "performance", "economy"):
                name, html = _fetch_tab(match_id, tab)
                tab_html[name] = html
            if not tab_html.get("overview"):
                raise RuntimeError(f"Missing overview HTML for match {match_id}")
            return VLRMatchParser(
                tab_html["overview"],
                match_id=match_id,
                performance_html=tab_html.get("performance"),
                economy_html=tab_html.get("economy"),
            ).parse()

        def _handle_parsed(match_id: str, parsed: dict[str, list[dict[str, Any]]]) -> None:
            nonlocal completed
            with self._io_lock:
                for key, rows in parsed.items():
                    if key in buffers:
                        buffers[key].extend(rows)
                ckpt.mark_done(match_id)
                completed += 1
                if completed % 10 == 0 or completed == len(pending):
                    flush()
                    logger.info(
                        "[vlr_extract_match_details] progress %s/%s checkpointed=%s",
                        completed,
                        len(pending),
                        ckpt.done_count,
                    )

        if pending:
            if not parallel:
                for match_id in pending:
                    try:
                        parsed = _scrape_one(match_id)
                        _handle_parsed(match_id, parsed)
                    except Exception:
                        logger.exception("Failed match detail scrape for match_id=%s", match_id)
            else:
                with ThreadPoolExecutor(max_workers=html_workers) as pool:
                    futures = {pool.submit(_scrape_one, mid): mid for mid in pending}
                    for future in as_completed(futures):
                        match_id = futures[future]
                        try:
                            parsed = future.result()
                            _handle_parsed(match_id, parsed)
                        except Exception:
                            logger.exception(
                                "Failed match detail scrape for match_id=%s", match_id
                            )

        with self._io_lock:
            flush()

        # Ensure files exist
        for key, path in paths.items():
            if not path.exists():
                write_parquet([], path)

        # Deduplicate dims
        for key in ("dim_teams", "dim_players", "dim_agents", "dim_maps", "dim_matches"):
            path = paths[key]
            try:
                df = pl.read_parquet(path)
                if df.height == 0 or "_empty" in df.columns:
                    continue
                subset = (
                    "id"
                    if "id" in df.columns
                    else (
                        "match_id"
                        if "match_id" in df.columns
                        else ("name" if "name" in df.columns else None)
                    )
                )
                if subset:
                    df = df.unique(subset=[subset], keep="last")
                    df.write_parquet(path)
                    logger.info("Deduped %s -> %s rows", key, df.height)
            except Exception:
                logger.exception("Dedup failed for %s", key)

        logger.info("[vlr_extract_match_details] Done")
        return paths

    def entity_paths_for_load(self) -> dict[str, Path]:
        entities = [
            "dim_events",
            "dim_teams",
            "dim_players",
            "dim_agents",
            "dim_maps",
            "dim_matches",
            "fact_match_maps",
            "fact_map_pickban",
            "fact_player_overview",
            "fact_player_performance",
            "fact_player_economy",
            "fact_rounds",
        ]
        return {name: self._path(name) for name in entities}
