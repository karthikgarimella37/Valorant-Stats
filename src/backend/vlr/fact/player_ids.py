"""Resolve scoreboard IGN + team to vlr_player_id from landings (match JSON has no player id)."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from backend.vlr.dim.util import events_jsonl_path, players_jsonl_path, teams_jsonl_path

logger = logging.getLogger(__name__)


def _s(value: Any) -> str | None:
    """Blank strings are not join keys."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ign_key(value: Any) -> str | None:
    """Case-fold IGN so 'Ethan' and 'ethan' hit the same player."""
    text = _s(value)
    return text.lower() if text else None


def _as_list(raw: Any) -> list[Any]:
    """teams_json / roster may already be a list or a JSON string."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _index_pair(
    by_team_ign: dict[tuple[str, str], str],
    ign_ids: dict[str, set[str]],
    team_id: str | None,
    ign: str | None,
    player_id: str | None,
) -> None:
    """Later sources overwrite (team, ign); ign-only is used only when unique."""
    if not player_id or not ign:
        return
    ign_ids.setdefault(ign, set()).add(player_id)
    if team_id:
        by_team_ign[(team_id, ign)] = player_id


def _from_teams(repo_root: Path) -> tuple[dict[tuple[str, str], str], dict[str, set[str]]]:
    """Current org roster: (vlr_team_id, alias) → vlr_player_id."""
    by_team_ign: dict[tuple[str, str], str] = {}
    ign_ids: dict[str, set[str]] = {}
    path = teams_jsonl_path(repo_root)
    if not path.exists():
        logger.warning("[facts] Player-id lookup skip missing teams.jsonl")
        return by_team_ign, ign_ids
    scanned = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            team_id = _s(obj.get("vlr_team_id") or obj.get("id"))
            roster = _as_list(obj.get("current_roster_json")) or _as_list(obj.get("roster"))
            for person in roster:
                if not isinstance(person, dict):
                    continue
                role = str(person.get("role") or "").lower()
                if person.get("is_staff") or "coach" in role:
                    continue
                player_id = _s(person.get("vlr_player_id") or person.get("id"))
                ign = _ign_key(person.get("ign") or person.get("alias") or person.get("name"))
                _index_pair(by_team_ign, ign_ids, team_id, ign, player_id)
            if scanned % 5000 == 0:
                logger.info("[facts] Player-id lookup teams progress lines=%s", scanned)
    logger.info("[facts] Player-id lookup teams done lines=%s pairs=%s", scanned, len(by_team_ign))
    return by_team_ign, ign_ids


def _from_players(repo_root: Path) -> tuple[dict[tuple[str, str], str], dict[str, set[str]]]:
    """Player profiles + past stints so historical match teams still resolve."""
    by_team_ign: dict[tuple[str, str], str] = {}
    ign_ids: dict[str, set[str]] = {}
    path = players_jsonl_path(repo_root)
    if not path.exists():
        logger.warning("[facts] Player-id lookup skip missing players.jsonl")
        return by_team_ign, ign_ids
    scanned = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            player_id = _s(obj.get("vlr_player_id") or obj.get("id"))
            ign = _ign_key(obj.get("ign") or obj.get("name"))
            if not player_id or not ign:
                continue
            ign_ids.setdefault(ign, set()).add(player_id)
            current_team = _s(obj.get("vlr_team_id"))
            if current_team:
                by_team_ign[(current_team, ign)] = player_id
            for stint in _as_list(obj.get("teams_json")):
                if not isinstance(stint, dict):
                    continue
                team_id = _s(stint.get("vlr_team_id") or stint.get("id"))
                _index_pair(by_team_ign, ign_ids, team_id, ign, player_id)
            if scanned % 5000 == 0:
                logger.info("[facts] Player-id lookup players progress lines=%s", scanned)
    logger.info("[facts] Player-id lookup players done lines=%s pairs=%s", scanned, len(by_team_ign))
    return by_team_ign, ign_ids


def _from_events(repo_root: Path) -> tuple[dict[tuple[str, str], str], dict[str, set[str]]]:
    """Event-page rosters are dated to the tournament, so they win on (team, ign)."""
    by_team_ign: dict[tuple[str, str], str] = {}
    ign_ids: dict[str, set[str]] = {}
    path = events_jsonl_path(repo_root)
    if not path.exists():
        logger.warning("[facts] Player-id lookup skip missing events.jsonl")
        return by_team_ign, ign_ids
    scanned = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            for team in _as_list(obj.get("teams_json")):
                if not isinstance(team, dict):
                    continue
                team_id = _s(team.get("id") or team.get("vlr_team_id"))
                for player in team.get("players") or []:
                    if not isinstance(player, dict):
                        continue
                    player_id = _s(player.get("id") or player.get("vlr_player_id"))
                    ign = _ign_key(player.get("name") or player.get("ign") or player.get("alias"))
                    _index_pair(by_team_ign, ign_ids, team_id, ign, player_id)
            if scanned % 500 == 0:
                logger.info("[facts] Player-id lookup events progress lines=%s", scanned)
    logger.info("[facts] Player-id lookup events done lines=%s pairs=%s", scanned, len(by_team_ign))
    return by_team_ign, ign_ids


class PlayerIdLookup:
    """Join scoreboard name + team id to dim_players without extra HTTP."""

    def __init__(
        self,
        by_team_ign: dict[tuple[str, str], str],
        ign_ids: dict[str, set[str]],
    ) -> None:
        self.by_team_ign = by_team_ign
        unique_ign = {ign: next(iter(ids)) for ign, ids in ign_ids.items() if len(ids) == 1}
        self.by_ign = unique_ign
        self.unresolved = 0

    def resolve(self, team_id: str | None, ign: str | None, raw_id: Any = None) -> str | None:
        """Prefer payload id, then (team, ign), then globally unique ign."""
        payload_id = _s(raw_id)
        if payload_id:
            return payload_id
        ign_key = _ign_key(ign)
        if not ign_key:
            self.unresolved += 1
            return None
        team_key = _s(team_id)
        if team_key:
            hit = self.by_team_ign.get((team_key, ign_key))
            if hit:
                return hit
        hit = self.by_ign.get(ign_key)
        if hit:
            return hit
        self.unresolved += 1
        return None


def load_player_id_lookup_from_warehouse() -> PlayerIdLookup:
    """Use dim_players + dim_teams already in Supabase so incremental facts skip 3GB jsonl."""
    from backend.database_connectors.supabase_connectors import SupabaseConnector

    logger.info("[facts] Player-id lookup from warehouse dim_players + dim_teams")
    connector = SupabaseConnector()
    by_team_ign: dict[tuple[str, str], str] = {}
    ign_ids: dict[str, set[str]] = {}
    players = connector.fetch_all(
        "SELECT vlr_player_id, ign, vlr_team_id, teams_json FROM vlr.dim_players"
    )
    for player_id_raw, ign_raw, team_id_raw, teams_json in players:
        player_id = _s(player_id_raw)
        ign = _ign_key(ign_raw)
        if not player_id or not ign:
            continue
        _index_pair(by_team_ign, ign_ids, _s(team_id_raw), ign, player_id)
        for stint in _as_list(teams_json):
            if isinstance(stint, dict):
                _index_pair(
                    by_team_ign,
                    ign_ids,
                    _s(stint.get("vlr_team_id") or stint.get("id")),
                    ign,
                    player_id,
                )
    logger.info("[facts] Player-id lookup warehouse players rows=%s pairs=%s", len(players), len(by_team_ign))
    teams = connector.fetch_all("SELECT vlr_team_id, current_roster_json FROM vlr.dim_teams")
    for team_id_raw, roster_json in teams:
        team_id = _s(team_id_raw)
        for person in _as_list(roster_json):
            if not isinstance(person, dict):
                continue
            role = str(person.get("role") or "").lower()
            if person.get("is_staff") or "coach" in role:
                continue
            _index_pair(
                by_team_ign,
                ign_ids,
                team_id,
                _ign_key(person.get("ign") or person.get("alias") or person.get("name")),
                _s(person.get("vlr_player_id") or person.get("id")),
            )
    lookup = PlayerIdLookup(by_team_ign, ign_ids)
    logger.info(
        "[facts] Player-id lookup warehouse done team_ign=%s unique_ign=%s",
        len(lookup.by_team_ign),
        len(lookup.by_ign),
    )
    return lookup


def load_player_id_lookup(repo_root: Path) -> PlayerIdLookup:
    """Read teams/players/events jsonl in parallel; events overwrite (team, ign)."""
    logger.info("[facts] Player-id lookup start")
    # Three independent files — parallel I/O, then merge in overwrite order.
    with ThreadPoolExecutor(max_workers=3) as pool:
        teams_f = pool.submit(_from_teams, repo_root)
        players_f = pool.submit(_from_players, repo_root)
        events_f = pool.submit(_from_events, repo_root)
        chunks = (players_f.result(), teams_f.result(), events_f.result())
    by_team_ign: dict[tuple[str, str], str] = {}
    ign_ids: dict[str, set[str]] = {}
    for team_map, ign_map in chunks:
        by_team_ign.update(team_map)
        for ign, ids in ign_map.items():
            ign_ids.setdefault(ign, set()).update(ids)
    lookup = PlayerIdLookup(by_team_ign, ign_ids)
    logger.info(
        "[facts] Player-id lookup done team_ign=%s unique_ign=%s",
        len(lookup.by_team_ign),
        len(lookup.by_ign),
    )
    return lookup
