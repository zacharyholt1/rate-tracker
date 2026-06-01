"""Source allowlist + registry.

Single source of truth for which domains the system is allowed to fetch.
Used by both the scheduled scrapers and the on-demand ``scrape_url`` function,
so an arbitrary-URL fetcher (a classic SSRF foot-gun) never exists — we only
ever fetch from domains we explicitly trust.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

# Domains we trust, loaded from the shared config so the Python scrapers and the
# Node scrape_url function read the exact same allowlist (no drift). A URL is
# fetchable only if its host equals one of these or is a subdomain of one.
_CONFIG = Path(__file__).resolve().parent.parent / "config" / "allowed_domains.json"
ALLOWED_DOMAINS = frozenset(json.loads(_CONFIG.read_text())["allowed_domains"])

_YEAR = date.today().year

# Year-templated archive index URLs, used by the backfill to walk past years.
FED_INDEX_TMPL = "https://www.federalreserve.gov/newsevents/pressreleases/{year}-press-fomc.htm"
RBA_INDEX_TMPL = "https://www.rba.gov.au/media-releases/{year}/"

# Per-source metadata for the scheduled scrapers.
SOURCES = {
    "fed": {
        "name": "Federal Reserve",
        "country": "US",
        "index_url": f"https://www.federalreserve.gov/newsevents/pressreleases/{_YEAR}-press-fomc.htm",
        "parser": "fed.py",
    },
    "rba": {
        "name": "RBA",
        "country": "AU",
        "index_url": f"https://www.rba.gov.au/media-releases/{_YEAR}/",
        "parser": "rba.py",
    },
    "fred": {
        "name": "FRED",
        "country": "US",
        # Keyless CSV endpoint — no API key needed, so nothing secret to leak.
        "base_url": "https://fred.stlouisfed.org/graph/fredgraph.csv",
        "parser": "fred.py",
        "series": {
            # US indicators
            "cpi":          {"id": "CPIAUCSL",        "country": "US", "period_type": "monthly"},
            "core_cpi":     {"id": "CPILFESL",        "country": "US", "period_type": "monthly"},
            "pce":          {"id": "PCEPI",           "country": "US", "period_type": "monthly"},
            "core_pce":     {"id": "PCEPILFE",        "country": "US", "period_type": "monthly"},
            "unemployment": {"id": "UNRATE",          "country": "US", "period_type": "monthly"},
            # AU indicators (sourced from ABS via FRED — avoids ABS bot-blocking)
            # Keys prefixed "au_" to avoid id collisions with US series in build_records,
            # but the indicator field is set to the canonical name (cpi/unemployment).
            "au_cpi":          {"id": "FPCPITOTLZGAUS",    "country": "AU", "period_type": "annual",    "indicator": "cpi"},
            "au_unemployment": {"id": "LRUNTTTTAUQ156S",   "country": "AU", "period_type": "quarterly", "indicator": "unemployment"},
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
