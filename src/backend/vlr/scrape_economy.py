"""Scrape VLR economy-tab round bank — vlrggapi only returns the team buy-win table."""

from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from backend.api_connectors.vlr_connector import SITE_BASE, VlrSessionFactory

logger = logging.getLogger(__name__)

BUY_TYPE_FROM_SYMBOL = {
    "": "pistol_eco",
    "$": "semi_eco",
    "$$": "semi_buy",
    "$$$": "full_buy",
}


def _bank_credits(text: str) -> int | None:
    """Turn VLR `0.4k` / `26.9k` into credits for fact_round_economy_detail.bank."""
    raw = (text or "").strip().lower().replace(",", "")
    if not raw:
        return None
    if raw.endswith("k"):
        try:
            return int(round(float(raw[:-1]) * 1000))
        except ValueError:
            return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def _loadout_credits(title: str | None) -> int | None:
    """`rnd-sq title` is equipment value in credits."""
    if not title:
        return None
    digits = re.sub(r"[^\d]", "", title)
    return int(digits) if digits else None


def _side(classes: list[str]) -> str | None:
    if "mod-ct" in classes:
        return "ct"
    if "mod-t" in classes:
        return "t"
    return None


def _parse_team_square(div: Tag) -> dict[str, Any]:
    """One team's buy square: symbol, spend, win, side."""
    classes = list(div.get("class") or [])
    symbol = div.get_text(strip=True)
    return {
        "buy_symbol": symbol,
        "buy_type": BUY_TYPE_FROM_SYMBOL.get(symbol, symbol),
        "loadout_credits": _loadout_credits(div.get("title")),
        "won": "mod-win" in classes,
        "side": _side(classes),
    }


def _parse_round_td(td: Tag, team1_tag: str, team2_tag: str) -> dict[str, Any] | None:
    """One round column: remaining bank + loadout for both teams."""
    round_el = td.select_one(".round-num")
    if round_el is None:
        return None
    banks = [el.get_text(strip=True) for el in td.select("div.bank")]
    squares = td.select("div.rnd-sq")
    if len(banks) < 2 or len(squares) < 2:
        return None
    team1 = _parse_team_square(squares[0])
    team2 = _parse_team_square(squares[1])
    team1["tag"] = team1_tag
    team1["bank"] = banks[0]
    team1["bank_credits"] = _bank_credits(banks[0])
    team2["tag"] = team2_tag
    team2["bank"] = banks[1]
    team2["bank_credits"] = _bank_credits(banks[1])
    if team1["side"] and not team2["side"]:
        team2["side"] = "t" if team1["side"] == "ct" else "ct"
    elif team2["side"] and not team1["side"]:
        team1["side"] = "t" if team2["side"] == "ct" else "ct"
    round_num = int(re.sub(r"[^\d]", "", round_el.get_text()) or 0)
    return {
        "round_num": round_num,
        "is_pistol_round": round_num in {1, 13},
        "team1": team1,
        "team2": team2,
    }


