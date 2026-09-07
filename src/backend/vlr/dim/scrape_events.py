"""Parse vlr.gg event list/detail HTML so historical extract can use the AWS IP rotator."""

from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from backend.api_connectors.vlr_connector import SITE_BASE

logger = logging.getLogger(__name__)

_EVENT_HREF = re.compile(r"/event/(\d+)")
_TEAM_HREF = re.compile(r"/team/(\d+)")
_PLAYER_HREF = re.compile(r"/player/(\d+)")


def _text(el: Tag | None) -> str:
    """Strip nested labels so prize/date cells stay clean."""
    return el.get_text(" ", strip=True) if el else ""


def _abs_url(src: str | None) -> str:
    """Turn //cdn or /img paths into absolute URLs for logo_url."""
    if not src:
        return ""
    src = src.strip()
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return f"{SITE_BASE}{src}"
    return src


def _id_from_href(href: str | None, pattern: re.Pattern[str]) -> str:
    """Pull the numeric vlr id from an event/team/player href."""
    if not href:
        return ""
    match = pattern.search(href)
    return match.group(1) if match else ""


def _flag_region(el: Tag | None) -> str | None:
    """Read `flag mod-kr` into a local region hint for split_event_region."""
    if not el:
        return None
    for part in el.get("class") or []:
        if part.startswith("mod-") and part not in {"mod-location", "mod-large"}:
            return part[4:]
    return None


def _parse_event_cards(container: Tag, status: str) -> list[dict[str, Any]]:
    """One `a.event-item` card → listing row used by format_dim_event_row."""
    rows: list[dict[str, Any]] = []
    for item in container.select("a.event-item"):
        href = item.get("href") or ""
        event_id = _id_from_href(href, _EVENT_HREF)
        if not event_id:
            continue
        title = _text(item.select_one(".event-item-title"))
        prize = _text(item.select_one(".event-item-desc-item.mod-prize"))
        dates = _text(item.select_one(".event-item-desc-item.mod-dates"))
        status_text = _text(item.select_one(".event-item-desc-item-status")) or status
        img = item.select_one(".event-item-thumb img")
        thumb = _abs_url(img.get("src") if img else None)
        region = _flag_region(item.select_one(".event-item-desc-item.mod-location .flag"))
        url = href if href.startswith("http") else f"{SITE_BASE}{href}"
        rows.append(
            {
                "id": event_id,
                "event_id": event_id,
                "title": title,
                "name": title,
                "status": status_text.lower() or status,
                "prize": prize,
                "dates": dates,
                "region": region,
                "img": thumb,
                "url_path": url,
                "url": url,
            }
        )
    return rows


def parse_events_list_html(html: str, *, status: str) -> list[dict[str, Any]]:
    """Split the events index into upcoming or completed cards."""
    soup = BeautifulSoup(html, "html.parser")
    label = "mod-completed" if status == "completed" else "mod-upcoming"
    rows: list[dict[str, Any]] = []
    for section in soup.select(f"div.wf-label.mod-large.{label}"):
        parent = section.parent
        if parent:
            rows.extend(_parse_event_cards(parent, status))
    return rows


