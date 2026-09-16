"""Load vlr.dim_weapons from valorant.fandom.com (AWS rotator)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from backend.api_connectors.fandom_connector import ValorantFandomConnector
from backend.config.env import load_project_env
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import json_dumps
from backend.vlr.dim.wikitext import (
    RANGE_KEY_RE,
    as_int,
    first_wikitable,
    iter_templates,
    quote_from_wikitext,
    strip_wiki,
    template_fields_lines,
    text_or_none,
    wiki_file_name,
    wikitable_rows,
    wikitext_after_heading,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
FANDOM_WEAPON_URL = "https://valorant.fandom.com/wiki/{name}"
WEAPONS_LIST_PAGE = "Weapons"
# Mode-only guns on the list page; competitive catalog skips them.
SKIP_WEAPON_NAMES = {"Golden Gun", "Snowball Launcher"}
LIST_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]")
HP_KEYS = ("hp_100", "hp_125", "hp_150")

WEAPON_COLS = (
    "weapon_name",
    "weapon_type",
    "credits",
    "wall_penetration",
    "length",
    "creator",
    "quote",
    "image_url",
    "icon_url",
    "killfeed_icon_url",
    "fire_rate",
    "magazine_size",
    "fandom_url",
    "rib_weapon_id",
    "fire_stats_json",
    "insert_date",
    "update_date",
)
JSON_COLS = ("fire_stats_json",)
WEAPON_TYPES = {
    "row_number": "BIGINT",
    "weapon_name": "TEXT",
    "weapon_type": "TEXT",
    "credits": "INTEGER",
    "wall_penetration": "TEXT",
    "length": "TEXT",
    "creator": "TEXT",
    "quote": "TEXT",
    "image_url": "TEXT",
    "icon_url": "TEXT",
    "killfeed_icon_url": "TEXT",
    "fire_rate": "DOUBLE PRECISION",
    "magazine_size": "INTEGER",
    "fandom_url": "TEXT",
    "rib_weapon_id": "TEXT",
    "fire_stats_json": "JSONB",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}


def _root(repo_root: Path | None) -> Path:
    """Resolve repo root so CLI and Dagster share one landing path."""
    return Path(repo_root or REPO_ROOT)


def weapons_jsonl_path(repo_root: Path) -> Path:
    """Landing so a failed upsert can retry without hitting Fandom again."""
    return repo_root / "data" / "vlr" / "dim_weapons.jsonl"


def apply_weapons_schema(repo_root: Path | None = None) -> Path:
    """Create dim_weapons; ADD Fandom columns (no DROP). Keep unique rib id if present."""
    load_project_env(repo_root)
    root = _root(repo_root)
    path = apply_dim_schema(root, "vlr_dim_weapons.sql", "dim_weapons", WEAPON_TYPES)
    from backend.database_connectors.supabase_connectors import SupabaseConnector

    SupabaseConnector().execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vlr_dim_weapons_rib_id "
        "ON vlr.dim_weapons (rib_weapon_id) WHERE rib_weapon_id IS NOT NULL"
    )
    return path


def _first_float(raw: str | None) -> float | None:
    """Pull 6.75 from '6.75 rounds/sec'."""
    text = text_or_none(raw)
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    return float(match.group(0))


def _num(raw: str | None) -> float | int | None:
    """Table cell to int when whole, else float."""
    value = _first_float(raw)
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return value


def _plain(raw: str | None) -> str | None:
    """Infobox value without wiki markup; keep spaces across <br> lines."""
    text = (raw or "").replace("<br />", " ").replace("<br/>", " ").replace("<br>", " ")
    return strip_wiki(text)


def _damage_from_cell(raw: str | None) -> dict[str, Any]:
    """Head/body/leg (or melee front/back) from an Infobox range cell."""
    text = (raw or "").replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    clean = strip_wiki(text) or ""
    out: dict[str, Any] = {}
    for match in re.finditer(
        r"(head|body|leg|front|back)\s*[-:]\s*(.+?)(?=(?:head|body|leg|front|back)\s*[-:]|$)",
        clean,
        re.I | re.S,
    ):
        key = match.group(1).lower()
        value = re.sub(r"\s+", " ", match.group(2)).strip()
        nums = [int(n) for n in re.findall(r"\d+", value)]
        out[key] = nums[0] if len(nums) == 1 else value
    if not out and text_or_none(clean):
        out["raw"] = clean
    return out


def weapon_titles_from_list(wikitext: str) -> list[str]:
    """Competitive guns from the Fandom Weapons list (skip Spike Rush / Escalation toys)."""
    start = wikitext.lower().find("==list of weapons==")
    chunk = wikitext[start:] if start >= 0 else wikitext
    end = chunk.lower().find("==update history==")
    if end > 0:
        chunk = chunk[:end]
    titles: list[str] = []
    seen: set[str] = set()
    for match in LIST_LINK_RE.finditer(chunk):
        name = match.group(1).strip()
        if name.startswith("File:") or name.startswith("Category:"):
            continue
        if name in SKIP_WEAPON_NAMES or name.lower() in seen:
            continue
        if name.lower() in {"weapons", "spike rush", "escalation", "snowball fight"}:
            continue
        seen.add(name.lower())
        titles.append(name)
    return titles


def _damage_ranges(fields: dict[str, str]) -> list[dict[str, Any]]:
    """Infobox 0-30m / 30-50m (and any other Xm-Ym) damage bands."""
    rows: list[dict[str, Any]] = []
    for key, value in fields.items():
        compact = key.replace(" ", "").replace("–", "-")
        if not RANGE_KEY_RE.match(compact):
            continue
        row = {"range": compact}
        row.update(_damage_from_cell(value))
        rows.append(row)
    return rows


def _ttk_rows(wikitext: str, *headings: str) -> list[dict[str, Any]]:
    """Primary / alt TTK tables: shots + seconds at 100/125/150 HP."""
    table = first_wikitable(wikitext_after_heading(wikitext, *headings))
    if not table:
        return []
    parsed: list[dict[str, Any]] = []
    range_name: str | None = None
    for cells in wikitable_rows(table):
        if not cells:
            continue
        joined = " ".join(cells).lower()
        if "damage" in joined and "range" in joined:
            continue
        if "bullets to kill" in joined or "bursts to kill" in joined or "time to kill" in joined:
            continue
        first = cells[0]
        if RANGE_KEY_RE.match(first.replace("–", "-").replace(" ", "")) or (
            "m" in first.lower() and re.search(r"\d", first)
        ):
            range_name = first.replace("–", "-")
            body_part = cells[1] if len(cells) > 1 else None
            nums = cells[2:]
        else:
            body_part = first
            nums = cells[1:]
        if not body_part or len(nums) < 6:
            continue
        entry: dict[str, Any] = {"range": range_name, "body_part": body_part}
        for i, hp_key in enumerate(HP_KEYS):
            shots = _num(nums[i * 2])
            time_sec = _num(nums[i * 2 + 1])
            entry[hp_key] = {"shots": shots, "time_sec": time_sec}
        parsed.append(entry)
    return parsed


def _spread_rows(wikitext: str) -> list[dict[str, Any]]:
    """Standing/crouch first-shot + max spread and movement penalties."""
    table = first_wikitable(wikitext_after_heading(wikitext, "spread values", "spread value"))
    if not table:
        return []
    out: list[dict[str, Any]] = []
    for cells in wikitable_rows(table):
        if len(cells) < 9:
            continue
        mode = cells[0]
        if not mode or "firing" in mode.lower() or "standing" in mode.lower():
            continue
        out.append(
            {
                "firing_mode": mode,
                "first_shot_standing": _num(cells[1]),
                "first_shot_crouched": _num(cells[2]),
                "max_standing": _num(cells[3]),
                "max_crouched": _num(cells[4]),
                "penalty_crouched": _num(cells[5]),
                "penalty_walking": _num(cells[6]),
                "penalty_running": _num(cells[7]),
                "penalty_airborne": _num(cells[8]),
            }
        )
    return out


def parse_fandom_weapon(wikitext: str) -> dict[str, Any]:
    """Infobox + Quote1 + TTK/spread tables from one Fandom weapon page."""
    boxes = iter_templates(wikitext, "Infobox weapon")
    fields = template_fields_lines(boxes[0]) if boxes else {}
    primary = {
        "fire_mode": _plain(fields.get("mode")),
        "fire_rate": _plain(fields.get("rate")),
        "run_speed": _plain(fields.get("run")),
        "equip_speed": _plain(fields.get("equip")),
        "reload_speed": _plain(fields.get("reload")),
        "magazine": as_int(fields.get("magazine")),
        "reserve": _plain(fields.get("reserve")),
        "first_shot_spread": _plain(fields.get("spread")),
        "damage": _damage_ranges(fields),
        "ttk": _ttk_rows(wikitext, "primary fire ttk"),
    }
    alternate = {
        "function": _plain(fields.get("function")),
        "pellet_count": as_int(fields.get("pellet")),
        "fire_rate": _plain(fields.get("altrate")),
        "zoom": _plain(fields.get("zoom")),
        "move_speed": _plain(fields.get("move")),
        "spread": _plain(fields.get("altspread")),
        "notes": _plain(fields.get("notes")),
        "ttk": _ttk_rows(wikitext, "alternate fire ttk", "alt fire ttk", "ads ttk"),
    }
    if not any(
        alternate[key]
        for key in ("function", "pellet_count", "fire_rate", "zoom", "move_speed", "spread", "notes")
    ) and not alternate["ttk"]:
        alternate = None
    return {
        "weapon_name": _plain(fields.get("title")),
        "weapon_type": _plain(fields.get("type")),
        "credits": as_int(fields.get("credits")),
        "wall_penetration": _plain(fields.get("penetration")),
        "length": _plain(fields.get("length")),
        "creator": _plain(fields.get("creator")),
        "quote": quote_from_wikitext(wikitext),
        "image_file": wiki_file_name(fields.get("image")),
        "icon_file": wiki_file_name(fields.get("icon")),
        "killfeed_file": wiki_file_name(fields.get("killfeed")),
        "fire_rate": _first_float(fields.get("rate")),
        "magazine_size": as_int(fields.get("magazine")),
        "fire_stats": {
            "primary_fire": primary,
            "alternate_fire": alternate,
            "spread": _spread_rows(wikitext),
        },
    }


def _file_url(file_name: str | None, urls: dict[str, str]) -> str | None:
    """Match File: titles ignoring underscore vs space."""
    if not file_name:
        return None
    variants = [
        file_name,
        file_name.replace("_", " "),
        f"File:{file_name}",
        f"File:{file_name.replace('_', ' ')}",
    ]
    for key in variants:
        if key in urls:
            return urls[key]
        for stored, url in urls.items():
            if stored.lower() == key.lower():
                return url
    return None


def format_weapon_row(title: str, parsed: dict[str, Any], file_urls: dict[str, str]) -> dict[str, Any]:
    """One dim_weapons row: Fandom identity columns + fire_stats_json."""
    name = parsed.get("weapon_name") or title
    return {
        "weapon_name": name,
        "weapon_type": parsed.get("weapon_type"),
        "credits": parsed.get("credits"),
        "wall_penetration": parsed.get("wall_penetration"),
        "length": parsed.get("length"),
        "creator": parsed.get("creator"),
        "quote": parsed.get("quote"),
        "image_url": _file_url(parsed.get("image_file"), file_urls),
        "icon_url": _file_url(parsed.get("icon_file"), file_urls),
        "killfeed_icon_url": _file_url(parsed.get("killfeed_file"), file_urls),
        "fire_rate": parsed.get("fire_rate"),
        "magazine_size": parsed.get("magazine_size"),
        "fandom_url": FANDOM_WEAPON_URL.format(name=name.replace(" ", "_")),
        "rib_weapon_id": None,
        "fire_stats_json": parsed.get("fire_stats") or {},
    }


def _write_weapons_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Rewrite landing after extract so jsonl matches the warehouse."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = dict(row)
            for key in ("insert_date", "update_date"):
                stamp = payload.get(key)
                if hasattr(stamp, "isoformat"):
                    payload[key] = stamp.isoformat()
            if not isinstance(payload.get("fire_stats_json"), str):
                payload["fire_stats_json"] = json_dumps(payload.get("fire_stats_json"))
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def extract_weapons(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Fetch Fandom Weapons list + each gun page through AWS and land jsonl."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[weapons] Extract start source=valorant.fandom.com via AWS rotator")
    connector = ValorantFandomConnector()
    list_text = connector.get_page_wikitext(WEAPONS_LIST_PAGE)
    if not list_text:
        raise RuntimeError("Fandom Weapons list page returned empty wikitext")
    titles = weapon_titles_from_list(list_text)
    logger.info("[weapons] List titles=%s names=%s", len(titles), titles)
    pages = connector.get_pages_wikitext(titles)
    parsed_by_title: dict[str, dict[str, Any]] = {}
    files: list[str] = []
    missing = 0
    for title in titles:
        wikitext = pages.get(title)
        if not wikitext:
            missing += 1
            continue
        parsed = parse_fandom_weapon(wikitext)
        parsed_by_title[title] = parsed
        for key in ("image_file", "icon_file", "killfeed_file"):
            if parsed.get(key):
                files.append(parsed[key])
    file_urls = connector.get_file_urls(files)
    rows: list[dict[str, Any]] = []
    for title, parsed in parsed_by_title.items():
        row = format_weapon_row(title, parsed, file_urls)
        if row.get("weapon_name"):
            rows.append(row)
    rows = stamp_rows(rows)
    path = weapons_jsonl_path(root)
    _write_weapons_jsonl(path, rows)
    logger.info(
        "[weapons] Extract done weapons=%s fandom_miss=%s path=%s",
        len(rows),
        missing,
        path,
    )
    return rows


def load_weapons(rows: list[dict[str, Any]] | None = None, repo_root: Path | None = None) -> int:
    """Upsert Fandom gun catalog on weapon_name; keep row_number on re-run."""
    load_project_env(repo_root)
    logger.info("[weapons] Load start")
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
    for row in rows:
        if not isinstance(row.get("fire_stats_json"), str):
            row["fire_stats_json"] = json_dumps(row.get("fire_stats_json"))
    loaded = upsert_dim_rows(
        rows,
        table="dim_weapons",
        columns=WEAPON_COLS,
        conflict_column="weapon_name",
        jsonb_columns=JSON_COLS,
    )
    logger.info("[weapons] Load done upserted=%s", loaded)
    return loaded


def run_weapons(repo_root: Path | None = None) -> dict[str, int]:
    """Schema + Fandom extract + upsert. Re-run when Riot ships a new gun."""
    rows = extract_weapons(repo_root)
    loaded = load_weapons(rows, repo_root)
    return {"extracted": len(rows), "loaded": loaded}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_weapons())
