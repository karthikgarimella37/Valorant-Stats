"""Persist per-entity fetch cursors so later Dagster runs only pull new/changed VLR ids."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

WATERMARK_FILENAME = "watermarks.json"


def watermark_path(repo_root: Path) -> Path:
    """Stable JSON file until the warehouse watermark table exists."""
    path = Path(repo_root) / "data" / "vlr" / WATERMARK_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_watermarks(repo_root: Path) -> dict[str, Any]:
    """Read all entity cursors so extract can skip already-fetched ids."""
    path = watermark_path(repo_root)
    if not path.exists():
        return {"rows": []}
    return json.loads(path.read_text())


def upsert_watermark(
    repo_root: Path,
    *,
    entity_type: str,
    entity_id: str,
    source_url: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record last successful fetch for one match/event/team/player."""
    logger.info("[watermark] Upsert type=%s id=%s", entity_type, entity_id)
    doc = load_watermarks(repo_root)
    rows: list[dict[str, Any]] = list(doc.get("rows") or [])
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "source_url": source_url,
        "last_fetched_at": now,
        "last_status": "ok",
        **(extra or {}),
    }
    rows = [r for r in rows if not (r.get("entity_type") == entity_type and str(r.get("entity_id")) == str(entity_id))]
    rows.append(row)
    doc = {"updated_at": now, "rows": rows}
    path = watermark_path(repo_root)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    logger.info("[watermark] Done path=%s rows=%s", path, len(rows))
    return row
