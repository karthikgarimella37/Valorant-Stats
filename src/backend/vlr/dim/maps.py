"""Load vlr.dim_maps catalog: valorant-api.com radar + Liquipedia location (AWS rotator)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.api_connectors.liquipedia_connector import LiquipediaValorantConnector
from backend.api_connectors.valorant_api_connector import ValorantApiConnector
from backend.config.env import load_project_env
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import json_dumps
from backend.vlr.dim.wikitext import (
    earth_from_text,
    iter_templates,
    parse_lat_lon,
    quote_from_wikitext,
    strip_wiki,
    template_fields,
    text_or_none,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
LP_MAP_URL = "https://liquipedia.net/valorant/{name}"

MAP_COLS = (
    "map_name",
    "country_name",
    "location_name",
    "earth_name",
    "coordinates_text",
    "latitude",
    "longitude",
    "spike_sites",
    "map_features",
    "description",
    "release_date",
    "minimap_url",
    "splash_url",
    "list_view_icon_url",
    "x_multiplier",
    "y_multiplier",
    "x_scalar",
    "y_scalar",
    "min_x",
    "min_y",
    "max_x",
    "max_y",
    "valorant_api_uuid",
    "liquipedia_url",
    "callouts_json",
    "features_json",
    "infobox_json",
    "insert_date",
    "update_date",
)
JSON_COLS = ("callouts_json", "features_json", "infobox_json")
MAP_TYPES = {
    "row_number": "BIGINT",
    "map_name": "TEXT",
    "country_name": "TEXT",
    "location_name": "TEXT",
    "earth_name": "TEXT",
    "coordinates_text": "TEXT",
    "latitude": "DOUBLE PRECISION",
    "longitude": "DOUBLE PRECISION",
    "spike_sites": "TEXT",
    "map_features": "TEXT",
    "description": "TEXT",
    "release_date": "TEXT",
    "minimap_url": "TEXT",
    "splash_url": "TEXT",
    "list_view_icon_url": "TEXT",
    "x_multiplier": "DOUBLE PRECISION",
    "y_multiplier": "DOUBLE PRECISION",
    "x_scalar": "DOUBLE PRECISION",
    "y_scalar": "DOUBLE PRECISION",
    "min_x": "DOUBLE PRECISION",
    "min_y": "DOUBLE PRECISION",
    "max_x": "DOUBLE PRECISION",
    "max_y": "DOUBLE PRECISION",
    "valorant_api_uuid": "TEXT",
    "liquipedia_url": "TEXT",
    "callouts_json": "JSONB",
    "features_json": "JSONB",
    "infobox_json": "JSONB",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}

SKIP_MAP_NAMES = {"The Range", "Basic Training"}


def is_catalog_map(name: str | None) -> bool:
    """Drop Range / training / Skirmish so dim_maps is competitive maps only."""
    text = (name or "").strip()
    if not text:
        return False
    if text in SKIP_MAP_NAMES:
        return False
    if text.lower().startswith("skirmish"):
        return False
    return True


def _map_rank(api_map: dict[str, Any]) -> int:
    """Prefer the UUID that has a minimap and callouts when names collide."""
    score = 0
    if api_map.get("displayIcon"):
        score += 10
    callouts = api_map.get("callouts") or []
    if isinstance(callouts, list):
        score += len(callouts)
    if api_map.get("narrativeDescription"):
        score += 5
    return score


def unique_api_maps(api_maps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per displayName so ON CONFLICT map_name does not CardinalityViolation."""
    best: dict[str, dict[str, Any]] = {}
    skipped = 0
    for row in api_maps:
        name = text_or_none(row.get("displayName"))
        if not is_catalog_map(name):
            skipped += 1
            continue
        assert name is not None
        prev = best.get(name)
        if prev is None or _map_rank(row) > _map_rank(prev):
            best[name] = row
    logger.info("[maps] Catalog maps=%s skipped_training=%s", len(best), skipped)
    return list(best.values())