def parse_live_events_html(html: str) -> list[dict[str, Any]]:
    """Live events live on the homepage sidebar, not the completed pager."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    container = soup.select_one("div.js-home-events")
    if not container:
        return rows
    for header in container.select("h1.wf-label.mod-sidebar"):
        if "live" not in header.get_text(" ", strip=True).lower():
            continue
        wrapper = header.parent
        if not wrapper:
            continue
        for item in wrapper.select("a.event-item"):
            href = item.get("href") or ""
            event_id = _id_from_href(href, _EVENT_HREF)
            if not event_id:
                continue
            title = _text(item.select_one(".event-item-name")) or _text(item.select_one(".event-item-title"))
            img = item.select_one("img.event-item-icon") or item.select_one("img")
            tags = item.select("div.event-item-tag")
            region = _text(tags[0]) if tags else None
            url = href if href.startswith("http") else f"{SITE_BASE}{href}"
            rows.append(
                {
                    "id": event_id,
                    "event_id": event_id,
                    "title": title,
                    "name": title,
                    "status": "live",
                    "region": region,
                    "img": _abs_url(img.get("src") if img else None),
                    "url_path": url,
                    "url": url,
                }
            )
    return rows


def _parse_header(soup: BeautifulSoup) -> dict[str, Any]:
    """Event header (new or legacy VLR layout) → detail['event']."""
    header = soup.select_one(".event-header") or soup.select_one(".wf-card")
    out = {
        "name": "",
        "series": "",
        "subtitle": "",
        "dates": "",
        "prize": "",
        "location": "",
        "logo": "",
    }
    if not header:
        return out
    logo = header.select_one(".event-header-thumb img") or header.select_one("img")
    if logo:
        out["logo"] = _abs_url(logo.get("src"))
    main = header.select_one(".event-header-main")
    if main:
        series_link = main.select_one(".event-header-main-bc a")
        out["series"] = _text(series_link)
        out["name"] = _text(main.select_one("h1.event-header-main-title"))
        out["subtitle"] = _text(main.select_one("h2.event-header-main-desc"))
        meta = main.select_one(".event-header-main-meta")
        if meta:
            for child in meta.find_all("div", recursive=False):
                label = _text(child.select_one(".label")).rstrip(":").lower()
                value = _text(child.select_one(".value"))
                if label == "dates":
                    out["dates"] = value
                elif label == "prize":
                    out["prize"] = value
                elif label in {"location", "venue"}:
                    out["location"] = value
        return out
    desc = header.select_one(".event-desc-inner")
    if desc:
        out["series"] = _text(desc.select_one("a"))
    out["name"] = _text(header.select_one("h1.wf-title"))
    out["subtitle"] = _text(header.select_one(".event-desc-subtitle"))
    for item in header.select(".event-desc-item"):
        label = _text(item.select_one(".event-desc-item-label")).rstrip(":").lower()
        value = _text(item.select_one(".event-desc-item-value"))
        if label == "dates":
            out["dates"] = value
        elif label == "prize":
            out["prize"] = value
        elif label in {"location", "venue"}:
            out["location"] = value
    return out


def _parse_prizes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Prize table rows for prizes_json."""
    prizes: list[dict[str, Any]] = []
    prize_card = soup.select_one(".wf-card.mod-dark")
    if not prize_card:
        return prizes
    ptable = prize_card.select_one(".wf-ptable")
    if not ptable:
        return prizes
    rows = ptable.select(".row")
    for row in rows[1:]:
        cells = row.select(".cell")
        if len(cells) < 3:
            continue
        team_link = cells[2].select_one("a")
        team_id = _id_from_href(team_link.get("href") if team_link else None, _TEAM_HREF)
        team_name = _text(team_link.select_one(".text-of")) if team_link else ""
        region_el = team_link.select_one(".ge-text-light") if team_link else None
        team_region = _text(region_el)
        if team_region and team_name.endswith(team_region):
            team_name = team_name[: -len(team_region)].strip()
        img = team_link.select_one("img") if team_link else None
        prizes.append(
            {
                "placement": _text(cells[0]),
                "amount": _text(cells[1]),
                "team": {
                    "id": team_id,
                    "name": team_name or _text(team_link),
                    "logo": _abs_url(img.get("src") if img else None),
                    "region": team_region,
                },
            }
        )
    return prizes


def _parse_teams(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Participating team cards for teams_json."""
    teams: list[dict[str, Any]] = []
    for card in soup.select(".wf-card.event-team"):
        name_link = card.select_one(".event-team-name")
        players: list[dict[str, Any]] = []
        for player_link in card.select(".event-team-players-item"):
            players.append(
                {
                    "id": _id_from_href(player_link.get("href"), _PLAYER_HREF),
                    "name": _text(player_link),
                    "flag": _flag_region(player_link.select_one(".flag")) or "",
                }
            )
        note_link = card.select_one(".event-team-note a")
        teams.append(
            {
                "id": _id_from_href(name_link.get("href") if name_link else None, _TEAM_HREF),
                "name": _text(name_link),
                "players": players,
                "qualification": _text(note_link),
            }
        )
    return teams


def _parse_standings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Group tables except the dark prize card."""
    standings: list[dict[str, Any]] = []
    for card in soup.select(".wf-card"):
        classes = card.get("class") or []
        if "mod-dark" in classes:
            continue
        ptable = card.select_one(".wf-ptable")
        if not ptable:
            continue
        header_row = ptable.select_one(".row")
        if not header_row:
            continue
        headers = [_text(cell) for cell in header_row.select(".cell")]
        if not headers:
            continue
        rows: list[dict[str, str]] = []
        for row in ptable.select(".row")[1:]:
            cells = row.select(".cell")
            row_data: dict[str, str] = {}
            for idx, cell in enumerate(cells):
                label = headers[idx] if idx < len(headers) else str(idx)
                link = cell.select_one("a")
                row_data[label] = _text(link) if link and idx == 0 else _text(cell)
            if row_data:
                rows.append(row_data)
        standings.append(
            {
                "stage": _text(card.select_one(".wf-label") or card.select_one("h2")),
                "columns": headers,
                "rows": rows,
            }
        )
    return standings


def parse_event_detail_html(html: str) -> dict[str, Any]:
    """Match the vlrggapi /v2/event/{id} `segments` shape for format_dim_event_row."""
    soup = BeautifulSoup(html, "html.parser")
    return {
        "event": _parse_header(soup),
        "prizes": _parse_prizes(soup),
        "teams": _parse_teams(soup),
        "standings": _parse_standings(soup),
    }
