"""RBA parser — extracts a cash-rate decision from a monetary-policy media
release.

RBA decision statements use consistent language, e.g.:
    "the Board decided to lower the cash rate target by 25 basis points to
     3.85 per cent."
    "the Board decided to leave the cash rate target unchanged at 4.35 per cent."
    "the Board decided to raise the cash rate target by 25 basis points to
     4.35 per cent."

Parsing is regex-based on that wording. If the wording can't be matched we
return None rather than guessing — a missed scrape is fixable, a wrong decision
record corrupts the leaderboard.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .validate import make_provenance

PARSER_VERSION = "0.1.0"

_DIRECTION = {
    "lower": "cut",
    "reduce": "cut",
    "decrease": "cut",
    "cut": "cut",
    "raise": "raise",
    "increase": "raise",
    "lift": "raise",
    "leave": "hold",
    "maintain": "hold",
    "keep": "hold",
    "hold": "hold",
}

_DECISION_RE = re.compile(
    r"decided to (?P<verb>lower|reduce|decrease|cut|raise|increase|lift|leave|maintain|keep|hold)"
    r"[^.]*?cash rate target"
    r"(?:[^.]*?by\s+(?P<bps>\d+)\s+basis points)?"
    r"[^.]*?(?:to|at)\s+(?P<rate>\d+(?:\.\d+)?)\s*per cent",
    re.IGNORECASE | re.DOTALL,
)


def extract_text(html: str) -> str:
    """Strip HTML to visible text. Never executes anything in the document."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Collapse all whitespace so regexes don't trip over newlines inside nodes.
    return " ".join(soup.get_text(" ", strip=True).split())


def parse_decision(html: str, *, url: str, meeting_date: str) -> dict | None:
    """Parse one RBA media release into a decision record, or None if the
    decision language isn't found."""
    text = extract_text(html)
    m = _DECISION_RE.search(text)
    if not m:
        return None

    decision = _DIRECTION[m.group("verb").lower()]
    rate_after = float(m.group("rate"))
    bps = m.group("bps")
    change_bps = None
    if decision == "hold":
        change_bps = 0
    elif bps:
        change_bps = int(bps) * (-1 if decision == "cut" else 1)

    rate_before = None
    if change_bps:
        rate_before = round(rate_after - change_bps / 100, 2)

    return {
        "id": f"RBA_{meeting_date}",
        "bank": "RBA",
        "country": "AU",
        "meeting_date": meeting_date,
        "decision": decision,
        "rate_before": rate_before,
        "rate_after": rate_after,
        "change_bps": change_bps,
        "target_rate_name": "cash rate",
        "statement_url": url,
        "cited_indicators": {},
        "provenance": make_provenance(
            source_url=url,
            source_name="RBA",
            raw_content=html,
            ingest_method="scraper",
            parser="rba.py",
            parser_version=PARSER_VERSION,
        ),
    }


# Media-release index: link text/date extraction so the orchestrator knows
# which statement pages to fetch.
_RELEASE_LINK_RE = re.compile(r"/media-releases/\d{4}/mr-\d{2}-\d{2}\.html")


def parse_index(html: str) -> list[str]:
    """Return relative media-release URLs found on an RBA index page."""
    soup = BeautifulSoup(html, "lxml")
    hrefs = []
    for a in soup.find_all("a", href=True):
        if _RELEASE_LINK_RE.search(a["href"]):
            hrefs.append(a["href"])
    return sorted(set(hrefs))