def unique_map_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Last-write-wins unique on map_name before upsert."""
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = text_or_none(row.get("map_name"))
        if not is_catalog_map(name):
            continue
        assert name is not None
        by_name[name] = row
    return list(by_name.values())


def _useful_feature(bit: str | None) -> bool:
    """Infobox teleporters=0 is not a map feature."""
    if not bit:
        return False
    return bit.strip().lower() not in {"0", "none", "n/a", "no", "false", "-"}


def _spike_sites_from_fields(fields: dict[str, str]) -> str | None:
    """sites=A/B, or bombsites=2/3 → A/B / A/B/C."""
    raw = strip_wiki(fields.get("sites") or fields.get("spikesites") or fields.get("spike_sites"))
    if raw and not raw.isdigit():
        return raw
    n = as_int(raw or fields.get("bombsites"))
    if n == 2:
        return "A/B"
    if n == 3:
        return "A/B/C"
    return None


def _root(repo_root: Path | None) -> Path:
    """Resolve repo root so CLI and Dagster share one landing path."""
    return Path(repo_root or REPO_ROOT)


def maps_jsonl_path(repo_root: Path) -> Path:
    """Landing so a failed upsert can retry without hitting Liquipedia again."""
    return repo_root / "data" / "vlr" / "dim_maps.jsonl"


def apply_maps_schema(repo_root: Path | None = None) -> Path:
    """Create dim_maps if missing; ADD catalog columns (no DROP)."""
    load_project_env(repo_root)
    return apply_dim_schema(_root(repo_root), "vlr_dim_maps.sql", "dim_maps", MAP_TYPES)


def _as_float(value: Any) -> float | None:
    """Radar multipliers and callout x/y are floats on valorant-api.com."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_liquipedia_map(wikitext: str) -> dict[str, Any]:
    """Infobox map (location, country, earth, sites, features) + official Quote."""
    info: dict[str, Any] = {"infobox": {}}
    boxes = iter_templates(wikitext, "Infobox map")
    if boxes:
        fields = template_fields(boxes[0])
        info["location_name"] = strip_wiki(
            fields.get("location") or fields.get("city") or fields.get("place")
        )
        info["country_name"] = strip_wiki(fields.get("country") or fields.get("nation"))
        info["earth_name"] = strip_wiki(fields.get("earth") or fields.get("world")) or earth_from_text(
            info.get("location_name"),
            fields.get("location"),
        )
        info["coordinates_text"] = strip_wiki(fields.get("coordinates") or fields.get("coords"))
        info["spike_sites"] = strip_wiki(fields.get("sites") or fields.get("spikesites") or fields.get("spike_sites"))
        feature_bits = [
            strip_wiki(fields.get("features")),
            strip_wiki(fields.get("teleporters")),
            strip_wiki(fields.get("doors")),
            strip_wiki(fields.get("mechanics")),
        ]
        info["map_features"] = ", ".join(bit for bit in feature_bits if bit) or None
        info["release_date"] = text_or_none(fields.get("releasedate") or fields.get("release_date"))
        info["infobox"] = {
            key: strip_wiki(value)
            for key, value in fields.items()
            if key not in _SKIP_INFOBOX and strip_wiki(value)
        }
        if not info.get("earth_name"):
            info["earth_name"] = earth_from_text(str(info.get("infobox") or ""))
    info["description"] = quote_from_wikitext(wikitext)
    return info


def _callouts_and_bounds(api_map: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, float] | None]:
    """Callout world x/y plus min/max so radar plots know map size."""
    rows: list[dict[str, Any]] = []
    xs: list[float] = []
    ys: list[float] = []
    for callout in api_map.get("callouts") or []:
        if not isinstance(callout, dict):
            continue
        loc = callout.get("location") if isinstance(callout.get("location"), dict) else {}
        x = _as_float(loc.get("x"))
        y = _as_float(loc.get("y"))
        if x is not None:
            xs.append(x)
        if y is not None:
            ys.append(y)
        rows.append(
            {
                "region_name": text_or_none(callout.get("regionName")),
                "super_region_name": text_or_none(callout.get("superRegionName")),
                "x": x,
                "y": y,
            }
        )
    bounds = None
    if xs and ys:
        bounds = {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)}
    return rows, bounds


