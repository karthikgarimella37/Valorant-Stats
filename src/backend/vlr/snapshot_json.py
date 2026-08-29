"""Write raw vlrggapi JSON per match/event/team/player before warehouse transforms."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.vlr.watermarks import upsert_watermark

logger = logging.getLogger(__name__)


def json_landing_path(repo_root: Path, entity_type: str, entity_id: str) -> Path:
    """One file per entity so re-runs overwrite the same id."""
    path = Path(repo_root) / "data" / "vlr" / "json" / entity_type / f"{entity_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_entity_json(
    repo_root: Path,
    *,
    entity_type: str,
    entity_id: str,
    payload: Any,
    source_url: str,
) -> Path:
    """Land one API payload and bump its watermark."""
    path = json_landing_path(repo_root, entity_type, entity_id)
    logger.info("[snapshot] Writing %s/%s -> %s", entity_type, entity_id, path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    upsert_watermark(
        repo_root,
        entity_type=entity_type,
        entity_id=str(entity_id),
        source_url=source_url,
        extra={"json_path": str(path)},
    )
    logger.info("[snapshot] Done type=%s id=%s bytes=%s", entity_type, entity_id, path.stat().st_size)
    return path
