"""Load vlr.dim_agents kit catalog: valorant-api.com + Liquipedia AbilityCard (AWS rotator)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.api_connectors.liquipedia_connector import LiquipediaValorantConnector
from backend.api_connectors.valorant_api_connector import ValorantApiConnector
from backend.config.env import load_project_env
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import canonical_agent_name, json_dumps
from backend.vlr.dim.wikitext import as_int, extra_stat_lines, iter_templates, strip_wiki, template_fields, text_or_none

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
LP_AGENT_URL = "https://liquipedia.net/valorant/{name}"

# Standard Valorant binds when Liquipedia only stores the PC hotkey.
CONSOLE_BINDS = {
    "C": {"ps": "L1", "xbox": "LB"},
    "Q": {"ps": "R1", "xbox": "RB"},
    "E": {"ps": "Circle", "xbox": "B"},
    "X": {"ps": "L1+R1", "xbox": "LB+RB"},
}

AGENT_COLS = (
    "agent_name",
    "role_name",
    "description",
    "real_name",
    "country_name",
    "release_date",
    "face_url",
    "image_url",
    "bust_url",
    "killfeed_portrait_url",
    "portrait_url",
    "role_icon_url",
    "valorant_api_uuid",
    "liquipedia_url",
    "ability_c_name",
    "ability_c_cost",
    "ability_q_name",
    "ability_q_cost",
    "ability_e_name",
    "ability_e_cost",
    "ultimate_name",
    "ultimate_orbs",
    "abilities_json",
    "tags_json",
    "insert_date",
    "update_date",
)
JSON_COLS = ("abilities_json", "tags_json")
AGENT_TYPES = {
    "row_number": "BIGINT",
    "agent_name": "TEXT",
    "role_name": "TEXT",
    "description": "TEXT",
    "real_name": "TEXT",
    "country_name": "TEXT",
    "release_date": "TEXT",
    "face_url": "TEXT",
    "image_url": "TEXT",
    "bust_url": "TEXT",
    "killfeed_portrait_url": "TEXT",
    "portrait_url": "TEXT",
    "role_icon_url": "TEXT",
    "valorant_api_uuid": "TEXT",
    "liquipedia_url": "TEXT",
    "ability_c_name": "TEXT",
    "ability_c_cost": "INTEGER",
    "ability_q_name": "TEXT",
    "ability_q_cost": "INTEGER",
    "ability_e_name": "TEXT",
    "ability_e_cost": "INTEGER",
    "ultimate_name": "TEXT",
    "ultimate_orbs": "INTEGER",
    "abilities_json": "JSONB",
    "tags_json": "JSONB",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}

API_SLOT_TO_HOTKEY = {
    "Grenade": "C",
    "Ability1": "Q",
    "Ability2": "E",
    "Ultimate": "X",
    "Passive": "Passive",
}

_SKIP_STAT_KEYS = {
    "name",
    "image",
    "hotkey",
    "hotkeyps",
    "hotkeyps5",
    "hotkeyxbox",
    "hotkey_ps",
    "hotkey_xbox",
    "ability",
    "cost",
    "ultimatecost",
    "ultimate_cost",
    "charges",
    "uses",
    "description",
    "_extra_lines",
}


def _root(repo_root: Path | None) -> Path:
    """Resolve repo root so CLI and Dagster share one landing path."""
    return Path(repo_root or REPO_ROOT)


def agents_jsonl_path(repo_root: Path) -> Path:
    """Landing so a failed upsert can retry without hitting Liquipedia again."""
    return repo_root / "data" / "vlr" / "dim_agents.jsonl"


def apply_agents_schema(repo_root: Path | None = None) -> Path:
    """Create dim_agents if missing; ADD kit columns (no DROP)."""
    load_project_env(repo_root)
    return apply_dim_schema(_root(repo_root), "vlr_dim_agents.sql", "dim_agents", AGENT_TYPES)


def _console_binds(hotkey: str | None, fields: dict[str, str]) -> tuple[str | None, str | None]:
    """PC hotkey plus PS5 / Xbox from Liquipedia, else the standard Valorant mapping."""
    ps = strip_wiki(fields.get("hotkeyps") or fields.get("hotkeyps5") or fields.get("hotkey_ps"))
    xbox = strip_wiki(fields.get("hotkeyxbox") or fields.get("hotkey_xbox"))
    defaults = CONSOLE_BINDS.get((hotkey or "").upper(), {})
    return ps or defaults.get("ps"), xbox or defaults.get("xbox")


def parse_liquipedia_agent(wikitext: str) -> dict[str, Any]:
    """Infobox identity + full AbilityCard (costs, uses, windup, duration, cooldown, binds)."""
    info: dict[str, Any] = {}
    boxes = iter_templates(wikitext, "Infobox agent")
    if boxes:
        fields = template_fields(boxes[0])
        info["real_name"] = strip_wiki(fields.get("realname") or fields.get("real_name"))
        info["country_name"] = strip_wiki(fields.get("country") or fields.get("nationality"))
        info["release_date"] = text_or_none(fields.get("releasedate") or fields.get("release_date"))
        info["role_name"] = strip_wiki(fields.get("class"))
    cards: list[dict[str, Any]] = []
    for block in iter_templates(wikitext, "AbilityCard"):
        fields = template_fields(block)
        name = text_or_none(fields.get("name"))
        if not name:
            continue
        kind = text_or_none(fields.get("ability"))
        hotkey = (text_or_none(fields.get("hotkey")) or "").upper() or None
        extra = extra_stat_lines(fields.get("_extra_lines"))
        stats: dict[str, str] = dict(extra)
        for key, value in fields.items():
            if key in _SKIP_STAT_KEYS or not value:
                continue
            cleaned = strip_wiki(value)
            if cleaned:
                stats[key] = cleaned
        ps_bind, xbox_bind = _console_binds(hotkey, fields)
        cards.append(
            {
                "name": name,
                "kind": kind,
                "hotkey": hotkey,
                "hotkey_pc": hotkey,
                "hotkey_ps": ps_bind,
                "hotkey_xbox": xbox_bind,
                "cost_credits": as_int(fields.get("cost")),
                "ultimate_orbs": as_int(fields.get("ultimatecost") or fields.get("ultimate_cost")),
                "uses": as_int(fields.get("uses") or fields.get("charges") or extra.get("uses")),
                "charges": as_int(fields.get("charges") or extra.get("uses")),
                "windup": strip_wiki(fields.get("windup") or extra.get("windup")),
                "duration": strip_wiki(fields.get("duration") or extra.get("duration")),
                "cooldown": strip_wiki(fields.get("cooldown") or extra.get("cooldown")),
                "debuff": strip_wiki(fields.get("debuff") or extra.get("debuff")),
                "regain": strip_wiki(fields.get("regain")),
                "affects": strip_wiki(fields.get("affects")),
                "description": strip_wiki(fields.get("description")),
                "lp_image": text_or_none(fields.get("image")),
                "stats": stats,
            }
        )
    info["cards"] = cards
    return info


def _name_key(name: str | None) -> str:
    """Compare ability names so 'Nebula / Dissipate' still matches Liquipedia 'Nebula'."""
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _lp_card_for(name: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Match Liquipedia stats by live ability name, never by stale hotkey."""
    key = _name_key(name)
    if not key:
        return {}
    for card in cards:
        other = _name_key(card.get("name"))
        if other == key:
            return card
        if min(len(key), len(other)) >= 5 and (key.startswith(other) or other.startswith(key)):
            return card
    return {}


