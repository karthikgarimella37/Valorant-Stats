"""
AWS API Gateway IP rotation via requests-ip-rotator.

Credentials (never commit):
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  or VLR_AWS_ACCESS_KEY_ID / VLR_AWS_SECRET_ACCESS_KEY

Enable with:
  VLR_USE_IP_ROTATOR=1
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import Any

from backend.config.env import load_project_env

logger = logging.getLogger(__name__)

load_project_env()


def ip_rotator_enabled() -> bool:
    """Off unless VLR_USE_IP_ROTATOR=1. AWS API Gateway is paid; do not auto-enable."""
    flag = os.getenv("VLR_USE_IP_ROTATOR", "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def assert_container_rotator() -> int:
    """Fail the extract if vlrggapi is not sending www.vlr.gg through AWS IPs."""
    flag = os.getenv("VLR_REQUIRE_ROTATOR", "1").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        logger.warning("[rotator] Check skipped (VLR_REQUIRE_ROTATOR=%s)", flag)
        return 0
    import re
    import subprocess

    try:
        proc = subprocess.run(
            ["docker", "logs", "vlrggapi"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "docker is not available. Start the rotator overlay with: "
            "docker compose up -d --build vlrggapi"
        ) from exc
    text = f"{proc.stdout or ''}{proc.stderr or ''}"
    found = re.findall(r"Ready endpoints=(\d+)", text)
    if not found:
        raise RuntimeError(
            "vlrggapi AWS rotator is not running. Rebuild the overlay image: "
            "docker compose up -d --build vlrggapi. "
            "Logs must show [vlrggapi_rotator] Ready endpoints=N with N>0. "
            "Do not scrape vlr.gg from the host IP."
        )
    count = int(found[-1])
    if count < 1:
        raise RuntimeError(
            "vlrggapi rotator created 0 AWS endpoints. Check IAM "
            "(CreateRestApi/GetRestApis) and set VLR_IP_ROTATOR_REGIONS=us-east-1. "
            "Do not scrape vlr.gg from the host IP."
        )
    logger.info("[rotator] vlrggapi AWS endpoints=%s", count)
    return count


def _access_key_id() -> str | None:
    return os.getenv("VLR_AWS_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID") or None


def _access_key_secret() -> str | None:
    return os.getenv("VLR_AWS_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or None


def _regions() -> list[str] | None:
    raw = os.getenv("VLR_IP_ROTATOR_REGIONS", "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    default = os.getenv("AWS_DEFAULT_REGION", "").strip()
    if default:
        return [default]
    return None


class VlrIpRotator:
    """
    Process-wide ApiGateway for a single site (default https://www.vlr.gg).

    Thread-safe start/shutdown. Sessions should mount the returned gateway
    with the exact site prefix, e.g. session.mount("https://www.vlr.gg", gateway).
    """

    _lock = threading.Lock()
    _gateways: dict[str, Any] = {}
    _atexit_registered = False

    @classmethod
    def get_gateway(cls, site: str) -> Any | None:
        if not ip_rotator_enabled():
            return None
        site = site.rstrip("/")
        with cls._lock:
            if site in cls._gateways:
                return cls._gateways[site]
            gateway = cls._start_unlocked(site)
            cls._gateways[site] = gateway
            if not cls._atexit_registered:
                atexit.register(cls.shutdown_all)
                cls._atexit_registered = True
            return gateway

    @classmethod
    def _start_unlocked(cls, site: str) -> Any:
        try:
            from requests_ip_rotator import ApiGateway
        except ImportError as exc:
            raise RuntimeError(
                "requests-ip-rotator is not installed. "
                "Run: uv add requests-ip-rotator (root + dagster_orchestration)"
            ) from exc

        access_key_id = _access_key_id()
        access_key_secret = _access_key_secret()
        if not access_key_id or not access_key_secret:
            raise RuntimeError(
                "VLR_USE_IP_ROTATOR is on but AWS keys are missing. "
                "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env "
                "(or VLR_AWS_ACCESS_KEY_ID / VLR_AWS_SECRET_ACCESS_KEY)."
            )

        kwargs: dict[str, Any] = {
            "access_key_id": access_key_id,
            "access_key_secret": access_key_secret,
            "verbose": os.getenv("VLR_IP_ROTATOR_VERBOSE", "1") not in ("0", "false", "False"),
        }
        regions = _regions()
        if regions:
            kwargs["regions"] = regions

        logger.info("Starting AWS ApiGateway IP rotator for %s regions=%s", site, regions or "DEFAULT")
        gateway = ApiGateway(site, **kwargs)
        endpoints = gateway.start()
        count = len(endpoints) if endpoints is not None else 0
        logger.info(
            "IP rotator ready for %s (%s endpoint(s)). Remember gateway.shutdown() / atexit.",
            site,
            count,
        )
        if count == 0:
            raise RuntimeError(
                "AWS IP rotator created 0 API Gateway endpoints. "
                "UnrecognizedClientException means the key is invalid or the region is not enabled. "
                "IAM needs apigateway CreateRestApi / GetRestApis in that region. "
                "Set VLR_IP_ROTATOR_REGIONS (or AWS_DEFAULT_REGION) to one enabled region, e.g. us-east-1."
            )
        return gateway

    @classmethod
    def mount(cls, session: Any, site: str) -> bool:
        """Mount rotator on session if enabled. Returns True when mounted."""
        gateway = cls.get_gateway(site)
        if gateway is None:
            return False
        # Prefix must match ApiGateway(site=...) exactly.
        session.mount(site.rstrip("/"), gateway)
        return True

    @classmethod
    def shutdown_all(cls) -> None:
        with cls._lock:
            items = list(cls._gateways.items())
            cls._gateways.clear()
        for site, gateway in items:
            try:
                logger.info("Shutting down IP rotator for %s", site)
                gateway.shutdown()
            except Exception:
                logger.exception("Failed shutting down IP rotator for %s", site)

    @classmethod
    def shutdown(cls, site: str) -> None:
        site = site.rstrip("/")
        with cls._lock:
            gateway = cls._gateways.pop(site, None)
        if gateway is not None:
            try:
                gateway.shutdown()
            except Exception:
                logger.exception("Failed shutting down IP rotator for %s", site)
