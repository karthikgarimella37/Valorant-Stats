"""Load vlr.dim_weapons from rib.gg (VLR match JSON has no gun names)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.api_connectors.ribs_connector import RibsConnector
from backend.config.env import load_project_env
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import utc_now

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]

WEAPON_COLS = (
    "weapon_name",
    "rib_weapon_id",
    "weapon_type",
    "credits",
    "fire_rate",
    "magazine_size",
    "image_url",
    "stats_json",
    "insert_date",
    "update_date",
)
WEAPON_TYPES = {
    "row_number": "BIGINT",
    "weapon_name": "TEXT",
    "rib_weapon_id": "TEXT",
    "weapon_type": "TEXT",
    "credits": "INTEGER",
    "fire_rate": "DOUBLE PRECISION",
    "magazine_size": "INTEGER",
    "image_url": "TEXT",
    "stats_json": "JSONB",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}


def _root(repo_root: Path | None) -> Path:
    return repo_root or REPO_ROOT


def weapons_jsonl_path(repo_root: Path) -> Path:
    """Landing so a failed upsert can retry without hitting rib.gg again."""
    return repo_root / "data" / "vlr" / "dim_weapons.jsonl"


def apply_weapons_schema(repo_root: Path | None = None) -> Path:
    """Create dim_weapons and a unique rib id index when present."""
    load_project_env(repo_root)
    root = _root(repo_root)
    path = apply_dim_schema(root, "vlr_dim_weapons.sql", "dim_weapons", WEAPON_TYPES)
    from backend.database_connectors.supabase_connectors import SupabaseConnector

    SupabaseConnector().execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vlr_dim_weapons_rib_id "
        "ON vlr.dim_weapons (rib_weapon_id) WHERE rib_weapon_id IS NOT NULL"
    )
    return path


def _pick(row: dict[str, Any], *keys: str) -> Any:
    """Read the first present camelCase or snake_case key from a rib payload."""
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def format_weapon_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten a rib weapon object; keep the full payload in stats_json."""
    name = str(_pick(raw, "name", "displayName", "weaponName") or "").strip()
    if not name:
        return None
    stats = _pick(raw, "weaponStats", "stats")
    stats = stats if isinstance(stats, dict) else {}
    shop = _pick(raw, "shopData", "shop")
    shop = shop if isinstance(shop, dict) else {}
    rib_id = _pick(raw, "id", "weaponId")
    return {
        "weapon_name": name,
        "rib_weapon_id": str(rib_id) if rib_id is not None else None,
        "weapon_type": str(
            _pick(raw, "type", "category", "weaponType")
            or _pick(shop, "category", "categoryText")
            or ""
        ).strip()
        or None,
        "credits": _as_int(
            _pick(raw, "cost", "credits", "price") or _pick(shop, "cost", "credits")
        ),
        "fire_rate": _as_float(_pick(raw, "fireRate", "fire_rate") or _pick(stats, "fireRate")),
        "magazine_size": _as_int(
            _pick(raw, "magazineSize", "magazine_size") or _pick(stats, "magazineSize")
        ),
        "image_url": str(
            _pick(raw, "imageUrl", "logoUrl", "displayIcon", "killStreamIcon") or ""
        ).strip()
        or None,
        "stats_json": json.dumps(raw, ensure_ascii=False, default=str),
    }


def extract_weapons(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Fetch every rib.gg weapon and land jsonl. Parallel pages live in the connector."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[weapons] Extract start source=rib.gg /weapons")
    connector = RibsConnector()
    raw_rows = connector.get_all_weapons()
    logger.info("[weapons] Fetched raw=%s", len(raw_rows))
    if raw_rows:
        logger.info("[weapons] Sample keys=%s", sorted(raw_rows[0].keys())[:40])
    seen: dict[str, dict[str, Any]] = {}
    skipped = 0
    for raw in raw_rows:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        row = format_weapon_row(raw)
        if not row:
            skipped += 1
            continue
        seen[row["weapon_name"]] = row
    rows = stamp_rows(list(seen.values()))
    path = weapons_jsonl_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = dict(row)
            stamp = payload.get("insert_date") or utc_now()
            payload["insert_date"] = stamp.isoformat() if hasattr(stamp, "isoformat") else stamp
            payload["update_date"] = payload["insert_date"]
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    logger.info("[weapons] Extract done unique=%s skipped=%s path=%s", len(rows), skipped, path)
    return rows


def load_weapons(rows: list[dict[str, Any]] | None = None, repo_root: Path | None = None) -> int:
    """Upsert weapons on weapon_name. stats_json holds leftover rib fields."""
    load_project_env(repo_root)
    apply_weapons_schema(repo_root)
    if rows is None:
        path = weapons_jsonl_path(_root(repo_root))
        if not path.exists():
            raise FileNotFoundError(f"dim_weapons jsonl missing at {path}. Run extract_weapons first.")
        rows = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
        stamp_rows(rows)
    return upsert_dim_rows(
        rows,
        table="dim_weapons",
        columns=WEAPON_COLS,
        conflict_column="weapon_name",
        jsonb_columns=("stats_json",),
    )


def run_weapons(repo_root: Path | None = None) -> dict[str, int]:
    """Schema + rib extract + upsert."""
    rows = extract_weapons(repo_root)
    loaded = load_weapons(rows, repo_root)
    return {"extracted": len(rows), "loaded": loaded}
