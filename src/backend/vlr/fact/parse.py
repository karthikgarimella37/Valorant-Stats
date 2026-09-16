"""Turn one matches.jsonl object into fact rows (metrics + binary + grain keys)."""

from __future__ import annotations

from typing import Any

from backend.vlr.dim.util import canonical_agent_name
from backend.vlr.fact.player_ids import PlayerIdLookup
from backend.vlr.fact.util import (
    duration_sec,
    match_advanced,
    other_team_id,
    parse_veto_actions,
    played_won,
    remap_advanced,
    to_float,
    to_int,
    win_method_code,
)


def _s(value: Any) -> str | None:
    """Blank strings become null so facts do not store empty keys."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _score_pair(raw: Any) -> tuple[int | None, int | None]:
    """Map score {team1, team2} whether nested or flat ints."""
    if not isinstance(raw, dict):
        return None, None
    t1 = raw.get("team1")
    t2 = raw.get("team2")
    if isinstance(t1, dict):
        t1 = t1.get("total")
    if isinstance(t2, dict):
        t2 = t2.get("total")
    return to_int(t1), to_int(t2)


def _economy_counts(row: dict[str, Any]) -> dict[str, int | None]:
    """Numbered /v2 economy cells: pistol=1 eco=2 semi-eco=3 semi-buy=4 full=5."""
    mapped = {
        "pistol": row.get("1") or row.get("pistol") or row.get("Pistol"),
        "eco": row.get("2") or row.get("eco") or row.get("Eco"),
        "semi_eco": row.get("3") or row.get("semi_eco"),
        "semi_buy": row.get("4") or row.get("semi_buy"),
        "full_buy": row.get("5") or row.get("full") or row.get("Full"),
    }
    out: dict[str, int | None] = {}
    for name, cell in mapped.items():
        played, won = played_won(cell)
        out[f"{name}_played"] = played
        out[f"{name}_won"] = won
    return out


def parse_match_facts(
    row: dict[str, Any],
    *,
    player_ids: PlayerIdLookup | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """One landing line → buckets keyed by jsonl stem. Skip list-only 429 stubs."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "overall": [],
        "performance": [],
        "rounds": [],
        "map_games": [],
        "series": [],
        "economy": [],
        "round_economy": [],
        "vetos": [],
    }
    match_id = _s(row.get("vlr_match_id"))
    detail = row.get("detail")
    if not match_id or not isinstance(detail, dict):
        return buckets
    maps = detail.get("maps")
    if not isinstance(maps, list) or not maps:
        return buckets

    event_id = _s(row.get("vlr_event_id"))
    match_date = _s(row.get("match_date"))
    team_1_id = _s(row.get("vlr_team_1_id"))
    team_2_id = _s(row.get("vlr_team_2_id"))
    teams = detail.get("teams") if isinstance(detail.get("teams"), list) else []
    team_1 = teams[0] if teams and isinstance(teams[0], dict) else {}
    team_2 = teams[1] if len(teams) > 1 and isinstance(teams[1], dict) else {}
    if not team_1_id:
        team_1_id = _s(team_1.get("id"))
    if not team_2_id:
        team_2_id = _s(team_2.get("id"))

    series_advanced: dict[str, dict[str, Any]] = {}
    performance = detail.get("performance")
    if isinstance(performance, dict):
        for adv in performance.get("advanced_stats") or []:
            if isinstance(adv, dict) and adv.get("player"):
                series_advanced[str(adv["player"]).strip().lower()] = remap_advanced(adv)

    for eco in detail.get("economy") or []:
        if not isinstance(eco, dict):
            continue
        tag = _s(eco.get("0") or eco.get("team") or eco.get("Team"))
        team_id = None
        if tag:
            n1 = (_s(team_1.get("name")) or "").lower()
            n2 = (_s(team_2.get("name")) or "").lower()
            t = tag.lower()
            if t == n1 or n1.startswith(t) or t in n1:
                team_id = team_1_id
            elif t == n2 or n2.startswith(t) or t in n2:
                team_id = team_2_id
        if not team_id:
            continue
        counts = _economy_counts(eco)
        buckets["economy"].append(
            {
                "fact_key": fact_key(match_id, team_id),
                "vlr_match_id": match_id,
                "vlr_event_id": event_id,
                "match_date": match_date,
                "vlr_team_id": team_id,
                **counts,
            }
        )

    for action in parse_veto_actions(_s(row.get("map_vetos")) or _s(detail.get("map_vetos"))):
        buckets["vetos"].append(
            {
                "fact_key": fact_key(match_id, action["action_order"]),
                "vlr_match_id": match_id,
                "vlr_event_id": event_id,
                "match_date": match_date,
                "map_name": action["map_name"],
                "team_tag": action["team_tag"],
                "action_order": action["action_order"],
                "is_ban": action["is_ban"],
                "is_pick": action["is_pick"],
                "is_decider": action["is_decider"],
            }
        )

    for side, team_id, team_obj in (("team1", team_1_id, team_1), ("team2", team_2_id, team_2)):
        maps_won = to_int(team_obj.get("score"))
        if maps_won is None:
            maps_won = to_int(row.get("team_1_score") if side == "team1" else row.get("team_2_score"))
        other = to_int(team_2.get("score") if side == "team1" else team_1.get("score"))
        if other is None:
            other = to_int(row.get("team_2_score") if side == "team1" else row.get("team_1_score"))
        is_winner = team_obj.get("is_winner")
        if is_winner is None and maps_won is not None and other is not None:
            is_winner = maps_won > other
        if not team_id:
            continue
        buckets["series"].append(
            {
                "fact_key": fact_key(match_id, team_id),
                "vlr_match_id": match_id,
                "vlr_event_id": event_id,
                "match_date": match_date,
                "vlr_team_id": team_id,
                "maps_won": maps_won,
                "maps_lost": other,
                "is_winner": bool(is_winner) if is_winner is not None else None,
            }
        )

    for map_game_number, map_row in enumerate(maps, start=1):
        if not isinstance(map_row, dict):
            continue
        map_name = _s(map_row.get("map_name") or map_row.get("name"))
        if not map_name:
            continue
        t1_rounds, t2_rounds = _score_pair(map_row.get("score"))
        t1_atk, t2_atk = _score_pair(map_row.get("score_t"))
        t1_def, t2_def = _score_pair(map_row.get("score_ct"))
        t1_ot, t2_ot = _score_pair(map_row.get("score_ot"))
        seconds = duration_sec(map_row.get("duration"))
        picked_by = _s(map_row.get("picked_by"))
        team1_won = (
            t1_rounds is not None and t2_rounds is not None and t1_rounds > t2_rounds
        )
        for side, team_id, won, lost, atk, deff, ot in (
            ("team1", team_1_id, t1_rounds, t2_rounds, t1_atk, t1_def, t1_ot),
            ("team2", team_2_id, t2_rounds, t1_rounds, t2_atk, t2_def, t2_ot),
        ):
            if not team_id:
                continue
            is_pick = bool(picked_by) and picked_by.lower() in {
                (_s(team_1.get("name")) or "").lower() if side == "team1" else (_s(team_2.get("name")) or "").lower(),
                (_s(team_1.get("tag")) or "").lower() if side == "team1" else (_s(team_2.get("tag")) or "").lower(),
            }
            buckets["map_games"].append(
                {
                    "fact_key": fact_key(match_id, map_game_number, team_id),
                    "vlr_match_id": match_id,
                    "vlr_event_id": event_id,
                    "match_date": match_date,
                    "map_name": map_name,
                    "map_game_number": map_game_number,
                    "vlr_team_id": team_id,
                    "rounds_won": won,
                    "rounds_lost": lost,
                    "attack_rounds_won": atk,
                    "defense_rounds_won": deff,
                    "overtime_rounds_won": ot,
                    "duration_sec": seconds,
                    "is_winner": (team1_won if side == "team1" else (not team1_won and t1_rounds != t2_rounds))
                    if t1_rounds is not None and t2_rounds is not None
                    else None,
                    "is_map_pick": is_pick,
                }
            )

        players = map_row.get("players") if isinstance(map_row.get("players"), dict) else {}
        rounds_played = (t1_rounds or 0) + (t2_rounds or 0) if t1_rounds is not None and t2_rounds is not None else None
        for side in ("team1", "team2"):
            team_id = team_1_id if side == "team1" else team_2_id
            is_winner = None
            if t1_rounds is not None and t2_rounds is not None and t1_rounds != t2_rounds:
                is_winner = t1_rounds > t2_rounds if side == "team1" else t2_rounds > t1_rounds
            for player in players.get(side) or []:
                if not isinstance(player, dict):
                    continue
                ign = _s(player.get("name"))
                if not ign:
                    continue
                agent = canonical_agent_name(_s(player.get("agent")))
                player_id = (
                    player_ids.resolve(team_id, ign, player.get("id") or player.get("player_id"))
                    if player_ids
                    else _s(player.get("id") or player.get("player_id"))
                )
                if team_id and player_id:
                    buckets["overall"].append(
                        {
                            "vlr_match_id": match_id,
                            "vlr_event_id": event_id,
                            "match_date": match_date,
                            "map_name": map_name,
                            "map_game_number": map_game_number,
                            "player_name": ign,
                            "vlr_team_id": team_id,
                            "vlr_player_id": player_id,
                            "agent_name": agent,
                            "kills": to_int(player.get("kills")),
                            "deaths": to_int(player.get("deaths")),
                            "assists": to_int(player.get("assists")),
                            "plus_minus": to_int(player.get("kd_diff") or player.get("plus_minus")),
                            "acs": to_float(player.get("acs")),
                            "adr": to_float(player.get("adr")),
                            "rating": to_float(player.get("rating")),
                            "rounds_played": rounds_played,
                            "is_winner": is_winner,
                        }
                    )
                # Keep concat fact_key: in-flight performance load upserts on that column.
                key = fact_key(match_id, map_game_number, ign)
                adv = match_advanced(ign, series_advanced) if map_game_number == 1 else {}
                buckets["performance"].append(
                    {
                        "fact_key": key,
                        "vlr_match_id": match_id,
                        "vlr_event_id": event_id,
                        "match_date": match_date,
                        "map_name": map_name,
                        "map_game_number": map_game_number,
                        "player_name": ign,
                        "vlr_team_id": team_id,
                        "agent_name": agent,
                        "kast": to_float(player.get("kast")),
                        "hs_pct": to_float(player.get("hs_pct")),
                        "first_kills": to_int(player.get("fk")),
                        "first_deaths": to_int(player.get("fd")),
                        "fk_diff": to_int(player.get("fk_diff")),
                        "multi_k2": to_int(adv.get("multi_2k") or adv.get("2K")),
                        "multi_k3": to_int(adv.get("multi_3k") or adv.get("3K")),
                        "multi_k4": to_int(adv.get("multi_4k") or adv.get("4K")),
                        "multi_k5": to_int(adv.get("multi_5k") or adv.get("5K")),
                        "clutch_v1": to_int(adv.get("clutch_1v1") or adv.get("1v1")),
                        "clutch_v2": to_int(adv.get("clutch_1v2") or adv.get("1v2")),
                        "clutch_v3": to_int(adv.get("clutch_1v3") or adv.get("1v3")),
                        "clutch_v4": to_int(adv.get("clutch_1v4") or adv.get("1v4")),
                        "clutch_v5": to_int(adv.get("clutch_1v5") or adv.get("1v5")),
                        "econ": to_int(adv.get("econ")),
                        "plants": to_int(adv.get("plants")),
                        "defuses": to_int(adv.get("defuses")),
                    }
                )

        for round_row in map_row.get("rounds") or []:
            if not isinstance(round_row, dict):
                continue
            round_number = to_int(round_row.get("round_num") or round_row.get("number"))
            if round_number is None:
                continue
            winner_side = str(round_row.get("winner") or "").lower()
            winning_team_id = (
                team_1_id if winner_side in {"team1", "1"} else team_2_id if winner_side in {"team2", "2"} else None
            )
            side = str(round_row.get("side") or "").lower()
            buckets["rounds"].append(
                {
                    "fact_key": fact_key(match_id, map_game_number, round_number),
                    "vlr_match_id": match_id,
                    "vlr_event_id": event_id,
                    "match_date": match_date,
                    "map_name": map_name,
                    "map_game_number": map_game_number,
                    "round_number": round_number,
                    "winning_vlr_team_id": winning_team_id,
                    "losing_vlr_team_id": other_team_id(winning_team_id, team_1_id, team_2_id),
                    "is_attack_win": side in {"t", "attack", "atk"},
                    "win_method_code": win_method_code(round_row.get("method")),
                }
            )

        for eco_round in map_row.get("round_economy") or []:
            if not isinstance(eco_round, dict):
                continue
            round_number = to_int(eco_round.get("round_num") or eco_round.get("round_number"))
            if round_number is None:
                continue
            pistol = bool(eco_round.get("is_pistol_round")) if "is_pistol_round" in eco_round else round_number in {1, 13}
            for side, team_id in (("team1", team_1_id), ("team2", team_2_id)):
                cell = eco_round.get(side)
                if not isinstance(cell, dict) or not team_id:
                    continue
                side_code = _s(cell.get("side"))
                buckets["round_economy"].append(
                    {
                        "fact_key": fact_key(match_id, map_game_number, round_number, team_id),
                        "vlr_match_id": match_id,
                        "vlr_event_id": event_id,
                        "match_date": match_date,
                        "map_name": map_name,
                        "map_game_number": map_game_number,
                        "round_number": round_number,
                        "vlr_team_id": team_id,
                        "economy_code": _s(cell.get("buy_type")),
                        "bank": to_int(cell.get("bank_credits") or cell.get("bank")),
                        "loadout": to_int(cell.get("loadout_credits") or cell.get("loadout")),
                        "is_pistol_round": pistol,
                        "is_winner": bool(cell.get("won")) if cell.get("won") is not None else None,
                        "is_attack": side_code in {"t", "attack", "atk"} if side_code else None,
                    }
                )

    return buckets
