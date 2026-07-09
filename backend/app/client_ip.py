"""Real-client-IP extraction for requests behind a trusted proxy.

On Railway the app sits behind Railway's edge proxy, so the socket peer is the
proxy, not the user. slowapi's default key function (`get_remote_address`)
therefore sees one shared proxy IP and lumps every user into a single rate-limit
bucket. The real client IP is carried in the `X-Forwarded-For` header.

TRUST ASSUMPTION: `X-Forwarded-For` is a client-controllable, comma-separated
list of the form `client, proxy1, proxy2, ...`. Everything a client sends is
untrusted and can be spoofed; only the entries our own trusted proxy appends are
reliable. With `trusted_hops` proxies between us and the internet, the real
client IP is the `trusted_hops`-th entry counted from the RIGHT. We default to a
single trusted hop (Railway's edge), so we take the rightmost entry. Taking the
leftmost (as naive parsers do) would let a client spoof a fresh IP per request
and evade per-IP limits entirely.
"""

from __future__ import annotations


def extract_client_ip(
    forwarded_for: str | None,
    fallback: str,
    trusted_hops: int = 1,
) -> str:
    """Pick the real client IP from an X-Forwarded-For header value.

    Args:
        forwarded_for: Raw header value, or None if absent.
        fallback: IP to use when the header is missing/empty (typically the
            socket peer address).
        trusted_hops: Number of trusted proxies between us and the client. The
            chosen IP is this many positions from the right of the list.

    Returns:
        The client IP string, or `fallback` when no usable header is present.
    """
    if forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        if parts:
            # Count `trusted_hops` from the right, clamped to a valid index so a
            # misconfigured hop count (0, negative, or larger than the list)
            # never raises — it just falls back to an endpoint of the list.
            index = min(len(parts) - 1, max(0, len(parts) - trusted_hops))
            return parts[index]
    return fallback
