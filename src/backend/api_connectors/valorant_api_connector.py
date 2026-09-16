"""HTTP client for valorant-api.com (Riot game-data mirror). Static catalogs only."""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://valorant-api.com"


class ValorantApiConnector:
    """Fetch playable-agent kit data (abilities, portraits, role). Not used for matches."""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.headers.update({"Accept": "application/json"})

    def get_playable_agents(self) -> list[dict[str, Any]]:
        """One GET for every playable agent so dim_agents can upsert the full roster."""
        url = f"{BASE_URL}/v1/agents"
        logger.info("[valorant-api] GET %s isPlayableCharacter=true", url)
        resp = self.session.get(
            url, params={"isPlayableCharacter": "true"}, timeout=self.timeout
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("valorant-api.com /v1/agents did not return data[]")
        playable = [
            row
            for row in rows
            if isinstance(row, dict) and row.get("isPlayableCharacter", True)
        ]
        logger.info("[valorant-api] Agents fetched=%s", len(playable))
        return playable
