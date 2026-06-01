"""Source allowlist + registry.

Single source of truth for which domains the system is allowed to fetch.
Used by both the scheduled scrapers and the on-demand ``scrape_url`` function,
so an arbitrary-URL fetcher (a classic SSRF foot-gun) never exists — we only
ever fetch from domains we explicitly trust.
"""

from __future__ import annotations

# Domains we trust. A URL is fetchable only if its host equals one of these
# or is a subdomain of one. Keep this tight — every entry is attack surface.
ALLOWED_DOMAINS = frozenset({
    # Central banks
    "federalreserve.gov",
    "rba.gov.au",
    # Official statistics
    "stlouisfed.org",      # FRED (keyless CSV download)
    "abs.gov.au",          # Australian Bureau of Statistics
    # News / forecast coverage
    "reuters.com",
    "afr.com",
    "wsj.com",
    "bloomberg.com",
})

# Per-source metadata for the scheduled scrapers.
SOURCES = {
    "fed": {
        "name": "Federal Reserve",
        "country": "US",
        "index_url": "https://www.federalreserve.gov/newsevents/pressreleases/2025-monetary-policy.htm",
        "parser": "fed.py",
    },
    "rba": {
        "name": "RBA",
        "country": "AU",
        "index_url": "https://www.rba.gov.au/media-releases/2025/",
        "parser": "rba.py",
    },
    "fred": {
        "name": "FRED",
        "country": "US",
        # Keyless CSV endpoint — no API key needed, so nothing secret to leak.
        "base_url": "https://fred.stlouisfed.org/graph/fredgraph.csv",
        "parser": "fred.py",
        "series": {
            "cpi": "CPIAUCSL",
            "core_cpi": "CPILFESL",
            "pce": "PCEPI",
            "core_pce": "PCEPILFE",
            "unemployment": "UNRATE",
        },
    },
    "abs": {
        "name": "ABS",
        "country": "AU",
        "index_url": "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation",
        "parser": "abs.py",
    },
}


def host_is_allowed(host: str) -> bool:
    """True if host equals or is a subdomain of an allowlisted domain."""
    host = host.lower().strip(".")
    return any(
        host == domain or host.endswith("." + domain)
        for domain in ALLOWED_DOMAINS
    )
