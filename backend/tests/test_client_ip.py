"""Tests for real-client-IP extraction behind a trusted proxy."""

from app.client_ip import extract_client_ip


def test_no_forwarded_header_uses_fallback():
    assert extract_client_ip(None, fallback="10.0.0.1") == "10.0.0.1"


def test_empty_forwarded_header_uses_fallback():
    assert extract_client_ip("   ", fallback="10.0.0.1") == "10.0.0.1"


def test_single_forwarded_entry():
    # Client -> Railway proxy. Railway appended the real client IP.
    assert extract_client_ip("203.0.113.5", fallback="10.0.0.1") == "203.0.113.5"


def test_takes_rightmost_entry_with_one_trusted_hop():
    # A client can spoof the leftmost entries; the rightmost is what our
    # trusted proxy actually observed, so with 1 trusted hop we take it.
    header = "1.1.1.1, 2.2.2.2, 203.0.113.5"
    assert extract_client_ip(header, fallback="10.0.0.1", trusted_hops=1) == "203.0.113.5"


def test_ignores_spoofed_leftmost_entry():
    # An attacker prepends a fake IP to evade rate limiting; we must not trust it.
    header = "9.9.9.9, 203.0.113.5"
    assert extract_client_ip(header, fallback="10.0.0.1", trusted_hops=1) == "203.0.113.5"


def test_multiple_trusted_hops():
    header = "203.0.113.5, 2.2.2.2, 3.3.3.3"
    assert extract_client_ip(header, fallback="10.0.0.1", trusted_hops=2) == "2.2.2.2"


def test_trusted_hops_exceeding_entries_clamps_to_leftmost():
    header = "203.0.113.5, 2.2.2.2"
    assert extract_client_ip(header, fallback="10.0.0.1", trusted_hops=9) == "203.0.113.5"


def test_whitespace_is_stripped():
    header = "1.1.1.1 ,  203.0.113.5 "
    assert extract_client_ip(header, fallback="10.0.0.1") == "203.0.113.5"
