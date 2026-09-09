
# Valorant-Stats overlay: inbound limits are for a public host, not this private Docker API.
# Outbound vlr.gg traffic still goes through AWS IP rotator + Dagster RateGate.
import os as _vlr_rl_os

def _vlr_rl_tier(env_name: str, default: int) -> tuple[int, int]:
    """Read one inbound cap so Compose can raise the 20/min match-detail limit."""
    raw = _vlr_rl_os.getenv(env_name, str(default)).strip()
    return (max(int(raw), 0), 60)


TIERS = {
    "cheap": _vlr_rl_tier("VLR_RL_CHEAP", 200),
    "moderate": _vlr_rl_tier("VLR_RL_MODERATE", 120),
    "expensive": _vlr_rl_tier("VLR_RL_EXPENSIVE", 300),
}

_VLR_RL_DISABLE = _vlr_rl_os.getenv("VLR_RL_DISABLE", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_orig_rl_dispatch = RateLimitMiddleware.dispatch


async def _vlr_rl_dispatch(self, request, call_next):
    """Skip inbound 429s when this API is only used by our extract."""
    if _VLR_RL_DISABLE:
        return await call_next(request)
    return await _orig_rl_dispatch(self, request, call_next)


RateLimitMiddleware.dispatch = _vlr_rl_dispatch
