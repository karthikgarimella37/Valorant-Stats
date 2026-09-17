"""Parse landed rib match + replay JSON into overlay fact rows. Keep leftovers in leftover_json."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.rib_gg.join import (
    resolve_rib_team_id,
    resolve_vlr_player,
    resolve_vlr_team_id,
)
from backend.rib_gg.paths import match_json_path, replay_json_path
from backend.vlr.dim.util import json_dumps
from backend.vlr.fact.util import coalesce_id, to_float, to_int

logger = logging.getLogger(__name__)

ROUND_STAT_KEYS = {
    "playerId",
    "name",
    "team",
    "side",
    "agent",
    "kills",
    "deaths",
    "assists",
    "damage",
    "acs",
    "hsPct",
    "alive",
    "firstKill",
}
ROUND_KEYS = {"winner", "winType", "mvpAgent", "attackerTeam"}
SKIP_REPLAY_TYPES = {"snapshot", "damage"}


def _s(value: Any) -> str | None:
    """Blank strings are not keys."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _leftover(obj: dict[str, Any], known: set[str]) -> str | None:
    """Unknown fields stay JSON so we never throw away a column we have not mapped yet."""
    extra = {key: value for key, value in obj.items() if key not in known}
    if not extra:
        return None
    return json_dumps(extra)


def _armor_name(hp: int | None) -> str | None:
    """rib armor 25/50 → Light/Heavy like the round UI."""
    if hp is None:
        return None
    if hp >= 50:
        return "Heavy Armor"
    if hp >= 25:
        return "Light Armor"
    return None


def _map_game_number(map_id: Any, index: int) -> int:
    """270-m2 → 2."""
    text = str(map_id or "")
    if "-m" in text:
        suffix = text.rsplit("-m", 1)[-1]
        if suffix.isdigit():
            return int(suffix)
    return index


def _other_side(side: str | None) -> str | None:
    """Losing team letter."""
    token = (side or "").strip().upper()
    if token == "A":
        return "B"
    if token == "B":
        return "A"
    return None


