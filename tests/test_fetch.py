"""Tests for the hardened fetch layer's policy checks (SSRF defences) and the
append-only merge logic. These never touch the network — they exercise the
validation that runs *before* any request is made.
"""

from __future__ import annotations

import json

import pytest

from scrapers import fetch
from scrapers.fetch import FetchError, assert_fetchable
from scrapers.sources import host_is_allowed


# ---- allowlist -------------------------------------------------------------

def test_allowlist_accepts_known_and_subdomains():
    assert host_is_allowed("rba.gov.au")
    assert host_is_allowed("www.rba.gov.au")
    assert host_is_allowed("fred.stlouisfed.org")


def test_allowlist_rejects_unknown():
    assert not host_is_allowed("evil.example")
    # Suffix-confusion must not pass: not a real subdomain of rba.gov.au
    assert not host_is_allowed("rba.gov.au.evil.example")
    assert not host_is_allowed("notrba.gov.au")


# ---- scheme + allowlist (no DNS) -------------------------------------------

def test_rejects_non_https():
    with pytest.raises(FetchError, match="https"):
        assert_fetchable("http://www.rba.gov.au/x")


def test_rejects_off_allowlist_host():
    with pytest.raises(FetchError, match="allowlist"):
        assert_fetchable("https://evil.example/x")


def test_rejects_no_host():
    with pytest.raises(FetchError):
        assert_fetchable("https:///nohost")


# ---- private-IP / SSRF guard (DNS monkeypatched) ---------------------------

def _fake_getaddrinfo(ip):
    def _inner(host, *a, **k):
        return [(2, 1, 6, "", (ip, 0))]
    return _inner


@pytest.mark.parametrize("ip", [
    "127.0.0.1",        # loopback
    "169.254.169.254",  # cloud metadata
    "10.0.0.5",         # RFC1918
    "192.168.1.1",      # RFC1918
    "0.0.0.0",          # unspecified
])
def test_blocks_private_resolution(monkeypatch, ip):
    # Pretend an allowlisted host resolves to an internal address.
    monkeypatch.setattr(fetch.socket, "getaddrinfo", _fake_getaddrinfo(ip))
    with pytest.raises(FetchError, match="non-public"):
        assert_fetchable("https://www.rba.gov.au/x")


def test_allows_public_resolution(monkeypatch):
    monkeypatch.setattr(fetch.socket, "getaddrinfo", _fake_getaddrinfo("23.45.67.89"))
    assert assert_fetchable("https://www.rba.gov.au/x") == "www.rba.gov.au"


# ---- merge (append-only) ---------------------------------------------------

def test_merge_is_append_only(tmp_path, monkeypatch):
    from scrapers import run

    data_dir = tmp_path
    monkeypatch.setattr(run, "DATA_DIR", data_dir)

    rec_v1 = {
        "id": "RBA_2025-05-20", "bank": "RBA", "country": "AU",
        "meeting_date": "2025-05-20", "decision": "cut", "rate_after": 3.85,
        "provenance": {
            "source_url": "https://www.rba.gov.au/x", "source_name": "RBA",
            "scraped_at": "2026-01-01T00:00:00+00:00", "ingest_method": "scraper",
            "content_hash": "sha256:" + "a" * 64,
        },
    }
    added = run.merge_into("decisions.json", "decision.schema.json", [rec_v1])
    assert added == 1

    # Re-merging the same id (even with a changed value) must NOT overwrite.
    rec_v2 = json.loads(json.dumps(rec_v1))
    rec_v2["rate_after"] = 9.99
    added = run.merge_into("decisions.json", "decision.schema.json", [rec_v2])
    assert added == 0

    stored = json.loads((data_dir / "decisions.json").read_text())
    assert len(stored) == 1
    assert stored[0]["rate_after"] == 3.85  # original preserved
