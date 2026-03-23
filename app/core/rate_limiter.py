"""Rate limiter singleton with Render-safe client IP extraction.

For Render deployments we avoid trusting ``request.client.host`` mutations from
proxy middleware. Instead, we derive the rate-limit key directly from the
right-most valid IP in ``X-Forwarded-For`` because Render appends the true
client IP to that position. Any attacker-controlled values prepended on the
left are ignored.
"""

import ipaddress
from typing import Optional

from slowapi import Limiter
from starlette.requests import Request

from app.core.config import settings


def _parse_ip(token: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a single X-Forwarded-For token into an IP address.

    Rejects malformed values instead of trying to be overly permissive.
    """
    candidate = token.strip().strip('"')
    if not candidate:
        return None
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _is_globally_routable(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return True for addresses that are usable as public client identities."""
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def get_rate_limit_ip(request: Request) -> str:
    """Derive a spoof-resistant client IP for rate limiting.

    Render appends the real client IP as the right-most X-Forwarded-For entry.
    We therefore scan from right to left, preferring the first globally
    routable IP. If every parsed value is private/reserved, we still fall back
    to the right-most valid IP instead of attacker-controlled left-side values.
    """
    x_forwarded_for = request.headers.get("x-forwarded-for", "")
    forwarded_chain = [
        parsed
        for parsed in (_parse_ip(part) for part in x_forwarded_for.split(","))
        if parsed is not None
    ]

    for address in reversed(forwarded_chain):
        if _is_globally_routable(address):
            return address.compressed

    if forwarded_chain:
        return forwarded_chain[-1].compressed

    client_host = request.client.host if request.client and request.client.host else ""
    parsed_client = _parse_ip(client_host)
    if parsed_client is not None:
        return parsed_client.compressed

    return "127.0.0.1"


def create_limiter(redis_url: Optional[str] = None) -> Limiter:
    """Create a Limiter with a shared backend when Redis is configured.

    The limiter is intentionally fail-open if the backend is temporarily
    unreachable so that Redis does not become an availability kill switch for
    core API endpoints.
    """
    kwargs: dict = {
        "key_func": get_rate_limit_ip,
        "swallow_errors": True,
    }
    if redis_url:
        kwargs["storage_uri"] = redis_url
    return Limiter(**kwargs)


limiter: Limiter = create_limiter(redis_url=settings.redis_url)
