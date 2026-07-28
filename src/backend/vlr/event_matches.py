"""Scrape VLR event match schedule pages."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MATCH_HREF_RE = re.compile(r"^/(\d{4,})(?:/[^?]*)?(?:\?.*)?$")


def parse_event_matches_html(html: str, *, event_id: str | int) -> list[dict[str, Any]]:
    """
    Parse https://www.vlr.gg/event/matches/{event_id}/ into match queue rows.
    """
    soup = BeautifulSoup(html, "html.parser")
    event_id_str = str(event_id)
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Prefer dedicated match cards when present.
    cards = soup.select("a.match-item, a.wf-module-item.match-item, a.wf-module-item")
    for card in cards:
        href = card.get("href") or ""
        m = MATCH_HREF_RE.match(href)
        if not m:
            continue
        match_id = m.group(1)
        if match_id in seen:
            continue
        seen.add(match_id)

        teams = [t.get_text(" ", strip=True) for t in card.select(".match-item-vs-team-name")]
        scores = [s.get_text(" ", strip=True) for s in card.select(".match-item-vs-team-score")]
        status_el = card.select_one(".ml-status, .match-item-event-series, .match-item-eta")
        event_stage = None
        stage_el = card.select_one(".match-item-event-series")
        if stage_el:
            event_stage = stage_el.get_text(" ", strip=True)
        date_el = card.select_one(".match-item-time, .moment-tz-convert")
        match_date = None
        if date_el:
            match_date = date_el.get("data-utc-ts") or date_el.get_text(" ", strip=True)

        matches.append(
            {
                "event_id": event_id_str,
                "match_id": match_id,
                "url": urljoin("https://www.vlr.gg", href),
                "team1_name": teams[0] if len(teams) > 0 else None,
                "team2_name": teams[1] if len(teams) > 1 else None,
                "team1_score": scores[0] if len(scores) > 0 else None,
                "team2_score": scores[1] if len(scores) > 1 else None,
                "event_stage": event_stage,
                "status": status_el.get_text(" ", strip=True) if status_el else None,
                "match_date": match_date,
            }
        )

    # Fallback: any numeric match links on the page.
    if not matches:
        for a in soup.find_all("a", href=True):
            m = MATCH_HREF_RE.match(a["href"])
            if not m:
                continue
            match_id = m.group(1)
            if match_id in seen:
                continue
            seen.add(match_id)
            matches.append(
                {
                    "event_id": event_id_str,
                    "match_id": match_id,
                    "url": urljoin("https://www.vlr.gg", a["href"]),
                    "team1_name": None,
                    "team2_name": None,
                    "team1_score": None,
                    "team2_score": None,
                    "event_stage": None,
                    "status": None,
                    "match_date": None,
                }
            )

    logger.info("Event %s: parsed %s match links", event_id_str, len(matches))
    return matches
