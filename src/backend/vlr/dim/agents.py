"""Load vlr.dim_agents kit catalog: valorant-api.com + Liquipedia ability costs."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from backend.api_connectors.liquipedia_connector import LiquipediaValorantConnector
from backend.api_connectors.valorant_api_connector import ValorantApiConnector
from backend.config.env import load_project_env
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import canonical_agent_name, json_dumps

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
LP_AGENT_URL = "https://liquipedia.net/valorant/{name}"

AGENT_COLS = (
    "agent_name",
    "role_name",
    "description",
    "real_name",
    "country_name",
    "release_date",
    "image_url",
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
    "image_url": "TEXT",
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


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.lower() in {"free", "none", "n/a", "-"}:
        return 0
    match = re.search(r"\d+", text.replace(",", ""))
    if not match:
        return None
    return int(match.group(0))


def _iter_templates(wikitext: str, name: str) -> list[str]:
    """Yield raw {{Name ...}} blocks, including nested {{ }} inside AbilityCard."""
    start_token = "{{" + name
    out: list[str] = []
    i = 0
    while True:
        i = wikitext.find(start_token, i)
        if i < 0:
            break
        depth = 0
        j = i
        while j < len(wikitext) - 1:
            if wikitext.startswith("{{", j):
                depth += 1
                j += 2
                continue
            if wikitext.startswith("}}", j):
                depth -= 1
                j += 2
                if depth == 0:
                    out.append(wikitext[i:j])
                    i = j
                    break
                continue
            j += 1
        else:
            break
    return out


def _template_fields(block: str) -> dict[str, str]:
    """Parse |key=value lines from a MediaWiki template body."""
    fields: dict[str, str] = {}
    body = block.strip()
    if body.startswith("{{"):
        body = body[2:]
    if body.endswith("}}"):
        body = body[:-2]
    for raw_line in body.splitlines()[1:]:
        line = raw_line.strip()
        if not line.startswith("|") or "=" not in line:
            continue
        key, value = line[1:].split("=", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


def parse_liquipedia_agent(wikitext: str) -> dict[str, Any]:
    """Infobox (real name, country, release) + AbilityCard costs/charges/hotkeys."""
    info: dict[str, Any] = {}
    boxes = _iter_templates(wikitext, "Infobox agent")
    if boxes:
        fields = _template_fields(boxes[0])
        info["real_name"] = _text(fields.get("realname") or fields.get("real_name"))
        info["country_name"] = _text(fields.get("country") or fields.get("nationality"))
        info["release_date"] = _text(fields.get("releasedate") or fields.get("release_date"))
        info["role_name"] = _text(fields.get("class"))
    cards: list[dict[str, Any]] = []
    for block in _iter_templates(wikitext, "AbilityCard"):
        fields = _template_fields(block)
        name = _text(fields.get("name"))
        if not name:
            continue
        kind = _text(fields.get("ability"))
        hotkey = (_text(fields.get("hotkey")) or "").upper() or None
        cards.append(
            {
                "name": name,
                "kind": kind,
                "hotkey": hotkey,
                "cost_credits": _as_int(fields.get("cost")),
                "ultimate_orbs": _as_int(fields.get("ultimatecost") or fields.get("ultimate_cost")),
                "charges": _as_int(fields.get("charges")),
                "description": _text(fields.get("description")),
            }
        )
    info["cards"] = cards
    return info


def _api_ability_index(agent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index valorant-api abilities by lowercase name for icon/description merge."""
    out: dict[str, dict[str, Any]] = {}
    for ability in agent.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        name = _text(ability.get("displayName"))
        if name:
            out[name.lower()] = ability
    return out