def _apply_live_slots(abilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hotkeys follow valorant-api slots (current kit). E/signature is never bought."""
    for row in abilities:
        slot = text_or_none(row.get("api_slot"))
        live = API_SLOT_TO_HOTKEY.get(slot or "")
        if live:
            row["hotkey"] = live
            row["hotkey_pc"] = live
            defaults = CONSOLE_BINDS.get(live, {})
            row["hotkey_ps"] = row.get("hotkey_ps") or defaults.get("ps")
            row["hotkey_xbox"] = row.get("hotkey_xbox") or defaults.get("xbox")
        if live == "E" or slot == "Ability2":
            row["cost_credits"] = 0
            row["kind"] = "Signature"
        elif live == "X" or slot == "Ultimate":
            row["kind"] = "Ultimate"
        elif live in {"C", "Q"}:
            kind = text_or_none(row.get("kind"))
            if not kind or kind.lower() in {"ability1", "ability2", "grenade", "signature"}:
                row["kind"] = "Basic"
        elif slot == "Passive":
            row["kind"] = "Passive"
            row["hotkey"] = row.get("hotkey") or "Passive"
    return abilities


def _merge_abilities(agent: dict[str, Any], lp: dict[str, Any]) -> list[dict[str, Any]]:
    """Live binds from valorant-api slots; Liquipedia fills cost/stats by ability name."""
    cards = [c for c in (lp.get("cards") or []) if isinstance(c, dict) and c.get("name")]
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ability in agent.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        name = text_or_none(ability.get("displayName"))
        if not name:
            continue
        slot = text_or_none(ability.get("slot"))
        hotkey = API_SLOT_TO_HOTKEY.get(slot or "", None)
        card = _lp_card_for(name, cards)
        defaults = CONSOLE_BINDS.get(str(hotkey or "").upper(), {})
        merged.append(
            {
                "hotkey": hotkey or card.get("hotkey"),
                "hotkey_pc": hotkey or card.get("hotkey"),
                "hotkey_ps": card.get("hotkey_ps") or defaults.get("ps"),
                "hotkey_xbox": card.get("hotkey_xbox") or defaults.get("xbox"),
                "kind": card.get("kind"),
                "name": name,
                "cost_credits": card.get("cost_credits"),
                "ultimate_orbs": card.get("ultimate_orbs"),
                "uses": card.get("uses"),
                "charges": card.get("charges"),
                "windup": card.get("windup"),
                "duration": card.get("duration"),
                "cooldown": card.get("cooldown"),
                "debuff": card.get("debuff"),
                "regain": card.get("regain"),
                "affects": card.get("affects"),
                "description": text_or_none(ability.get("description")) or card.get("description"),
                "icon_url": text_or_none(ability.get("displayIcon")),
                "lp_image": card.get("lp_image"),
                "api_slot": slot,
                "stats": card.get("stats") or {},
            }
        )
        seen.add(_name_key(name))
        if card.get("name"):
            seen.add(_name_key(card.get("name")))
    for card in cards:
        if _name_key(card.get("name")) in seen:
            continue
        hotkey = card.get("hotkey")
        defaults = CONSOLE_BINDS.get(str(hotkey or "").upper(), {})
        merged.append(
            {
                "hotkey": hotkey,
                "hotkey_pc": hotkey,
                "hotkey_ps": card.get("hotkey_ps") or defaults.get("ps"),
                "hotkey_xbox": card.get("hotkey_xbox") or defaults.get("xbox"),
                "kind": card.get("kind"),
                "name": card["name"],
                "cost_credits": card.get("cost_credits"),
                "ultimate_orbs": card.get("ultimate_orbs"),
                "uses": card.get("uses"),
                "charges": card.get("charges"),
                "windup": card.get("windup"),
                "duration": card.get("duration"),
                "cooldown": card.get("cooldown"),
                "debuff": card.get("debuff"),
                "regain": card.get("regain"),
                "affects": card.get("affects"),
                "description": card.get("description"),
                "icon_url": None,
                "lp_image": card.get("lp_image"),
                "api_slot": None,
                "stats": card.get("stats") or {},
            }
        )
    return _drop_stale_lp_dupes(_apply_live_slots(merged))


def _hotkey_row(
    abilities: list[dict[str, Any]], hotkey: str, kind: str | None = None
) -> dict[str, Any] | None:
    """Pick C/Q/E/X from merged kit; Ultimate wins when X is also a signature (Astra)."""
    fallback = None
    for row in abilities:
        if str(row.get("hotkey") or "").upper() != hotkey:
            continue
        row_kind = str(row.get("kind") or "")
        if kind and row_kind.lower() == kind.lower():
            return row
        if fallback is None:
            fallback = row
    return fallback


def _drop_stale_lp_dupes(abilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop leftover Liquipedia cards already covered by a live valorant-api slot."""
    slotted = [_name_key(row.get("name")) for row in abilities if row.get("api_slot")]
    kept: list[dict[str, Any]] = []
    for row in abilities:
        if row.get("api_slot"):
            kept.append(row)
            continue
        key = _name_key(row.get("name"))
        if not key:
            continue
        if any(
            key == other or (min(len(key), len(other)) >= 5 and (key.startswith(other) or other.startswith(key)))
            for other in slotted
        ):
            continue
        kept.append(row)
    return kept


def _slot_row(abilities: list[dict[str, Any]], slot: str, hotkey: str) -> dict[str, Any] | None:
    """Prefer the live valorant-api slot so Harbor Q/E follow the current kit."""
    for row in abilities:
        if text_or_none(row.get("api_slot")) == slot:
            return row
    kind = "Ultimate" if slot == "Ultimate" else ("Signature" if slot == "Ability2" else None)
    return _hotkey_row(abilities, hotkey, kind=kind)


def flatten_kit_columns(abilities: list[dict[str, Any]]) -> dict[str, Any]:
    """C/Q buy costs, E always 0 (signature), X ult orbs — from live slots."""
    abilities = _drop_stale_lp_dupes(_apply_live_slots(abilities))
    c_row = _slot_row(abilities, "Grenade", "C")
    q_row = _slot_row(abilities, "Ability1", "Q")
    e_row = _slot_row(abilities, "Ability2", "E")
    x_row = _slot_row(abilities, "Ultimate", "X")
    return {
        "ability_c_name": (c_row or {}).get("name"),
        "ability_c_cost": (c_row or {}).get("cost_credits"),
        "ability_q_name": (q_row or {}).get("name"),
        "ability_q_cost": (q_row or {}).get("cost_credits"),
        "ability_e_name": (e_row or {}).get("name"),
        "ability_e_cost": 0 if e_row else None,
        "ultimate_name": (x_row or {}).get("name"),
        "ultimate_orbs": (x_row or {}).get("ultimate_orbs"),
        "abilities_json": abilities,
    }


def _release_date(api_agent: dict[str, Any], lp: dict[str, Any]) -> str | None:
    """Prefer Liquipedia; valorant-api uses 1970-01-01 for launch roster."""
    lp_date = text_or_none(lp.get("release_date"))
    if lp_date:
        return lp_date[:10]
    raw = text_or_none(api_agent.get("releaseDate"))
    if not raw or raw.startswith("1970-01-01"):
        return None
    return raw[:10]


def format_agent_row(api_agent: dict[str, Any], lp: dict[str, Any]) -> dict[str, Any] | None:
    """One dim_agents row: identity/face from valorant-api, AbilityCard stats from Liquipedia."""
    name = canonical_agent_name(api_agent.get("displayName"))
    if not name:
        return None
    role = api_agent.get("role") if isinstance(api_agent.get("role"), dict) else {}
    abilities = _merge_abilities(api_agent, lp)
    kit = flatten_kit_columns(abilities)
    tags = api_agent.get("characterTags")
    tags = tags if isinstance(tags, list) else []
    face = text_or_none(api_agent.get("displayIcon"))
    return {
        "agent_name": name,
        "role_name": text_or_none(role.get("displayName")) or lp.get("role_name"),
        "description": text_or_none(api_agent.get("description")),
        "real_name": lp.get("real_name"),
        "country_name": lp.get("country_name"),
        "release_date": _release_date(api_agent, lp),
        "face_url": face,
        "image_url": face,
        "bust_url": text_or_none(api_agent.get("bustPortrait")),
        "killfeed_portrait_url": text_or_none(api_agent.get("killfeedPortrait")),
        "portrait_url": text_or_none(api_agent.get("fullPortrait") or api_agent.get("fullPortraitV2")),
        "role_icon_url": text_or_none(role.get("displayIcon")),
        "valorant_api_uuid": text_or_none(api_agent.get("uuid")),
        "liquipedia_url": LP_AGENT_URL.format(name=name.replace(" ", "_")),
        **{k: kit[k] for k in kit if k != "abilities_json"},
        "abilities_json": kit["abilities_json"],
        "tags_json": tags,
    }


def extract_agents(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Fetch kit catalog (~30 agents) through AWS rotator and land jsonl."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[agents] Extract start sources=valorant-api.com + liquipedia.net via AWS rotator")
    api_agents = ValorantApiConnector().get_playable_agents()
    titles = [canonical_agent_name(a.get("displayName")) for a in api_agents]
    titles = [t for t in titles if t]
    lp_pages = LiquipediaValorantConnector().get_pages_wikitext(titles)
    rows: list[dict[str, Any]] = []
    missing_lp = 0
    for api_agent in api_agents:
        name = canonical_agent_name(api_agent.get("displayName"))
        wikitext = lp_pages.get(name or "") if name else None
        if not wikitext:
            missing_lp += 1
            lp: dict[str, Any] = {"cards": []}
        else:
            lp = parse_liquipedia_agent(wikitext)
        row = format_agent_row(api_agent, lp)
        if row:
            rows.append(row)
    rows = stamp_rows(rows)
    path = agents_jsonl_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = dict(row)
            for key in ("insert_date", "update_date"):
                stamp = payload.get(key)
                if hasattr(stamp, "isoformat"):
                    payload[key] = stamp.isoformat()
            payload["abilities_json"] = json_dumps(payload.get("abilities_json"))
            payload["tags_json"] = json_dumps(payload.get("tags_json"))
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    logger.info(
        "[agents] Extract done agents=%s liquipedia_miss=%s path=%s",
        len(rows),
        missing_lp,
        path,
    )
    return rows


def load_agents(rows: list[dict[str, Any]] | None = None, repo_root: Path | None = None) -> int:
    """Upsert kit catalog on agent_name; keep row_number on re-run."""
    load_project_env(repo_root)
    apply_agents_schema(repo_root)
    if rows is None:
        path = agents_jsonl_path(_root(repo_root))
        if not path.exists():
            raise FileNotFoundError(f"dim_agents jsonl missing at {path}. Run extract_agents first.")
        rows = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
        stamp_rows(rows)
    for row in rows:
        abilities = row.get("abilities_json")
        if isinstance(abilities, str):
            try:
                abilities = json.loads(abilities)
            except json.JSONDecodeError:
                abilities = []
        if isinstance(abilities, list):
            kit = flatten_kit_columns(abilities)
            row.update(kit)
        if not isinstance(row.get("abilities_json"), str):
            row["abilities_json"] = json_dumps(row.get("abilities_json"))
        if not isinstance(row.get("tags_json"), str):
            row["tags_json"] = json_dumps(row.get("tags_json"))
    loaded = upsert_dim_rows(
        rows,
        table="dim_agents",
        columns=AGENT_COLS,
        conflict_column="agent_name",
        jsonb_columns=JSON_COLS,
    )
    logger.info("[agents] Load done upserted=%s", loaded)
    return loaded


def run_agents(repo_root: Path | None = None) -> dict[str, int]:
    """Schema + catalog extract + upsert. Re-run when Riot ships a new agent."""
    rows = extract_agents(repo_root)
    loaded = load_agents(rows, repo_root)
    return {"extracted": len(rows), "loaded": loaded}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_agents())
