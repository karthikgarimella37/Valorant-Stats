"""Liquipedia Valorant MediaWiki API — ability costs live in AbilityCard wikitext."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://liquipedia.net/valorant/api.php"
USER_AGENT = "Valorant-Stats/1.0 (esports warehouse catalog; gzip MediaWiki API)"


class LiquipediaValorantConnector:
    """Fetch agent wikitext so we can parse credit costs and ult orbs (not on valorant-api.com)."""

    def __init__(self, timeout: int = 30, max_workers: int = 6) -> None:
        self.timeout = timeout
        self.max_workers = max_workers
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.8, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            }
        )

    def get_page_wikitext(self, title: str) -> str | None:
        """One agent page as wikitext (Infobox + AbilityCard)."""
        logger.info("[liquipedia] GET parse page=%s", title)
        resp = self.session.get(
            BASE_URL,
            params={"action": "parse", "page": title, "prop": "wikitext", "format": "json"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("error"):
            logger.warning("[liquipedia] Parse miss page=%s err=%s", title, payload["error"].get("code"))
            return None
        wikitext = ((payload.get("parse") or {}).get("wikitext") or {}).get("*")
        if not wikitext:
            logger.warning("[liquipedia] Empty wikitext page=%s", title)
            return None
        return str(wikitext)

    def get_pages_wikitext(self, titles: list[str]) -> dict[str, str]:
        """Parallel page fetches — each agent page is independent I/O."""
        out: dict[str, str] = {}
        if not titles:
            return out
        logger.info("[liquipedia] Fetch pages=%s workers=%s", len(titles), self.max_workers)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self.get_page_wikitext, title): title for title in titles}
            done = 0
            for future in as_completed(futures):
                title = futures[future]
                try:
                    text = future.result()
                except Exception:
                    logger.exception("[liquipedia] Failed page=%s", title)
                    raise
                if text:
                    out[title] = text
                done += 1
                if done % 10 == 0 or done == len(titles):
                    logger.info("[liquipedia] Progress %s/%s", done, len(titles))
        logger.info("[liquipedia] Done pages=%s ok=%s", len(titles), len(out))
        return out
