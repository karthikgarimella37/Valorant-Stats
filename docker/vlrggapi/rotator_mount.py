"""Route vlrggapi's httpx client through AWS API Gateway so scrapes leave from AWS IPs."""

from __future__ import annotations

import atexit
import logging
import os
import random
from ipaddress import IPv4Address

import httpx

logger = logging.getLogger(__name__)

VLR_SITE = "https://www.vlr.gg"
_MAX_IPV4 = (1 << 32) - 1
_gateway = None
_endpoints: list[str] = []


def _enabled() -> bool:
    flag = os.getenv("VLR_USE_IP_ROTATOR", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return bool(os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("VLR_AWS_ACCESS_KEY_ID"))


def _regions() -> list[str] | None:
    raw = os.getenv("VLR_IP_ROTATOR_REGIONS", "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    default = os.getenv("AWS_DEFAULT_REGION", "").strip()
    return [default] if default else None


class VlrGatewayTransport(httpx.AsyncHTTPTransport):
    """Rewrite www.vlr.gg URLs onto a random API Gateway endpoint (same as requests-ip-rotator)."""

    def __init__(self, endpoints: list[str], **kwargs):
        super().__init__(**kwargs)
        self.endpoints = endpoints

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        endpoint = random.choice(self.endpoints)
        raw_path = request.url.raw_path.decode()
        new_url = httpx.URL(f"https://{endpoint}/ProxyStage{raw_path}")
        headers = request.headers.copy()
        headers["host"] = endpoint
        headers.pop("x-forwarded-for", None)
        headers["x-my-x-forwarded-for"] = str(IPv4Address(random.randint(0, _MAX_IPV4)))
        forwarded = httpx.Request(
            request.method,
            new_url,
            headers=headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        return await super().handle_async_request(forwarded)


def start_gateway() -> list[str]:
    """Create API Gateway proxies at container boot. Fail if AWS returns no endpoints."""
    global _gateway, _endpoints
    if _endpoints:
        return _endpoints
    if not _enabled():
        logger.info("[vlrggapi_rotator] Off — scrapes use the container IP")
        return []
    access_key_id = os.getenv("VLR_AWS_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
    access_key_secret = os.getenv("VLR_AWS_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
    if not access_key_id or not access_key_secret:
        raise RuntimeError(
            "VLR_USE_IP_ROTATOR is on but AWS keys are missing in the vlrggapi container. "
            "Pass AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY via compose env_file."
        )
    from requests_ip_rotator import ApiGateway

    kwargs: dict = {
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "verbose": os.getenv("VLR_IP_ROTATOR_VERBOSE", "1") not in ("0", "false", "False"),
    }
    regions = _regions()
    if regions:
        kwargs["regions"] = regions
    logger.info("[vlrggapi_rotator] Starting API Gateway for %s regions=%s", VLR_SITE, regions or "DEFAULT")
    _gateway = ApiGateway(VLR_SITE, **kwargs)
    _endpoints = list(_gateway.start() or [])
    atexit.register(_shutdown)
    logger.info("[vlrggapi_rotator] Ready endpoints=%s", len(_endpoints))
    if not _endpoints:
        raise RuntimeError(
            "AWS IP rotator created 0 API Gateway endpoints inside vlrggapi. "
            "Keys may be invalid, or the region is not enabled. "
            "IAM needs apigateway CreateRestApi / GetRestApis. "
            "Set VLR_IP_ROTATOR_REGIONS or AWS_DEFAULT_REGION to one enabled region."
        )
    return _endpoints


def _shutdown() -> None:
    global _gateway, _endpoints
    if _gateway is None:
        return
    try:
        _gateway.shutdown()
    except Exception:
        logger.exception("[vlrggapi_rotator] Shutdown failed")
    _gateway = None
    _endpoints = []


def rotator_mounts() -> dict[str, httpx.AsyncBaseTransport] | None:
    """httpx mounts so only www.vlr.gg goes through AWS IPs."""
    endpoints = start_gateway()
    if not endpoints:
        return None
    return {VLR_SITE: VlrGatewayTransport(endpoints)}
