import hmac
import ipaddress
import socket
import time
from collections import defaultdict
from urllib.parse import urlparse

from .config import settings

BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

ALLOWED_SCHEMES = frozenset({"http", "https"})


async def check_url_safety(url: str) -> bool:
    """SSRF protection: block private/reserved CIDRs, loopback, unsafe schemes."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ALLOWED_SCHEMES:
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    if hostname in ("localhost", "0.0.0.0", "[::]", "[::1]"):
        return False

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
        for info in addr_infos:
            ip = ipaddress.ip_address(info[4][0])
            for network in BLOCKED_NETWORKS:
                if ip in network:
                    return False
    except (socket.gaierror, ValueError, OSError):
        return False

    return True


# ---------------------------------------------------------------------------
# In-memory sliding-window rate limiter
# ---------------------------------------------------------------------------
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(client_id: str) -> bool:
    """Return True if the request is within the rate limit."""
    now = time.time()
    window = 60.0
    bucket = _rate_buckets[client_id]
    _rate_buckets[client_id] = [t for t in bucket if now - t < window]
    bucket = _rate_buckets[client_id]

    if len(bucket) >= settings.rate_limit_rpm:
        return False

    bucket.append(now)
    return True


# ---------------------------------------------------------------------------
# Token auth
# ---------------------------------------------------------------------------
def verify_auth_token(token: str | None) -> bool:
    """Constant-time token comparison."""
    if not token:
        return False
    return hmac.compare_digest(token, settings.auth_token)
