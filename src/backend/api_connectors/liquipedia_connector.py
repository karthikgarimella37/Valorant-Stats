"""Liquipedia Valorant MediaWiki API — ability costs live in AbilityCard wikitext."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://liquipedia.net/valorant/api.php"
USER_AGENT = "Valorant-Stats/1.0 (esports warehouse catalog; gzip MediaWiki API)"


class LiquipediaValorantConnector:
    """Fetch agent wikitext so we can parse credit costs and ult orbs (not on valorant-api.com)."""

    def __init__(
        self,
        timeout: int = 30,
        max_workers: int | None = None,
        interval_sec: float | None = None,
    ) -> None:
        self.timeout = timeout
        # Serial by default: Liquipedia 429s when several parse calls overlap.
        self.max_workers = max_workers or int(os.getenv("VLR_LIQUIPEDIA_WORKERS", "1"))
        self.interval_sec = (
            interval_sec
            if interval_sec is not None
            else float(os.getenv("VLR_LIQUIPEDIA_INTERVAL_SEC", "1.1"))
        )
        self._gate = threading.Lock()
        self._last_start = 0.0
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.8, status_forcelist=(500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            }
        )

    def _wait_turn(self) -> None:
        """Keep ~1 GET/sec so Liquipedia does not 429 the catalog run."""
        with self._gate:
            wait = self.interval_sec - (time.monotonic() - self._last_start)
            if wait > 0:
                time.sleep(wait)
            self._last_start = time.monotonic()

    def get_page_wikitext(self, title: str) -> str | None:
        """One agent page as wikitext (Infobox + AbilityCard)."""
        for attempt in range(1, 6):
            self._wait_turn()
            logger.info("[liquipedia] GET parse page=%s attempt=%s", title, attempt)
            resp = self.session.get(
                BASE_URL,
                params={"action": "parse", "page": title, "prop": "wikitext", "format": "json"},
                timeout=self.timeout,
            )
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After") or min(30, 10 * attempt))
                logger.warning("[liquipedia] 429 page=%s sleep=%ss attempt=%s", title, wait, attempt)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("error"):
                logger.warning(
                    "[liquipedia] Parse miss page=%s err=%s",
                    title,
                    payload["error"].get("code"),
                )
                return None
            wikitext = ((payload.get("parse") or {}).get("wikitext") or {}).get("*")
            if not wikitext:
                logger.warning("[liquipedia] Empty wikitext page=%s", title)
                return None
            return str(wikitext)
        logger.warning("[liquipedia] Gave up page=%s after 429s", title)
        return None

    def get_pages_wikitext(self, titles: list[str]) -> dict[str, str]:
        """Fetch agent pages. Serial unless VLR_LIQUIPEDIA_WORKERS > 1."""
        out: dict[str, str] = {}
        if not titles:
            return out
        logger.info("[liquipedia] Fetch pages=%s workers=%s interval=%s", len(titles), self.max_workers, self.interval_sec)
        if self.max_workers <= 1:
            for done, title in enumerate(titles, start=1):
                try:
                    text = self.get_page_wikitext(title)
                except Exception:
                    logger.exception("[liquipedia] Failed page=%s", title)
                    text = None
                if text:
                    out[title] = text
                if done % 10 == 0 or done == len(titles):
                    logger.info("[liquipedia] Progress %s/%s ok=%s", done, len(titles), len(out))
            logger.info("[liquipedia] Done pages=%s ok=%s", len(titles), len(out))
            return out
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self.get_page_wikitext, title): title for title in titles}
            done = 0
            for future in as_completed(futures):
                title = futures[future]
                try:
                    text = future.result()
                except Exception:
                    logger.exception("[liquipedia] Failed page=%s", title)
                    text = None
                if text:
                    out[title] = text
                done += 1
                if done % 10 == 0 or done == len(titles):
                    logger.info("[liquipedia] Progress %s/%s ok=%s", done, len(titles), len(out))
        logger.info("[liquipedia] Done pages=%s ok=%s", len(titles), len(out))
        return out