def _parse_bank_table(table: Tag) -> tuple[list[str], list[dict[str, Any]]]:
    """Read both half-rows so overtime maps keep a single round list."""
    tags: list[str] = []
    rounds: list[dict[str, Any]] = []
    for tr in table.select("tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        if not tags:
            tags = [el.get_text(strip=True) for el in tds[0].select("div.team")]
        team1_tag = tags[0] if tags else "team1"
        team2_tag = tags[1] if len(tags) > 1 else "team2"
        for td in tds[1:]:
            parsed = _parse_round_td(td, team1_tag, team2_tag)
            if parsed:
                rounds.append(parsed)
    rounds.sort(key=lambda row: row["round_num"])
    return tags, rounds


def _clean_cell(text: str) -> str:
    """Collapse VLR padded win-count cells (`4 (0)`)."""
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_summary_table(table: Tag) -> list[dict[str, Any]]:
    """Labeled pistol/eco/$/$$/$$$ win counts (headers are `th`, not always `thead`)."""
    header_aliases = {
        "": "team",
        "pistol won": "pistol_won",
        "eco (won)": "eco_won",
        "$ (won)": "semi_eco_won",
        "$$ (won)": "semi_buy_won",
        "$$$ (won)": "full_buy_won",
    }
    raw_headers = [_clean_cell(th.get_text(" ", strip=True)) for th in table.select("tr th")]
    headers = [header_aliases.get(h.lower(), h or f"col_{i}") for i, h in enumerate(raw_headers)]
    if not headers:
        headers = ["team", "pistol_won", "eco_won", "semi_eco_won", "semi_buy_won", "full_buy_won"]
    rows: list[dict[str, Any]] = []
    for tr in table.select("tr"):
        cells = [_clean_cell(td.get_text(" ", strip=True)) for td in tr.select("td")]
        if not cells:
            continue
        row = {headers[i] if i < len(headers) else str(i): cells[i] for i in range(len(cells))}
        rows.append(row)
    return rows


def parse_economy_html(html: str) -> dict[str, dict[str, Any]]:
    """Split one economy-tab page into per-game_id bank + summary."""
    soup = BeautifulSoup(html, "html.parser")
    by_game: dict[str, dict[str, Any]] = {}
    for game in soup.select("div.vm-stats-game[data-game-id]"):
        game_id = str(game.get("data-game-id") or "")
        if not game_id or game_id == "all":
            continue
        summary: list[dict[str, Any]] = []
        tags: list[str] = []
        rounds: list[dict[str, Any]] = []
        for table in game.select("table.wf-table-inset.mod-econ"):
            if "(BANK)" in table.get_text():
                tags, rounds = _parse_bank_table(table)
            else:
                summary = _parse_summary_table(table)
        by_game[game_id] = {
            "game_id": game_id,
            "team_tags": tags,
            "economy_summary": summary,
            "round_economy": rounds,
        }
    return by_game


def fetch_match_economy_html(match_id: str) -> str:
    """One HTML GET: `?game=all&tab=economy` includes every map on the page."""
    url = f"{SITE_BASE}/{match_id}/?game=all&tab=economy"
    logger.info("[scrape_economy] Starting match_id=%s url=%s", match_id, url)
    session = VlrSessionFactory().create(for_html=True)
    response = session.get(url, timeout=45)
    response.raise_for_status()
    logger.info("[scrape_economy] Fetched bytes=%s status=%s", len(response.text), response.status_code)
    return response.text


def attach_round_economy(match: dict[str, Any], *, html: str | None = None) -> dict[str, Any]:
    """Merge per-round bank onto /v2 match details so JSON landings have fact-ready rows."""
    match_id = str(match.get("match_id") or "")
    logger.info("[scrape_economy] Attach start match_id=%s", match_id)
    page = html if html is not None else fetch_match_economy_html(match_id)
    by_game = parse_economy_html(page)
    eco_maps = match.get("economy_by_map") or []
    maps = match.get("maps") or []
    for index, map_row in enumerate(maps):
        if not isinstance(map_row, dict):
            continue
        game_id = ""
        if index < len(eco_maps) and isinstance(eco_maps[index], dict):
            game_id = str(eco_maps[index].get("game_id") or "")
        game_id = game_id or str(map_row.get("game_id") or "")
        parsed = by_game.get(game_id) or {}
        map_row["game_id"] = game_id
        if parsed.get("economy_summary"):
            map_row["economy"] = parsed["economy_summary"]
        map_row["round_economy"] = parsed.get("round_economy") or []
        logger.info(
            "[scrape_economy] Map %s game_id=%s rounds=%s",
            map_row.get("map_name"),
            game_id,
            len(map_row["round_economy"]),
        )
    round_economy_by_map: list[dict[str, Any]] = []
    for index, item in enumerate(eco_maps):
        if not isinstance(item, dict):
            continue
        game_id = str(item.get("game_id") or "")
        if not game_id:
            continue
        map_name = maps[index].get("map_name") if index < len(maps) and isinstance(maps[index], dict) else None
        round_economy_by_map.append(
            {
                "game_id": game_id,
                "map_name": map_name,
                "round_economy": (by_game.get(game_id) or {}).get("round_economy") or [],
            }
        )
    match["round_economy_by_map"] = round_economy_by_map
    total = sum(len(block.get("round_economy") or []) for block in match["round_economy_by_map"])
    logger.info("[scrape_economy] Done match_id=%s maps=%s rounds=%s", match_id, len(by_game), total)
    return match