def _player_states(round_obj: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Replay round keys besides events/freezetime are actorId → loadout timeline."""
    states: dict[str, list[dict[str, Any]]] = {}
    nested = round_obj.get("players") or round_obj.get("playerStates")
    if isinstance(nested, dict):
        source = nested.items()
    else:
        source = round_obj.items()
    for key, value in source:
        if key in {"events", "freezetimeEndT", "players", "playerStates"}:
            continue
        if not isinstance(value, list) or not value:
            continue
        first = value[0]
        if isinstance(first, dict) and ("loadoutValue" in first or "armor" in first or "money" in first):
            states[str(key)] = [row for row in value if isinstance(row, dict)]
    return states


def _freeze_loadout(states: list[dict[str, Any]], freeze_t: float | None) -> dict[str, Any]:
    """Buy-complete state: first tick at/after freeze, else last before freeze."""
    if not states:
        return {}
    freeze = freeze_t if freeze_t is not None else 0.0
    after = [row for row in states if to_float(row.get("t")) is not None and float(row["t"]) >= freeze]
    if after:
        return after[0]
    before = [row for row in states if to_float(row.get("t")) is not None and float(row["t"]) < freeze]
    if before:
        return before[-1]
    return states[0]


def _roster_by_name(replay: dict[str, Any]) -> dict[str, str]:
    """IGN lower → replay actor id."""
    roster = replay.get("roster") if isinstance(replay.get("roster"), dict) else {}
    out: dict[str, str] = {}
    for actor_id, row in roster.items():
        if not isinstance(row, dict):
            continue
        name = _s(row.get("name"))
        if name:
            out[name.lower()] = str(actor_id)
    return out


def _pos_xy(pos: Any) -> tuple[float | None, float | None]:
    """Replay pos object → x,y."""
    if not isinstance(pos, dict):
        return None, None
    return to_float(pos.get("x")), to_float(pos.get("y"))


def parse_match_overlay(
    payload: dict[str, Any],
    replay_by_map: dict[str, dict[str, Any]],
    *,
    cross: dict[str, Any] | None = None,
    player_ids: Any = None,
) -> dict[str, list[dict[str, Any]]]:
    """One landed match → fact buckets. Replay optional per map."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "rounds": [],
        "round_players": [],
        "round_economy": [],
        "kills": [],
        "replay_events": [],
    }
    match_id = coalesce_id(payload.get("rib_match_id"))
    event_id = _s(payload.get("rib_event_id"))
    match_date = _s(payload.get("match_date"))
    vlr_match_id = _s((cross or {}).get("vlr_match_id"))
    vlr_event_id = _s((cross or {}).get("vlr_event_id"))
    maps = payload.get("maps") if isinstance(payload.get("maps"), list) else []
    for map_index, map_row in enumerate(maps, start=1):
        if not isinstance(map_row, dict):
            continue
        map_id = _s(map_row.get("id")) or f"{match_id}-m{map_index}"
        map_name = _s(map_row.get("map") or map_row.get("map_name"))
        game_n = _map_game_number(map_id, map_index)
        replay_blob = replay_by_map.get(map_id) or {}
        replay = replay_blob.get("replayData") if isinstance(replay_blob.get("replayData"), dict) else replay_blob
        if not isinstance(replay, dict):
            replay = {}
        name_to_actor = _roster_by_name(replay)
        replay_rounds = replay.get("rounds") if isinstance(replay.get("rounds"), list) else []
        actor_to_player: dict[str, str] = {}
        player_to_vlr: dict[str, str | None] = {}

        rounds = map_row.get("rounds") if isinstance(map_row.get("rounds"), list) else []
        round_stats = map_row.get("roundStats") if isinstance(map_row.get("roundStats"), list) else []
        round_economy = map_row.get("roundEconomy") if isinstance(map_row.get("roundEconomy"), list) else []

        for round_number, round_row in enumerate(rounds, start=1):
            if not isinstance(round_row, dict):
                continue
            winner_side = _s(round_row.get("winner"))
            attacker = _s(round_row.get("attackerTeam"))
            win_type = _s(round_row.get("winType"))
            winning_rib = resolve_rib_team_id(payload, winner_side)
            losing_rib = resolve_rib_team_id(payload, _other_side(winner_side))
            buckets["rounds"].append(
                {
                    "rib_match_id": match_id,
                    "rib_map_id": map_id,
                    "rib_event_id": event_id,
                    "vlr_match_id": vlr_match_id,
                    "vlr_event_id": vlr_event_id,
                    "match_date": match_date,
                    "map_name": map_name,
                    "map_game_number": game_n,
                    "round_number": round_number,
                    "winning_rib_team_id": winning_rib,
                    "winning_vlr_team_id": resolve_vlr_team_id(cross, winner_side),
                    "losing_rib_team_id": losing_rib,
                    "losing_vlr_team_id": resolve_vlr_team_id(cross, _other_side(winner_side)),
                    "win_type": win_type,
                    "is_attack_win": (winner_side or "").upper() == (attacker or "").upper() if winner_side and attacker else None,
                    "mvp_agent": _s(round_row.get("mvpAgent")),
                    "leftover_json": _leftover(round_row, ROUND_KEYS),
                }
            )

        for round_number, players in enumerate(round_stats, start=1):
            if not isinstance(players, list):
                continue
            replay_round = replay_rounds[round_number - 1] if round_number - 1 < len(replay_rounds) and isinstance(replay_rounds[round_number - 1], dict) else {}
            freeze_t = to_float(replay_round.get("freezetimeEndT")) if replay_round else None
            states_by_actor = _player_states(replay_round) if replay_round else {}
            for player in players:
                if not isinstance(player, dict):
                    continue
                player_id = coalesce_id(player.get("playerId") or player.get("id"))
                ign = _s(player.get("name"))
                side = _s(player.get("team") or player.get("side") if player.get("team") in {"A", "B"} else player.get("team"))
                team_letter = _s(player.get("team"))
                rib_team_id = resolve_rib_team_id(payload, team_letter)
                vlr_team_id = resolve_vlr_team_id(cross, team_letter)
                vlr_player_id = resolve_vlr_player(player_ids, vlr_team_id, ign)
                actor_id = name_to_actor.get((ign or "").lower()) if ign else None
                if actor_id:
                    actor_to_player[actor_id] = player_id
                player_to_vlr[player_id] = vlr_player_id
                loadout_row = _freeze_loadout(states_by_actor.get(actor_id or "", []), freeze_t) if actor_id else {}
                armor_hp = to_int(loadout_row.get("armor"))
                leftover_player = {key: value for key, value in player.items() if key not in ROUND_STAT_KEYS}
                if loadout_row:
                    leftover_player["replay_loadout"] = {
                        key: value
                        for key, value in loadout_row.items()
                        if key not in {"weapon", "armor", "money", "loadoutValue", "t"}
                    }
                buckets["round_players"].append(
                    {
                        "rib_match_id": match_id,
                        "rib_map_id": map_id,
                        "rib_event_id": event_id,
                        "rib_team_id": rib_team_id,
                        "rib_player_id": player_id,
                        "rib_actor_id": actor_id,
                        "vlr_match_id": vlr_match_id,
                        "vlr_event_id": vlr_event_id,
                        "vlr_team_id": vlr_team_id,
                        "vlr_player_id": vlr_player_id,
                        "match_date": match_date,
                        "map_name": map_name,
                        "map_game_number": game_n,
                        "round_number": round_number,
                        "player_name": ign,
                        "agent_name": _s(player.get("agent")),
                        "side": _s(player.get("side")),
                        "weapon_name": _s(loadout_row.get("weapon")),
                        "armor_hp": armor_hp,
                        "armor_name": _armor_name(armor_hp),
                        "loadout": to_int(loadout_row.get("loadoutValue")),
                        "leftover_credits": to_int(loadout_row.get("money")),
                        "acs": to_float(player.get("acs")),
                        "kills": to_int(player.get("kills")),
                        "deaths": to_int(player.get("deaths")),
                        "assists": to_int(player.get("assists")),
                        "damage": to_int(player.get("damage")),
                        "hs_pct": to_float(player.get("hsPct")),
                        "is_alive": player.get("alive") if isinstance(player.get("alive"), bool) else None,
                        "is_first_kill": player.get("firstKill") if isinstance(player.get("firstKill"), bool) else None,
                        "leftover_json": json_dumps(leftover_player) if leftover_player else None,
                    }
                )

            events = replay_round.get("events") if isinstance(replay_round.get("events"), list) else []
            event_index = 0
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_type = _s(event.get("type")) or ""
                if event_type in SKIP_REPLAY_TYPES:
                    continue
                event_index += 1
                actor_id = _s(event.get("actorId"))
                target_id = _s(event.get("targetId"))
                pos_x, pos_y = _pos_xy(event.get("pos"))
                target_pos = event.get("targetPos")
                tx, ty = _pos_xy(target_pos)
                known = {"t", "pos", "type", "actorId", "targetId", "weapon", "ability", "targetPos"}
                actor_player = actor_to_player.get(actor_id or "")
                target_player = actor_to_player.get(target_id or "")
                buckets["replay_events"].append(
                    {
                        "rib_match_id": match_id,
                        "rib_map_id": map_id,
                        "rib_event_id": event_id,
                        "vlr_match_id": vlr_match_id,
                        "vlr_event_id": vlr_event_id,
                        "match_date": match_date,
                        "map_name": map_name,
                        "map_game_number": game_n,
                        "round_number": round_number,
                        "event_index": event_index,
                        "event_type": event_type,
                        "t_ms": to_float(event.get("t")),
                        "actor_rib_player_id": actor_player,
                        "actor_rib_actor_id": actor_id,
                        "actor_vlr_player_id": player_to_vlr.get(actor_player or ""),
                        "target_rib_player_id": target_player,
                        "target_rib_actor_id": target_id,
                        "target_vlr_player_id": player_to_vlr.get(target_player or ""),
                        "weapon_name": _s(event.get("weapon")),
                        "ability_name": _s(event.get("ability")),
                        "pos_x": pos_x,
                        "pos_y": pos_y,
                        "leftover_json": _leftover(event, known),
                    }
                )
                if event_type == "kill":
                    buckets["kills"].append(
                        {
                            "rib_match_id": match_id,
                            "rib_map_id": map_id,
                            "rib_event_id": event_id,
                            "vlr_match_id": vlr_match_id,
                            "vlr_event_id": vlr_event_id,
                            "match_date": match_date,
                            "map_name": map_name,
                            "map_game_number": game_n,
                            "round_number": round_number,
                            "event_index": event_index,
                            "t_ms": to_float(event.get("t")),
                            "weapon_name": _s(event.get("weapon")),
                            "killer_rib_player_id": actor_player,
                            "killer_rib_actor_id": actor_id,
                            "killer_vlr_player_id": player_to_vlr.get(actor_player or ""),
                            "victim_rib_player_id": target_player,
                            "victim_rib_actor_id": target_id,
                            "victim_vlr_player_id": player_to_vlr.get(target_player or ""),
                            "killer_x": pos_x,
                            "killer_y": pos_y,
                            "victim_x": tx,
                            "victim_y": ty,
                            "leftover_json": _leftover(event, known),
                        }
                    )

        for round_number, eco in enumerate(round_economy, start=1):
            if not isinstance(eco, dict):
                continue
            for team_letter, cell in eco.items():
                if not isinstance(cell, dict):
                    continue
                buckets["round_economy"].append(
                    {
                        "rib_match_id": match_id,
                        "rib_map_id": map_id,
                        "rib_event_id": event_id,
                        "rib_team_id": resolve_rib_team_id(payload, str(team_letter)),
                        "vlr_match_id": vlr_match_id,
                        "vlr_event_id": vlr_event_id,
                        "vlr_team_id": resolve_vlr_team_id(cross, str(team_letter)),
                        "match_date": match_date,
                        "map_name": map_name,
                        "map_game_number": game_n,
                        "round_number": round_number,
                        "bank": to_int(cell.get("bank")),
                        "loadout": to_int(cell.get("loadout")),
                        "buy_tier": _s(cell.get("buyTier") or cell.get("buy_tier")),
                        "leftover_json": _leftover(cell, {"bank", "loadout", "buyTier", "buy_tier"}),
                    }
                )
    return buckets


def load_replay_maps(repo_root: Path, match_id: str, map_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Read replay JSON per map id; missing files are skipped (match still parses)."""
    out: dict[str, dict[str, Any]] = {}
    for map_id in map_ids:
        path = replay_json_path(repo_root, match_id, map_id)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.exception("[rib_parse] Bad replay json match=%s map=%s", match_id, map_id)
            continue
        if isinstance(payload, dict):
            out[map_id] = payload
    return out


def parse_landed_match(repo_root: Path, match_id: str, *, cross: dict[str, Any] | None, player_ids: Any) -> dict[str, list[dict[str, Any]]]:
    """Read one match JSON + its replays and explode facts."""
    path = match_json_path(repo_root, match_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    maps = payload.get("maps") if isinstance(payload.get("maps"), list) else []
    map_ids = [str(row.get("id")) for row in maps if isinstance(row, dict) and row.get("id")]
    replays = load_replay_maps(repo_root, match_id, map_ids)
    return parse_match_overlay(payload, replays, cross=cross, player_ids=player_ids)
