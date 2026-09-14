"""Parse maps/agents/teams/players/country from existing VLR jsonl (no extra scrape)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.config.env import load_project_env
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import events_jsonl_path, matches_jsonl_path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]

# VLR scoreboard has no agent role; fill known names so the dim is usable now.
AGENT_ROLES: dict[str, str] = {
    "Jett": "Duelist",
    "Phoenix": "Duelist",
    "Reyna": "Duelist",
    "Raze": "Duelist",
    "Yoru": "Duelist",
    "Neon": "Duelist",
    "Iso": "Duelist",
    "Waylay": "Duelist",
    "Sova": "Initiator",
    "Breach": "Initiator",
    "Skye": "Initiator",
    "KAY/O": "Initiator",
    "KAYO": "Initiator",
    "Fade": "Initiator",
    "Gekko": "Initiator",
    "Tejo": "Initiator",
    "Brimstone": "Controller",
    "Omen": "Controller",
    "Viper": "Controller",
    "Astra": "Controller",
    "Harbor": "Controller",
    "Clove": "Controller",
    "Sage": "Sentinel",
    "Cypher": "Sentinel",
    "Killjoy": "Sentinel",
    "Chamber": "Sentinel",
    "Deadlock": "Sentinel",
    "Vyse": "Sentinel",
}

# VLR roster flags look like mod-us. Names are display labels, not ISO official names.
FLAG_TO_COUNTRY: dict[str, str] = {
    "us": "United States",
    "ca": "Canada",
    "mx": "Mexico",
    "br": "Brazil",
    "ar": "Argentina",
    "cl": "Chile",
    "co": "Colombia",
    "pe": "Peru",
    "gb": "United Kingdom",
    "uk": "United Kingdom",
    "fr": "France",
    "de": "Germany",
    "es": "Spain",
    "it": "Italy",
    "pt": "Portugal",
    "nl": "Netherlands",
    "be": "Belgium",
    "pl": "Poland",
    "tr": "Turkey",
    "ru": "Russia",
    "ua": "Ukraine",
    "se": "Sweden",
    "fi": "Finland",
    "no": "Norway",
    "dk": "Denmark",
    "cz": "Czechia",
    "hu": "Hungary",
    "ro": "Romania",
    "rs": "Serbia",
    "hr": "Croatia",
    "gr": "Greece",
    "lt": "Lithuania",
    "ee": "Estonia",
    "lv": "Latvia",
    "ie": "Ireland",
    "at": "Austria",
    "ch": "Switzerland",
    "cn": "China",
    "kr": "South Korea",
    "jp": "Japan",
    "tw": "Taiwan",
    "hk": "Hong Kong",
    "th": "Thailand",
    "vn": "Vietnam",
    "id": "Indonesia",
    "my": "Malaysia",
    "sg": "Singapore",
    "ph": "Philippines",
    "in": "India",
    "pk": "Pakistan",
    "bd": "Bangladesh",
    "au": "Australia",
    "nz": "New Zealand",
    "sa": "Saudi Arabia",
    "ae": "United Arab Emirates",
    "qa": "Qatar",
    "kw": "Kuwait",
    "eg": "Egypt",
    "ma": "Morocco",
    "za": "South Africa",
    "un": "Unknown",
}

MAP_COLS = ("map_name", "insert_date", "update_date")
MAP_TYPES = {
    "row_number": "BIGINT",
    "map_name": "TEXT",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}
AGENT_COLS = ("agent_name", "role_name", "insert_date", "update_date")
AGENT_TYPES = {
    "row_number": "BIGINT",
    "agent_name": "TEXT",
    "role_name": "TEXT",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}
COUNTRY_COLS = ("country_name", "country_flag", "region_code", "insert_date", "update_date")
COUNTRY_TYPES = {
    "row_number": "BIGINT",
    "country_name": "TEXT",
    "country_flag": "TEXT",
    "region_code": "TEXT",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}
TEAM_COLS = ("vlr_team_id", "team_name", "insert_date", "update_date")
TEAM_TYPES = {
    "row_number": "BIGINT",
    "vlr_team_id": "TEXT",
    "team_name": "TEXT",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}
PLAYER_COLS = (
    "vlr_player_id",
    "ign",
    "vlr_team_id",
    "country_flag",
    "country_name",
    "insert_date",
    "update_date",
)
PLAYER_TYPES = {
    "row_number": "BIGINT",
    "vlr_player_id": "TEXT",
    "ign": "TEXT",
    "vlr_team_id": "TEXT",
    "country_flag": "TEXT",
    "country_name": "TEXT",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}


def _root(repo_root: Path | None) -> Path:
    return repo_root or REPO_ROOT


def apply_landing_schema(repo_root: Path | None = None) -> None:
    """Create dims that are filled from jsonl so load does not fail on missing tables."""
    load_project_env(repo_root)
    root = _root(repo_root)
    apply_dim_schema(root, "vlr_dim_maps.sql", "dim_maps", MAP_TYPES)
    apply_dim_schema(root, "vlr_dim_agents.sql", "dim_agents", AGENT_TYPES)
    apply_dim_schema(root, "vlr_dim_country.sql", "dim_country", COUNTRY_TYPES)
    apply_dim_schema(root, "vlr_dim_teams.sql", "dim_teams", TEAM_TYPES)
    apply_dim_schema(root, "vlr_dim_players.sql", "dim_players", PLAYER_TYPES)


def _flag_code(raw: str | None) -> str | None:
    """Strip VLR `mod-us` so country lookup uses `us`."""
    if not raw:
        return None
    code = str(raw).strip().lower()
    if code.startswith("mod-"):
        code = code[4:]
    return code or None


def country_from_flag(raw: str | None) -> tuple[str | None, str | None]:
    """Return (flag_code, country_name) for dim_country / dim_players."""
    code = _flag_code(raw)
    if not code:
        return None, None
    return code, FLAG_TO_COUNTRY.get(code, code.upper())


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _iter_map_players(game: dict[str, Any]):
    """Walk team1/team2 or a flat player list on one map payload."""
    players = game.get("players")
    if isinstance(players, dict):
        for side in ("team1", "team2"):
            for player in players.get(side) or []:
                if isinstance(player, dict):
                    yield player
        return
    if isinstance(players, list):
        for player in players:
            if isinstance(player, dict):
                yield player


def collect_from_matches(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """One pass over matches.jsonl for maps, agents, and extra team ids. Serial: single file."""
    path = matches_jsonl_path(repo_root)
    maps: set[str] = set()
    agents: set[str] = set()
    teams: dict[str, str] = {}
    scanned = 0
    logger.info("[landings] Scan matches path=%s", path)
    if not path.exists():
        raise FileNotFoundError(f"matches.jsonl missing at {path}. Run vlr_matches first.")
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            obj = json_loads_obj(line)
            if not obj:
                continue
            for tid_key, name_key in (
                ("vlr_team_1_id", "team_1_name"),
                ("vlr_team_2_id", "team_2_name"),
            ):
                team_id = str(obj.get(tid_key) or "").strip()
                if team_id:
                    name = str(obj.get(name_key) or "").strip()
                    teams[team_id] = name or teams.get(team_id) or team_id
            detail = obj.get("detail") if isinstance(obj.get("detail"), dict) else {}
            games = detail.get("maps") if isinstance(detail.get("maps"), list) else []
            for game in games:
                if not isinstance(game, dict):
                    continue
                map_name = str(game.get("map_name") or game.get("name") or "").strip()
                if map_name and map_name.lower() not in {"tba", "tbd", "n/a"}:
                    maps.add(map_name)
                for player in _iter_map_players(game):
                    agent = str(player.get("agent") or "").strip()
                    if agent:
                        agents.add(agent)
            if scanned % 25000 == 0:
                logger.info(
                    "[landings] Match scan lines=%s maps=%s agents=%s teams=%s",
                    scanned,
                    len(maps),
                    len(agents),
                    len(teams),
                )
    logger.info(
        "[landings] Match scan done lines=%s maps=%s agents=%s teams=%s",
        scanned,
        len(maps),
        len(agents),
        len(teams),
    )
    map_rows = stamp_rows([{"map_name": name} for name in sorted(maps)])
    agent_rows = stamp_rows(
        [{"agent_name": name, "role_name": AGENT_ROLES.get(name)} for name in sorted(agents)]
    )
    return map_rows, agent_rows, teams


def collect_from_events(repo_root: Path, teams: dict[str, str]) -> tuple[list[dict[str, Any]], ...]:
    """Unique players/countries and extra team names from events.jsonl rosters."""
    events_path = events_jsonl_path(repo_root)
    players: dict[str, dict[str, Any]] = {}
    countries: dict[str, str] = {}
    logger.info("[landings] Scan events for teams/players path=%s", events_path)
    if not events_path.exists():
        raise FileNotFoundError(f"events.jsonl missing at {events_path}. Run vlr_events first.")
    scanned = 0
    with events_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            obj = json_loads_obj(line)
            if not obj:
                continue
            for team in _as_list(obj.get("teams_json")):
                if not isinstance(team, dict):
                    continue
                team_id = str(team.get("id") or "").strip()
                team_name = str(team.get("name") or "").strip()
                if team_id:
                    teams[team_id] = team_name or teams.get(team_id) or team_id
                for player in team.get("players") or []:
                    if not isinstance(player, dict):
                        continue
                    player_id = str(player.get("id") or "").strip()
                    if not player_id:
                        continue
                    flag, country_name = country_from_flag(player.get("flag"))
                    if flag and country_name:
                        countries[country_name] = flag
                    prev = players.get(player_id)
                    ign = str(player.get("name") or "").strip()
                    if prev is None:
                        players[player_id] = {
                            "vlr_player_id": player_id,
                            "ign": ign,
                            "vlr_team_id": team_id or None,
                            "country_flag": flag,
                            "country_name": country_name,
                        }
                    else:
                        if ign:
                            prev["ign"] = ign
                        if team_id:
                            prev["vlr_team_id"] = team_id
                        if flag:
                            prev["country_flag"] = flag
                            prev["country_name"] = country_name
            if scanned % 500 == 0:
                logger.info(
                    "[landings] Events progress events=%s teams=%s players=%s",
                    scanned,
                    len(teams),
                    len(players),
                )
    logger.info("[landings] Events done events=%s teams=%s players=%s", scanned, len(teams), len(players))
    team_rows = stamp_rows(
        [{"vlr_team_id": tid, "team_name": name} for tid, name in sorted(teams.items())]
    )
    player_rows = stamp_rows(list(players.values()))
    country_rows = stamp_rows(
        [{"country_name": name, "country_flag": flag, "region_code": None} for name, flag in sorted(countries.items())]
    )
    return team_rows, player_rows, country_rows


def load_from_landings(repo_root: Path | None = None) -> dict[str, int]:
    """Upsert maps/agents/country/teams/players parsed from jsonl."""
    load_project_env(repo_root)
    root = _root(repo_root)
    apply_landing_schema(root)
    map_rows, agent_rows, teams = collect_from_matches(root)
    team_rows, player_rows, country_rows = collect_from_events(root, teams)
    counts = {
        "dim_maps": upsert_dim_rows(map_rows, table="dim_maps", columns=MAP_COLS, conflict_column="map_name"),
        "dim_agents": upsert_dim_rows(
            agent_rows, table="dim_agents", columns=AGENT_COLS, conflict_column="agent_name"
        ),
        "dim_country": upsert_dim_rows(
            country_rows, table="dim_country", columns=COUNTRY_COLS, conflict_column="country_name"
        ),
        "dim_teams": upsert_dim_rows(team_rows, table="dim_teams", columns=TEAM_COLS, conflict_column="vlr_team_id"),
        "dim_players": upsert_dim_rows(
            player_rows, table="dim_players", columns=PLAYER_COLS, conflict_column="vlr_player_id"
        ),
    }
    logger.info("[landings] Done counts=%s", counts)
    return counts
