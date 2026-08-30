"""Probe vlrggapi against one live VLR match so we know what the wrapper actually returns."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from backend.api_connectors.vlr_v2_connector import VlrV2Connector
from backend.vlr.scrape_economy import attach_round_economy
from backend.vlr.snapshot_json import write_entity_json

logger = logging.getLogger(__name__)

EXAMPLE_MATCH_ID = "742485"
EXAMPLE_MATCH_URL = "https://www.vlr.gg/742485/gen-g-vs-t1-vct-2026-pacific-stage-2-lr2"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _check(name: str, ok: bool, note: str) -> dict[str, Any]:
    return {"field": name, "ok": ok, "note": note}


def cover_match(match: dict[str, Any]) -> list[dict[str, Any]]:
    """Score the Gen.G vs T1 payload against the VLR match page checklist."""
    event = match.get("event") or {}
    teams = match.get("teams") or []
    maps = match.get("maps") or []
    first_players = ((maps[0].get("players") or {}).get("team1") or []) if maps else []
    first_player = first_players[0] if first_players else {}
    adv = ((maps[0].get("performance") or {}).get("advanced_stats") or []) if maps else []
    adv0 = adv[0] if adv else {}
    eco0 = ((maps[0].get("economy") or [None])[0]) if maps else None
    labeled_adv = any(k in adv0 for k in ("2K", "3K", "ECON", "Econ", "PL"))
    labeled_eco = isinstance(eco0, dict) and any(
        str(k).lower() in {"team", "pistol", "eco", "full"} for k in eco0
    )
    has_half_on_player = any(
        k in first_player for k in ("rating_attack", "acs_t", "kills_t", "attack", "defend")
    )
    rounds = (maps[0].get("rounds") or []) if maps else []
    has_round_method = any(r.get("method") for r in rounds)
    bank_rounds = (maps[0].get("round_economy") or []) if maps else []
    has_round_bank = bool(bank_rounds) and bool((bank_rounds[0].get("team1") or {}).get("bank"))
    return [
        _check("event.name", _present(event.get("name")), str(event.get("name"))),
        _check("event.series / stage", _present(event.get("series")), str(event.get("series"))),
        _check("event.id on match", _present(event.get("id") or match.get("event_id")), "missing — resolve via /v2/search"),
        _check("date + time + patch", "Patch" in str(match.get("date")), str(match.get("date"))),
        _check("map_vetos", _present(match.get("map_vetos")), str(match.get("map_vetos"))[:80]),
        _check("series score", len(teams) == 2 and _present(teams[0].get("score")), json.dumps([t.get("name") + ":" + str(t.get("score")) for t in teams])),
        _check("team ids", all(t.get("id") for t in teams), json.dumps([t.get("id") for t in teams])),
        _check("maps played", len(maps) >= 2, f"n={len(maps)} names={[m.get('map_name') for m in maps]}"),
        _check(
            "overview player All",
            bool(first_player.get("acs") and first_player.get("kills")),
            f"{first_player.get('name')} {first_player.get('agent')} R={first_player.get('rating')} ACS={first_player.get('acs')}",
        ),
        _check("team tag on match", any((t.get("tag") or "").strip() for t in teams), "empty on match; GEN is on team profile"),
        _check("overview Attack/Defend splits", has_half_on_player, "API only reads .side.mod-both"),
        _check(
            "performance values present (unlabeled 1-13)",
            bool(adv0.get("2") or adv0.get("11")),
            "remap 2=2K,3=3K,4=4K,5=5K,6-10=1vX,11=ECON,12=PL,13=DE",
        ),
        _check("rounds winner+side", bool(rounds) and "winner" in rounds[0] and "side" in rounds[0], f"n={len(rounds)}"),
        _check("round win method", has_round_method, "not in payload"),
        _check("performance 2K..1v5/ECON/PL/DE labeled", labeled_adv, f"keys={list(adv0.keys())}"),
        _check("economy team buy-win table labeled", labeled_eco, f"eco0={eco0}"),
        _check(
            "economy per round bank/loadout",
            has_round_bank,
            f"n={len(bank_rounds)} r1={bank_rounds[0] if bank_rounds else None}",
        ),
    ]


def cover_event(event_detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Score event 2776 against the VCT Pacific Stage 2 page."""
    event = event_detail.get("event") or event_detail
    prizes = event_detail.get("prizes") or []
    teams = event_detail.get("teams") or []
    stands = event_detail.get("standings") or []
    prize_with_team = sum(1 for p in prizes if (p.get("team") or {}).get("id"))
    return [
        _check("circuit name", "Champions Tour" in str(event.get("series")), str(event.get("series"))),
        _check("event title", _present(event.get("name")), str(event.get("name"))),
        _check("subtitle", _present(event.get("subtitle")), str(event.get("subtitle"))),
        _check("dates", _present(event.get("dates")), str(event.get("dates"))),
        _check("prize pool", _present(event.get("prize")), str(event.get("prize"))),
        _check("location/venue", _present(event.get("location")), str(event.get("location"))),
        _check("prize rows", len(prizes) >= 4, f"n={len(prizes)} with_team={prize_with_team}"),
        _check("prize points/note", any(p.get("points") or p.get("note") for p in prizes), "not in prize objects"),
        _check("participating teams", len(teams) >= 1, f"n={len(teams)}"),
        _check("group/playoff standings tables", len(stands) > 0, "0 tables — use events/matches.event_series instead"),
    ]


