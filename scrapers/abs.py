"""ABS parser — Australian CPI / unemployment from media-release text.

The ABS publishes plain-language summaries, e.g.:
    "The Consumer Price Index (CPI) rose 0.9 per cent in the March 2025 quarter
     and 2.4 per cent annually."
    "The unemployment rate remained at 4.1 per cent in April 2025."

We extract the annual CPI movement and the unemployment rate via regex. ABS
also offers bulk data downloads; those can be wired in later for full history.
Unmatched text → no record (don't guess).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .validate import make_provenance

PARSER_VERSION = "0.1.0"

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}
_QUARTER_MONTH = {"march": "Q1", "june": "Q2", "september": "Q3", "december": "Q4"}

_CPI_RE = re.compile(
    # 400-char cap prevents grabbing an unrelated number later on the page.
    r"Consumer Price Index.{0,400}?(?P<annual>\d+(?:\.\d+)?)\s*per cent\s*annually",
    re.IGNORECASE | re.DOTALL,
)
_CPI_PERIOD_RE = re.compile(
    r"(?P<month>March|June|September|December)\s+(?P<year>\d{4})\s+quarter",
    re.IGNORECASE,
)
# ABS unemployment: "The unemployment rate ... X per cent in Month YYYY"
# Also handle "rose to", "fell to", "was X per cent in", etc.
_UNEMP_RE = re.compile(
    r"unemployment rate[^.]{0,200}?(?:to|at|was)\s*"
    r"(?P<rate>\d+(?:\.\d+)?)\s*per cent\s+in\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})",
    re.IGNORECASE,
)


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Collapse all whitespace so regexes don't trip over newlines inside nodes.
    return " ".join(soup.get_text(" ", strip=True).split())


def parse_cpi(html: str, *, url: str) -> dict | None:
    text = extract_text(html)
    m = _CPI_RE.search(text)
    p = _CPI_PERIOD_RE.search(text)
    if not m or not p:
        return None
    quarter = _QUARTER_MONTH[p.group("month").lower()]
    period = f"{p.group('year')}-{quarter}"
    return {
        "id": f"AU_cpi_{period}",
        "country": "AU",
        "indicator": "cpi",
        "period": period,
        "period_type": "quarterly",
        "value": float(m.group("annual")),
        "unit": "percent_yoy",
        "released_at": None,
        "provenance": make_provenance(
            source_url=url, source_name="ABS", raw_content=html,
            ingest_method="scraper", parser="abs.py", parser_version=PARSER_VERSION,
        ),
    }


def parse_unemployment(html: str, *, url: str) -> dict | None:
    text = extract_text(html)
    m = _UNEMP_RE.search(text)
    if not m:
        return None
    month = m.group("month").lower()
    if month not in _MONTHS:
        return None
    period = f"{m.group('year')}-{_MONTHS[month]}"
    return {
        "id": f"AU_unemployment_{period}",
        "country": "AU",
        "indicator": "unemployment",
        "period": period,
        "period_type": "monthly",
        "value": float(m.group("rate")),
        "unit": "percent",
        "released_at": None,
        "provenance": make_provenance(
            source_url=url, source_name="ABS", raw_content=html,
            ingest_method="scraper", parser="abs.py", parser_version=PARSER_VERSION,
        ),
    }
