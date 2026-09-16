"""Valorant Fandom MediaWiki API via AWS IP rotator (weapon Infobox + TTK tables)."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from backend.api_connectors.rotating_http import rotating_session

logger = logging.getLogger(__name__)

BASE_URL = "https://valorant.fandom.com/api.php"
SITE = "https://valorant.fandom.com"
USER_AGENT = "Valorant-Stats/1.0 (esports warehouse catalog; gzip MediaWiki API)"


class ValorantFandomConnector:
    """Fetch weapon wikitext and file URLs through AWS so Fandom never sees the host IP."""

    def __init__(
        self,
        timeout: int = 30,
        max_workers: int | None = None,
        interval_sec: float | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_workers = max_workers or int(os.getenv("VLR_FANDOM_WORKERS", "3"))
        self.interval_sec = (
            interval_sec
            if interval_sec is not None
            else float(os.getenv("VLR_FANDOM_INTERVAL_SEC", "0.4"))
        )
        self._gate = threading.Lock()
        self._last_start = 0.0
        self.session = rotating_session(
            SITE,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
        )

    def _wait_turn(self) -> None:
        """Pace GETs so Fandom does not 429 the catalog run."""
        with self._gate:
            wait = self.interval_sec - (time.monotonic() - self._last_start)
            if wait > 0:
                time.sleep(wait)
            self._last_start = time.monotonic()

    def _get_json(self, params: dict[str, str], label: str) -> dict[str, Any]:
        """One MediaWiki GET through AWS with 429 retry."""
        for attempt in range(1, 6):
            self._wait_turn()
            logger.info("[fandom] GET %s attempt=%s via_rotator=1", label, attempt)
            resp = self.session.get(BASE_URL, params=params, timeout=self.timeout)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After") or min(30, 10 * attempt))
                logger.warning("[fandom] 429 %s sleep=%ss attempt=%s", label, wait, attempt)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"Fandom {label} did not return JSON object")
            return payload
        raise RuntimeError(f"Fandom gave up {label} after 429s")

    def get_page_wikitext(self, title: str) -> str | None:
        """One weapon (or list) page as wikitext."""
        payload = self._get_json(
            {"action": "parse", "page": title, "prop": "wikitext", "format": "json"},
            f"parse page={title}",
        )
        if payload.get("error"):
            logger.warning("[fandom] Parse miss page=%s err=%s", title, payload["error"].get("code"))
            return None
        wikitext = ((payload.get("parse") or {}).get("wikitext") or {}).get("*")
        if not wikitext:
            logger.warning("[fandom] Empty wikitext page=%s", title)
            return None
        return str(wikitext)

    def get_pages_wikitext(self, titles: list[str]) -> dict[str, str]:
        """Fetch weapon pages in parallel; Fandom is lighter than Liquipedia."""
        out: dict[str, str] = {}
        if not titles:
            return out
        logger.info(
            "[fandom] Fetch pages=%s workers=%s interval=%s via_rotator=1",
            len(titles),
            self.max_workers,
            self.interval_sec,
        )
        workers = max(1, self.max_workers)
        if workers <= 1:
            for done, title in enumerate(titles, start=1):
                try:
                    text = self.get_page_wikitext(title)
                except Exception:
                    logger.exception("[fandom] Failed page=%s", title)
                    text = None
                if text:
                    out[title] = text
                if done % 5 == 0 or done == len(titles):
                    logger.info("[fandom] Progress %s/%s ok=%s", done, len(titles), len(out))
            logger.info("[fandom] Done pages=%s ok=%s", len(titles), len(out))
            return out
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.get_page_wikitext, title): title for title in titles}
            done = 0
            for future in as_completed(futures):
                title = futures[future]
                try:
                    text = future.result()
                except Exception:
                    logger.exception("[fandom] Failed page=%s", title)
                    text = None
                if text:
                    out[title] = text
                done += 1
                if done % 5 == 0 or done == len(titles):
                    logger.info("[fandom] Progress %s/%s ok=%s", done, len(titles), len(out))
        logger.info("[fandom] Done pages=%s ok=%s", len(titles), len(out))
        return out

    def get_file_urls(self, file_names: list[str]) -> dict[str, str]:
        """Resolve File: titles to static.wikia.nocookie.net URLs (batched)."""
        out: dict[str, str] = {}
        titles: list[str] = []
        seen: set[str] = set()
        for name in file_names:
            clean = (name or "").strip()
            if not clean:
                continue
            if not clean.lower().startswith("file:"):
                clean = f"File:{clean}"
            key = clean.replace("_", " ")
            if key.lower() in seen:
                continue
            seen.add(key.lower())
            titles.append(key)
        if not titles:
            return out
        logger.info("[fandom] Resolve files=%s via_rotator=1", len(titles))
        for start in range(0, len(titles), 40):
            chunk = titles[start : start + 40]
            payload = self._get_json(
                {
                    "action": "query",
                    "titles": "|".join(chunk),
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "format": "json",
                },
                f"imageinfo n={len(chunk)}",
            )
            pages = ((payload.get("query") or {}).get("pages") or {})
            if not isinstance(pages, dict):
                continue
            for page in pages.values():
                if not isinstance(page, dict):
                    continue
                title = str(page.get("title") or "")
                info = page.get("imageinfo") or []
                url = info[0].get("url") if info and isinstance(info[0], dict) else None
                if title and url:
                    out[title.replace("_", " ")] = str(url)
                    out[title.split(":", 1)[-1].replace("_", " ")] = str(url)
        logger.info("[fandom] File URLs resolved=%s", len(out))
        return out