def cover_team(profile: dict[str, Any], transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score Gen.G team page fields."""
    roster = profile.get("roster") or []
    coaches = [p for p in roster if "coach" in str(p.get("role") or "").lower()]
    socials = profile.get("social_links") or []
    has_site = any("geng.gg" in str(s.get("url")) for s in socials)
    has_tw = any("geng_gold" in str(s.get("url")) for s in socials)
    return [
        _check("name+tag", profile.get("name") == "Gen.G" and profile.get("tag") == "GEN", f"{profile.get('name')} {profile.get('tag')}"),
        _check("country", _present(profile.get("country_name")), str(profile.get("country_name"))),
        _check("website", has_site, json.dumps(socials)[:200]),
        _check("twitter", has_tw, "geng_gold in social_links"),
        _check("current roster", len(roster) >= 5, f"n={len(roster)}"),
        _check("staff/coaches", len(coaches) >= 1, f"roles={[p.get('alias')+':'+str(p.get('role')) for p in coaches]}"),
        _check("is_staff flag", any(p.get("is_staff") for p in roster), "false for coaches — filter on role"),
        _check("description parsed", "geng.gg" not in str(profile.get("description") or "").replace(" ", ""), "header text is concatenated"),
        _check("transactions present", len(transactions) >= 1, f"n={len(transactions)}"),
        _check(
            "transaction date/role aligned",
            bool(transactions) and str(transactions[0].get("date") or "").count("-") >= 2,
            "date is real name; role is often a tweet URL",
        ),
    ]


def run_probe(repo_root: Path | None = None) -> dict[str, Any]:
    """Fetch the example match graph and write JSON + a coverage report."""
    repo_root = Path(repo_root or REPO_ROOT)
    out_dir = repo_root / "data" / "vlr" / "api_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("[probe] Starting example match=%s", EXAMPLE_MATCH_ID)
    connector = VlrV2Connector()
    connector.health()

    match = connector.get_match_details(EXAMPLE_MATCH_ID)
    write_entity_json(
        repo_root,
        entity_type="matches",
        entity_id=EXAMPLE_MATCH_ID,
        payload=match,
        source_url=EXAMPLE_MATCH_URL,
    )

    search = connector.search("VCT 2026 Pacific Stage 2")
    events = ((search.get("results") or {}).get("events") or []) if isinstance(search, dict) else []
    event_id = str(events[0]["id"]) if events else ""
    event_detail: dict[str, Any] = {}
    event_matches: list[dict[str, Any]] = []
    if event_id:
        event_detail = connector.get_event_detail(event_id)
        event_matches = connector.get_event_matches(event_id)
        write_entity_json(
            repo_root,
            entity_type="events",
            entity_id=event_id,
            payload={"event_id": event_id, **event_detail, "matches": event_matches},
            source_url=f"https://www.vlr.gg/event/{event_id}",
        )

    team_id = (match.get("teams") or [{}])[0].get("id") or "17"
    team = connector.get_team_profile(str(team_id))
    transactions = connector.get_team_transactions(str(team_id))
    write_entity_json(
        repo_root,
        entity_type="teams",
        entity_id=str(team_id),
        payload={**team, "transactions": transactions},
        source_url=f"https://www.vlr.gg/team/{team_id}",
    )

    player_id = ""
    for person in team.get("roster") or []:
        if person.get("alias") == "t3xture":
            player_id = str(person.get("id") or "")
            break
    player: dict[str, Any] = {}
    if player_id:
        player = connector.get_player_profile(player_id)
        write_entity_json(
            repo_root,
            entity_type="players",
            entity_id=player_id,
            payload=player,
            source_url=f"https://www.vlr.gg/player/{player_id}",
        )

    example_stage = next(
        (row.get("event_series") for row in event_matches if str(row.get("match_id")) == EXAMPLE_MATCH_ID),
        "",
    )

    report = {
        "example_match_url": EXAMPLE_MATCH_URL,
        "resolved": {
            "match_id": EXAMPLE_MATCH_ID,
            "event_id": event_id,
            "team_id": str(team_id),
            "player_id": player_id,
            "event_match_count": len(event_matches),
        },
        "match": cover_match(match),
        "event": cover_event(event_detail)
        + [
            _check(
                "match list stage label",
                "Lower Round 2" in str(example_stage),
                str(example_stage),
            )
        ],
        "team": cover_team(team, transactions),
        "player": [
            _check("player profile", _present(player.get("name")), str(player.get("name"))),
            _check("current team", _present((player.get("current_team") or {}).get("name")), str(player.get("current_team"))),
            _check("agent_stats", bool(player.get("agent_stats")), f"n={len(player.get('agent_stats') or [])}"),
        ],
    }
    report["ok_count"] = sum(
        1
        for block in (report["match"], report["event"], report["team"], report["player"])
        for row in block
        if row["ok"]
    )
    report["fail_count"] = sum(
        1
        for block in (report["match"], report["event"], report["team"], report["player"])
        for row in block
        if not row["ok"]
    )
    report_path = out_dir / "coverage_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    logger.info("[probe] Done ok=%s fail=%s path=%s", report["ok_count"], report["fail_count"], report_path)
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = run_probe()
    print(json.dumps({"ok": report["ok_count"], "fail": report["fail_count"], "resolved": report["resolved"]}, indent=2))
    for section in ("match", "event", "team", "player"):
        print(f"\n== {section} ==")
        for row in report[section]:
            mark = "OK " if row["ok"] else "GAP"
            print(f"  {mark}  {row['field']}: {row['note'][:120]}")


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT / "src"))
    main()
