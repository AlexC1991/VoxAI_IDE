"""
IronGate Web Client — Rate Limiting & Request Safety
"""

import time
import threading
from .config import log


class RateLimiter:
    """Token-bucket rate limiter for outbound HTTP requests."""

    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0):
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        now = time.monotonic()
        with self._lock:
            self._timestamps = [t for t in self._timestamps if now - t < self._window]
            if len(self._timestamps) >= self._max:
                log.warning("Rate limit reached (%d/%d in %.0fs window)",
                            len(self._timestamps), self._max, self._window)
                return False
            self._timestamps.append(now)
            return True

    def wait(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire():
                return True
            time.sleep(0.5)
        return False


BLOCKED_DOMAINS = frozenset({
    "localhost", "127.0.0.1", "::1", "0.0.0.0",
    "metadata.google.internal", "169.254.169.254",
})


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/reserved IP range."""
    import ipaddress
    import socket as _socket
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        pass
    try:
        resolved = _socket.getaddrinfo(hostname, None, _socket.AF_UNSPEC, _socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in resolved:
            ip_str = sockaddr[0]
            addr = ipaddress.ip_address(ip_str)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return True
    except Exception:
        pass
    return False


def is_safe_url(url: str) -> bool:
    """Reject URLs targeting localhost, private IPs, or cloud metadata endpoints."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().strip(".")
        if not hostname:
            return False
        if hostname in BLOCKED_DOMAINS:
            log.warning("Blocked request to unsafe host: %s", hostname)
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        if _is_private_ip(hostname):
            log.warning("Blocked request to private/reserved IP: %s", hostname)
            return False
        return True
    except Exception:
        return False
