from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.client_ip import extract_client_ip
from app.config import settings


def client_ip_key(request: Request) -> str:
    """Rate-limit key: the real client IP, resolved through the trusted proxy.

    Behind Railway's edge proxy the socket peer is the proxy, so we read the
    forwarded IP instead. Falls back to the socket address when the header is
    absent (e.g. local dev).
    """
    fallback = get_remote_address(request)
    return extract_client_ip(
        request.headers.get("x-forwarded-for"),
        fallback=fallback,
        trusted_hops=settings.TRUSTED_PROXY_HOPS,
    )


limiter = Limiter(key_func=client_ip_key)