def format_map_row(api_map: dict[str, Any], lp: dict[str, Any]) -> dict[str, Any] | None:
    """One dim_maps row: radar math from valorant-api, place/lore from Liquipedia."""
    name = text_or_none(api_map.get("displayName"))
    if not name:
        return None
    callouts, bounds = _callouts_and_bounds(api_map)
    bounds = bounds or {}
    coord_text = lp.get("coordinates_text") or text_or_none(api_map.get("coordinates"))
    lat, lon = parse_lat_lon(coord_text)
    location = lp.get("location_name")
    earth = lp.get("earth_name") or earth_from_text(location, coord_text)
    features = lp.get("map_features")
    feature_list = [p.strip() for p in (features or "").split(",") if p.strip()]
    return {
        "map_name": name,
        "country_name": lp.get("country_name"),
        "location_name": location,
        "earth_name": earth,
        "coordinates_text": coord_text,
        "latitude": lat,
        "longitude": lon,
        "spike_sites": lp.get("spike_sites"),
        "map_features": features,
        "description": lp.get("description")
        or text_or_none(api_map.get("narrativeDescription") or api_map.get("tacticalDescription")),
        "release_date": lp.get("release_date"),
        "minimap_url": text_or_none(api_map.get("displayIcon")),
        "splash_url": text_or_none(api_map.get("splash") or api_map.get("listViewIconTall")),
        "list_view_icon_url": text_or_none(api_map.get("listViewIcon")),
        "x_multiplier": _as_float(api_map.get("xMultiplier")),
        "y_multiplier": _as_float(api_map.get("yMultiplier")),
        "x_scalar": _as_float(api_map.get("xScalarToAdd")),
        "y_scalar": _as_float(api_map.get("yScalarToAdd")),
        "min_x": bounds.get("min_x"),
        "min_y": bounds.get("min_y"),
        "max_x": bounds.get("max_x"),
        "max_y": bounds.get("max_y"),
        "valorant_api_uuid": text_or_none(api_map.get("uuid")),
        "liquipedia_url": LP_MAP_URL.format(name=name.replace(" ", "_")),
        "callouts_json": callouts,
        "features_json": feature_list,
        "infobox_json": lp.get("infobox") or {},
    }


def extract_maps(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Fetch map catalog through AWS rotator and land jsonl."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[maps] Extract start sources=valorant-api.com + liquipedia.net via AWS rotator")
    api_maps = ValorantApiConnector().get_maps()
    titles = [text_or_none(row.get("displayName")) for row in api_maps]
    titles = [t for t in titles if t]
    lp_pages = LiquipediaValorantConnector().get_pages_wikitext(titles)
    rows: list[dict[str, Any]] = []
    missing_lp = 0
    for api_map in api_maps:
        name = text_or_none(api_map.get("displayName"))
        wikitext = lp_pages.get(name or "") if name else None
        if not wikitext:
            missing_lp += 1
            lp: dict[str, Any] = {}
        else:
            lp = parse_liquipedia_map(wikitext)
        row = format_map_row(api_map, lp)
        if row:
            rows.append(row)
    rows = stamp_rows(rows)
    path = maps_jsonl_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = dict(row)
            for key in ("insert_date", "update_date"):
                stamp = payload.get(key)
                if hasattr(stamp, "isoformat"):
                    payload[key] = stamp.isoformat()
            for key in JSON_COLS:
                payload[key] = json_dumps(payload.get(key))
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    logger.info("[maps] Extract done maps=%s liquipedia_miss=%s path=%s", len(rows), missing_lp, path)
    return rows


def load_maps(rows: list[dict[str, Any]] | None = None, repo_root: Path | None = None) -> int:
    """Upsert map catalog on map_name; keep row_number on re-run."""
    load_project_env(repo_root)
    apply_maps_schema(repo_root)
    if rows is None:
        path = maps_jsonl_path(_root(repo_root))
        if not path.exists():
            raise FileNotFoundError(f"dim_maps jsonl missing at {path}. Run extract_maps first.")
        rows = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
        stamp_rows(rows)
    for row in rows:
        for key in JSON_COLS:
            if not isinstance(row.get(key), str):
                row[key] = json_dumps(row.get(key))
    loaded = upsert_dim_rows(
        rows,
        table="dim_maps",
        columns=MAP_COLS,
        conflict_column="map_name",
        jsonb_columns=JSON_COLS,
    )
    logger.info("[maps] Load done upserted=%s", loaded)
    return loaded


def run_maps(repo_root: Path | None = None) -> dict[str, int]:
    """Schema + catalog extract + upsert. Re-run when Riot ships a new map."""
    rows = extract_maps(repo_root)
    loaded = load_maps(rows, repo_root)
    return {"extracted": len(rows), "loaded": loaded}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_maps())
