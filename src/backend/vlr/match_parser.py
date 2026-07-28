"""
Parse VLR match HTML (overview / performance / economy tabs).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

OVERVIEW_STAT_KEYS = [
    "rating",
    "acs",
    "kills",
    "deaths",
    "assists",
    "plus_minus",
    "kast",
    "adr",
    "hs_pct",
    "fk",
    "fd",
    "fk_fd_diff",
]


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\t", " ")).strip()


def _map_name_from_game(game_or_map_el: Tag | None) -> str | None:
    """Read map name from a vm-stats-game node or a .map node."""
    if game_or_map_el is None:
        return None
    map_el = (
        game_or_map_el
        if "map" in (game_or_map_el.get("class") or [])
        else game_or_map_el.select_one(".map")
    )
    if map_el is None:
        return None
    cloned = BeautifulSoup(str(map_el), "html.parser").select_one(".map")
    return _extract_map_name(
        cloned,
        fallback_text=map_el.get_text(" ", strip=True),
    )


def _extract_map_name(map_el: Tag | None, fallback_text: str | None = None) -> str | None:
    """
    Derive map name from VLR DOM without a hardcoded map list.

    Handles labels like "Bind PICK 48:56", "Summit", "1 Pearl", etc.
    New maps (e.g. Summit) are picked up automatically.
    """
    if map_el is not None:
        # Prefer the bold map title span when present.
        title_span = map_el.select_one("div[style*='font-weight'] > span, .map span")
        if title_span:
            # Clone-ish: get direct text nodes before nested PICK badge.
            parts: list[str] = []
            for child in title_span.children:
                if getattr(child, "name", None) is None:
                    text = _clean(str(child))
                    if text:
                        parts.append(text)
                elif "picked" in (child.get("class") or []):
                    break
            if parts:
                return _clean(" ".join(parts))

        dur = map_el.select_one(".map-duration")
        if dur:
            dur.extract()
        for picked in map_el.select(".picked"):
            picked.extract()
        text = _clean(map_el.get_text(" ", strip=True))
        if text:
            text = re.sub(r"^\d+\s+", "", text)  # nav style "1 Pearl"
            text = re.split(r"\bPICK\b|\d+:\d+", text, maxsplit=1)[0].strip()
            return text or None

    text = _clean(fallback_text)
    if not text:
        return None
    text = re.sub(r"^\d+\s+", "", text)
    text = re.split(r"\bPICK\b|\d+:\d+", text, maxsplit=1)[0].strip()
    return text or None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip().replace(",", "")
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip().replace("%", "").replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def _triple(text: str) -> tuple[str | None, str | None, str | None]:
    """Split 'both atk def' style cells into three tokens."""
    parts = _clean(text).split()
    if not parts:
        return None, None, None
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        return parts[0], parts[1], None
    return parts[0], parts[1], parts[2]


def _id_from_href(href: str | None, kind: str) -> str | None:
    if not href:
        return None
    m = re.search(rf"/{kind}/(\d+)", href)
    return m.group(1) if m else None


def _abs_url(src: str | None) -> str | None:
    if not src:
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://www.vlr.gg" + src
    if src.startswith("http"):
        return src
    return urljoin("https://www.vlr.gg/", src)


def _agent_from_img(img: Tag | None) -> str | None:
    if not img:
        return None
    src = img.get("src") or ""
    if "agents" not in src and "agent" not in src:
        # still allow alt
        return img.get("alt") or img.get("title")
    name = img.get("alt") or img.get("title")
    if name:
        return name
    return Path(src).stem.replace("_", " ")


def parse_pickban_note(note: str | None, team_name_to_id: dict[str, str | None]) -> list[dict[str, Any]]:
    """Parse strings like 'CGZ ban Fracture; IGZ ban Lotus; CGZ pick Pearl; ...'."""
    if not note:
        return []
    rows: list[dict[str, Any]] = []
    chunks = [c.strip() for c in note.split(";") if c.strip()]
    for index, chunk in enumerate(chunks):
        m = re.match(
            r"^(?P<team>.+?)\s+(?P<action>ban|pick)\s+(?P<map>[A-Za-z0-9/]+)",
            chunk,
            flags=re.I,
        )
        if not m:
            # leftover like 'Decider Ascent'
            m2 = re.match(r"^(?P<label>Decider)\s+(?P<map>[A-Za-z0-9/]+)", chunk, flags=re.I)
            if m2:
                rows.append(
                    {
                        "order_index": index,
                        "action": "decider",
                        "map_name": m2.group("map"),
                        "team_name": None,
                        "team_id": None,
                        "raw": chunk,
                    }
                )
            continue
        team_name = m.group("team").strip()
        rows.append(
            {
                "order_index": index,
                "action": m.group("action").lower(),
                "map_name": m.group("map"),
                "team_name": team_name,
                "team_id": team_name_to_id.get(team_name),
                "raw": chunk,
            }
        )
    return rows


class VLRMatchParser:
    """Parse one VLR match across overview/performance/economy HTML documents."""

    def __init__(
        self,
        overview_html: str,
        *,
        match_id: str | int,
        performance_html: str | None = None,
        economy_html: str | None = None,
    ):
        self.match_id = str(match_id)
        self.overview = BeautifulSoup(overview_html, "html.parser")
        self.performance = BeautifulSoup(performance_html, "html.parser") if performance_html else None
        self.economy = BeautifulSoup(economy_html, "html.parser") if economy_html else None

    def parse(self) -> dict[str, list[dict[str, Any]]]:
        match_row = self.extract_match_dimension()
        maps = self.extract_match_maps()
        teams = self.extract_teams()
        team_name_to_id = {
            (t.get("name") or "").strip(): t.get("id") for t in teams if t.get("name")
        }
        # also short tags from maps header if needed
        pickban = parse_pickban_note(match_row.get("note"), team_name_to_id)
        for row in pickban:
            row["match_id"] = self.match_id

        overview_rows, players, agents = self.extract_overview_stats()
        rounds = self.extract_rounds()
        performance_rows = self.extract_performance() if self.performance else []
        economy_rows = self.extract_economy() if self.economy else []

        for row in overview_rows + performance_rows + economy_rows + rounds + maps:
            row.setdefault("match_id", self.match_id)

        return {
            "dim_matches": [match_row],
            "dim_teams": teams,
            "dim_players": players,
            "dim_agents": agents,
            "dim_maps": [{"name": m["map_name"]} for m in maps if m.get("map_name")],
            "fact_match_maps": maps,
            "fact_map_pickban": pickban,
            "fact_player_overview": overview_rows,
            "fact_player_performance": performance_rows,
            "fact_player_economy": economy_rows,
            "fact_rounds": rounds,
        }

    def extract_match_dimension(self) -> dict[str, Any]:
        soup = self.overview
        team_links = soup.select("a.match-header-link")
        team1_name = team2_name = team1_id = team2_id = None
        team1_logo = team2_logo = None
        if len(team_links) >= 1:
            team1_name = _clean(team_links[0].select_one(".wf-title-med").get_text() if team_links[0].select_one(".wf-title-med") else team_links[0].get_text())
            team1_id = _id_from_href(team_links[0].get("href"), "team")
            img = team_links[0].select_one("img")
            team1_logo = _abs_url(img.get("src") if img else None)
        if len(team_links) >= 2:
            team2_name = _clean(team_links[1].select_one(".wf-title-med").get_text() if team_links[1].select_one(".wf-title-med") else team_links[1].get_text())
            team2_id = _id_from_href(team_links[1].get("href"), "team")
            img = team_links[1].select_one("img")
            team2_logo = _abs_url(img.get("src") if img else None)

        event_name = event_id = event_stage = None
        event_a = soup.select_one("a.match-header-event")
        if event_a:
            raw = _clean(event_a.get_text(" ", strip=True))
            # often "Event Name Stage"
            event_name = raw.split("\n")[0].strip() if raw else None
            event_id = _id_from_href(event_a.get("href"), "event")
            # series/stage sibling
            series = soup.select_one("a.match-header-event-series")
            if series:
                event_stage = _clean(series.get_text(" ", strip=True))

        match_date = None
        ts = soup.select_one(".moment-tz-convert")
        if ts and ts.get("data-utc-ts"):
            match_date = ts.get("data-utc-ts")
        elif soup.select_one(".match-header-date"):
            match_date = _clean(soup.select_one(".match-header-date").get_text(" ", strip=True))

        scores = []
        for el in soup.select(".match-header-vs-score .js-spoiler, .match-header-vs-score"):
            digits = re.findall(r"\d+", el.get_text(" ", strip=True))
            if len(digits) >= 2:
                scores = digits[:2]
                break
        if not scores:
            digits = re.findall(r"\d+", _clean((soup.select_one(".match-header-vs-score") or Tag(name="div")).get_text(" ")))
            scores = digits[:2]

        note_el = soup.select_one(".match-header-note")
        note = _clean(note_el.get_text(" ", strip=True)) if note_el else None

        patch = None
        for el in soup.select(".match-header-vs-note, .match-header-note, .ge-text-light"):
            txt = _clean(el.get_text(" ", strip=True))
            m = re.search(r"Patch\s*([0-9.]+)", txt, flags=re.I)
            if m:
                patch = m.group(1)
                break

        return {
            "match_id": self.match_id,
            "event_id": event_id,
            "event_name": event_name,
            "event_stage": event_stage,
            "team1_id": team1_id,
            "team2_id": team2_id,
            "team1_name": team1_name,
            "team2_name": team2_name,
            "team1_logo": team1_logo,
            "team2_logo": team2_logo,
            "team1_score": _parse_int(scores[0]) if len(scores) > 0 else None,
            "team2_score": _parse_int(scores[1]) if len(scores) > 1 else None,
            "match_date": match_date,
            "patch": patch,
            "note": note,
            "url": f"https://www.vlr.gg/{self.match_id}",
            "best_of": None,
        }

    def extract_teams(self) -> list[dict[str, Any]]:
        match = self.extract_match_dimension()
        teams = []
        for side in ("1", "2"):
            tid = match.get(f"team{side}_id")
            name = match.get(f"team{side}_name")
            if tid or name:
                teams.append(
                    {
                        "id": tid,
                        "name": name,
                        "url": f"https://www.vlr.gg/team/{tid}" if tid else None,
                        "img": match.get(f"team{side}_logo"),
                        "country": None,
                    }
                )
        return teams

    def extract_match_maps(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for game in self.overview.select("div.vm-stats-game"):
            game_id = game.get("data-game-id")
            if not game_id or game_id == "all":
                continue
            map_el = game.select_one(".map")
            map_name = _map_name_from_game(game)

            teams = game.select(".vm-stats-game-header .team")
            team1_name = team2_name = None
            team1_rounds = team2_rounds = None
            if len(teams) >= 1:
                team1_name = _clean((teams[0].select_one(".team-name") or teams[0]).get_text(" ", strip=True))
                score = teams[0].select_one(".score")
                team1_rounds = _parse_int(_clean(score.get_text())) if score else None
            if len(teams) >= 2:
                team2_name = _clean((teams[1].select_one(".team-name") or teams[1]).get_text(" ", strip=True))
                score = teams[1].select_one(".score")
                team2_rounds = _parse_int(_clean(score.get_text())) if score else None

            pick_side = None
            if map_el and map_el.select_one(".picked.mod-1"):
                pick_side = 1
            elif map_el and map_el.select_one(".picked.mod-2"):
                pick_side = 2

            duration = None
            dur_el = game.select_one(".map-duration")
            if dur_el:
                duration = _clean(dur_el.get_text(" ", strip=True))

            rows.append(
                {
                    "match_id": self.match_id,
                    "map_game_id": game_id,
                    "map_number": len(rows) + 1,
                    "map_name": map_name,
                    "team1_name": team1_name,
                    "team2_name": team2_name,
                    "team1_rounds": team1_rounds,
                    "team2_rounds": team2_rounds,
                    "pick_side": pick_side,
                    "duration": duration,
                }
            )
        return rows

    def extract_overview_stats(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        overview_rows: list[dict[str, Any]] = []
        players_by_id: dict[str, dict[str, Any]] = {}
        agents_by_name: dict[str, dict[str, Any]] = {}

        for game in self.overview.select("div.vm-stats-game"):
            game_id = game.get("data-game-id") or "all"
            map_name = "all" if game_id == "all" else _map_name_from_game(game)

            for row in game.select(".ovw-table .ovw-row"):
                cells = [
                    c
                    for c in row.children
                    if getattr(c, "get", None) and "ovw-cell" in (c.get("class") or [])
                ]
                if not cells or "mod-player" not in (cells[0].get("class") or []):
                    continue

                player_cell = cells[0]
                player_a = player_cell.select_one("a")
                player_href = player_a.get("href") if player_a else None
                player_id = _id_from_href(player_href, "player")
                player_text = _clean(player_cell.get_text(" ", strip=True))
                # "something PRX" -> name + team tag
                parts = player_text.split()
                team_tag = parts[-1] if len(parts) >= 2 else None
                player_name = " ".join(parts[:-1]) if len(parts) >= 2 else player_text
                agent_img = player_cell.select_one("img")
                agent_name = _agent_from_img(agent_img)
                if agent_name:
                    agents_by_name[agent_name.lower()] = {
                        "name": agent_name,
                        "image_url": _abs_url(agent_img.get("src") if agent_img else None),
                    }
                if player_id:
                    players_by_id[player_id] = {
                        "id": player_id,
                        "name": player_name,
                        "url": urljoin("https://www.vlr.gg", player_href) if player_href else None,
                        "country": None,
                        "country_code": None,
                        "team_id": None,
                        "team_tag": team_tag,
                    }

                # Remaining cells: rating, acs, kda, +/-, kast, adr, hs, fk, fd, fkfd
                stat_cells = cells[1:]
                values: dict[str, Any] = {
                    "match_id": self.match_id,
                    "map_game_id": game_id,
                    "map_name": map_name,
                    "player_id": player_id,
                    "player_name": player_name,
                    "team_tag": team_tag,
                    "agent_name": agent_name,
                }

                # KDA cell detection
                mapped: list[tuple[str, str]] = []
                for cell in stat_cells:
                    txt = _clean(cell.get_text(" ", strip=True))
                    if "mod-kda" in (cell.get("class") or []) or "/" in txt:
                        # both / atk / def each as K D A
                        segments = [s.strip() for s in txt.split("/")]
                        for prefix, seg in zip(["both", "atk", "def"], segments):
                            kdap = seg.split()
                            if len(kdap) >= 3:
                                values[f"kills_{prefix}"] = _parse_int(kdap[0])
                                values[f"deaths_{prefix}"] = _parse_int(kdap[1])
                                values[f"assists_{prefix}"] = _parse_int(kdap[2])
                        values["kills"] = values.get("kills_both")
                        values["deaths"] = values.get("deaths_both")
                        values["assists"] = values.get("assists_both")
                        mapped.append(("kda", txt))
                        continue
                    mapped.append(("stat", txt))

                # Non-KDA stats in order
                non_kda = [t for kind, t in mapped if kind == "stat"]
                key_order = [k for k in OVERVIEW_STAT_KEYS if k not in {"kills", "deaths", "assists"}]
                for key, raw in zip(key_order, non_kda):
                    both, atk, def_ = _triple(raw)
                    if key in {"rating", "acs", "adr", "kast", "hs_pct"}:
                        values[key] = _parse_float(both)
                        values[f"{key}_atk"] = _parse_float(atk)
                        values[f"{key}_def"] = _parse_float(def_)
                    else:
                        values[key] = _parse_int(both) if both and re.search(r"\d", both) else _parse_float(both)
                        values[f"{key}_atk"] = _parse_int(atk) if atk and re.fullmatch(r"[+-]?\d+", atk or "") else _parse_float(atk)
                        values[f"{key}_def"] = _parse_int(def_) if def_ and re.fullmatch(r"[+-]?\d+", def_ or "") else _parse_float(def_)

                overview_rows.append(values)

        return overview_rows, list(players_by_id.values()), list(agents_by_name.values())

    def extract_rounds(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for game in self.overview.select("div.vm-stats-game"):
            game_id = game.get("data-game-id")
            if not game_id or game_id == "all":
                continue
            map_name = _map_name_from_game(game)

            for col in game.select(".vlr-rounds-row-col"):
                rnd = col.select_one(".rnd-num")
                if not rnd:
                    continue
                round_number = _parse_int(_clean(rnd.get_text()))
                title = col.get("title")  # score after round e.g. 4-1
                squares = col.select(".rnd-sq")
                winner_side = None
                win_type = None
                for idx, sq in enumerate(squares):
                    classes = sq.get("class") or []
                    if "mod-win" in classes:
                        winner_side = idx  # 0 team1, 1 team2
                        img = sq.select_one("img")
                        if img and img.get("src"):
                            win_type = Path(img["src"]).stem  # elim/boom/defuse/time
                        break
                rows.append(
                    {
                        "match_id": self.match_id,
                        "map_game_id": game_id,
                        "map_name": map_name,
                        "round_number": round_number,
                        "score_after": title,
                        "winner_side": winner_side,
                        "win_type": win_type,
                    }
                )
        return rows

    def extract_performance(self) -> list[dict[str, Any]]:
        """
        Performance tab: pairwise kill matrices and multi-kill / clutch tables.

        We flatten each table into long rows: match_id, table_index, row_player, col_player, value_raw.
        """
        if not self.performance:
            return []
        rows: list[dict[str, Any]] = []
        # Map sections often wrapped; associate nearest map heading if present.
        current_map = None
        for el in self.performance.select("div.vm-stats-game, table.wf-table-inset, table"):
            if isinstance(el, Tag) and "vm-stats-game" in (el.get("class") or []):
                game_id = el.get("data-game-id")
                if game_id == "all":
                    current_map = "all"
                else:
                    current_map = _map_name_from_game(el)
                continue
            if el.name != "table":
                continue
            table_rows = el.select("tr")
            if len(table_rows) < 2:
                continue
            headers = [_clean(c.get_text(" ", strip=True)) for c in table_rows[0].find_all(["th", "td"])]
            for tr in table_rows[1:]:
                cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
                if not cells:
                    continue
                row_player = cells[0]
                for col_idx, value in enumerate(cells[1:], start=1):
                    col_player = headers[col_idx] if col_idx < len(headers) else f"col_{col_idx}"
                    rows.append(
                        {
                            "match_id": self.match_id,
                            "map_name": current_map,
                            "row_player": row_player,
                            "col_player": col_player,
                            "value_raw": value,
                        }
                    )
        return rows

    def extract_economy(self) -> list[dict[str, Any]]:
        if not self.economy:
            return []
        rows: list[dict[str, Any]] = []
        current_map = None
        for el in self.economy.select("div.vm-stats-game, table"):
            if isinstance(el, Tag) and "vm-stats-game" in (el.get("class") or []):
                game_id = el.get("data-game-id")
                if game_id == "all":
                    current_map = "all"
                else:
                    current_map = _map_name_from_game(el)
                continue
            if el.name != "table":
                continue
            table_rows = el.select("tr")
            if len(table_rows) < 2:
                continue
            headers = [_clean(c.get_text(" ", strip=True)) for c in table_rows[0].find_all(["th", "td"])]
            # Team economy summary tables have headers like Pistol Won, Eco (won), ...
            if any("Pistol" in h or "Eco" in h or "$$$" in h for h in headers):
                for tr in table_rows[1:]:
                    cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
                    if not cells:
                        continue
                    row: dict[str, Any] = {
                        "match_id": self.match_id,
                        "map_name": current_map,
                        "team_name": cells[0],
                        "row_type": "team_economy_summary",
                    }
                    for h, v in zip(headers[1:], cells[1:]):
                        key = re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_")
                        # values like "4 (2)"
                        m = re.match(r"(\d+)\s*\((\d+)\)", v)
                        if m:
                            row[key] = _parse_int(m.group(1))
                            row[f"{key}_won"] = _parse_int(m.group(2))
                        else:
                            row[key] = v
                    rows.append(row)
            else:
                # Round bank / buy type timeline — store as raw rows
                for tr in table_rows:
                    cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
                    if not cells:
                        continue
                    rows.append(
                        {
                            "match_id": self.match_id,
                            "map_name": current_map,
                            "row_type": "economy_timeline",
                            "raw_cells": " || ".join(cells),
                        }
                    )
        return rows