def _merge_abilities(agent: dict[str, Any], lp: dict[str, Any]) -> list[dict[str, Any]]:
    """Liquipedia costs + valorant-api icons/text; include Passive from the API only."""
    api_by_name = _api_ability_index(agent)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in lp.get("cards") or []:
        name = card["name"]
        api = api_by_name.get(name.lower()) or {}
        slot = API_SLOT_TO_HOTKEY.get(str(api.get("slot") or ""), card.get("hotkey"))
        row = {
            "hotkey": card.get("hotkey") or slot,
            "kind": card.get("kind") or ("Ultimate" if card.get("ultimate_orbs") else None),
            "name": name,
            "cost_credits": card.get("cost_credits"),
            "ultimate_orbs": card.get("ultimate_orbs"),
            "charges": card.get("charges"),
            "description": card.get("description") or _text(api.get("description")),
            "icon_url": _text(api.get("displayIcon")),
            "api_slot": _text(api.get("slot")),
        }
        merged.append(row)
        seen.add(name.lower())
    for ability in agent.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        name = _text(ability.get("displayName"))
        if not name or name.lower() in seen:
            continue
        merged.append(
            {
                "hotkey": API_SLOT_TO_HOTKEY.get(str(ability.get("slot") or ""), None),
                "kind": _text(ability.get("slot")),
                "name": name,
                "cost_credits": None,
                "ultimate_orbs": None,
                "charges": None,
                "description": _text(ability.get("description")),
                "icon_url": _text(ability.get("displayIcon")),
                "api_slot": _text(ability.get("slot")),
            }
        )
    return merged


def _hotkey_row(abilities: list[dict[str, Any]], hotkey: str) -> dict[str, Any] | None:
    for row in abilities:
        if str(row.get("hotkey") or "").upper() == hotkey:
            return row
    return None


def _release_date(api_agent: dict[str, Any], lp: dict[str, Any]) -> str | None:
    """Prefer Liquipedia; valorant-api uses 1970-01-01 for launch roster."""
    lp_date = _text(lp.get("release_date"))
    if lp_date:
        return lp_date[:10]
    raw = _text(api_agent.get("releaseDate"))
    if not raw or raw.startswith("1970-01-01"):
        return None
    return raw[:10]


def format_agent_row(api_agent: dict[str, Any], lp: dict[str, Any]) -> dict[str, Any] | None:
    """One dim_agents row: identity from valorant-api, costs from Liquipedia."""
    name = canonical_agent_name(api_agent.get("displayName"))
    if not name:
        return None
    role = api_agent.get("role") if isinstance(api_agent.get("role"), dict) else {}
    abilities = _merge_abilities(api_agent, lp)
    c_row = _hotkey_row(abilities, "C")
    q_row = _hotkey_row(abilities, "Q")
    e_row = _hotkey_row(abilities, "E")
    x_row = _hotkey_row(abilities, "X")
    tags = api_agent.get("characterTags")
    tags = tags if isinstance(tags, list) else []
    return {
        "agent_name": name,
        "role_name": _text(role.get("displayName")) or lp.get("role_name"),
        "description": _text(api_agent.get("description")),
        "real_name": lp.get("real_name"),
        "country_name": lp.get("country_name"),
        "release_date": _release_date(api_agent, lp),
        "image_url": _text(api_agent.get("displayIcon")),
        "portrait_url": _text(api_agent.get("fullPortrait") or api_agent.get("fullPortraitV2")),
        "role_icon_url": _text(role.get("displayIcon")),
        "valorant_api_uuid": _text(api_agent.get("uuid")),
        "liquipedia_url": LP_AGENT_URL.format(name=name.replace(" ", "_")),
        "ability_c_name": (c_row or {}).get("name"),
        "ability_c_cost": (c_row or {}).get("cost_credits"),
        "ability_q_name": (q_row or {}).get("name"),
        "ability_q_cost": (q_row or {}).get("cost_credits"),
        "ability_e_name": (e_row or {}).get("name"),
        "ability_e_cost": (e_row or {}).get("cost_credits"),
        "ultimate_name": (x_row or {}).get("name"),
        "ultimate_orbs": (x_row or {}).get("ultimate_orbs"),
        "abilities_json": abilities,
        "tags_json": tags,
    }


def extract_agents(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Fetch kit catalog (~30 agents) and land jsonl."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[agents] Extract start sources=valorant-api.com + liquipedia.net/valorant")
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
