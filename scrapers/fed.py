"""Fed parser — extracts an FOMC rate decision from a press release.

FOMC statements use consistent language around the target range, e.g.:
    "the Committee decided to maintain the target range for the federal funds
     rate at 4-1/4 to 4-1/2 percent."
    "the Committee decided to raise the target range for the federal funds rate
     to 4-1/4 to 4-1/2 percent."
    "the Committee decided to lower the target range for the federal funds rate
     by 1/4 percentage point to 4 to 4-1/4 percent."

The Fed targets a *range* and writes rates as fractions (4-1/4 = 4.25). We
record the upper bound of the range as rate_after. Unmatched wording → None.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .validate import make_provenance

PARSER_VERSION = "0.1.0"

_DIRECTION = {
    "maintain": "hold",
    "keep": "hold",
    "leave": "hold",
    "raise": "raise",
    "increase": "raise",
    "lower": "cut",
    "reduce": "cut",
    "decrease": "cut",
}

_DECISION_RE = re.compile(
    r"decided to (?P<verb>maintain|keep|leave|raise|increase|lower|reduce|decrease)"
    r"[^.]*?target range for the federal funds rate"
    r"[^.]*?(?:to|at)\s+(?P<low>[\d/\- ]+?)\s+to\s+(?P<high>[\d/\- ]+?)\s+percent",
    re.IGNORECASE | re.DOTALL,
)


def _frac_to_float(s: str) -> float | None:
    """Parse Fed-style fractions: '4-1/4' -> 4.25, '4' -> 4.0, '1/2' -> 0.5."""
    s = s.strip()
    if not s:
        return None
    whole, frac = 0.0, 0.0
    if "-" in s:
        w, _, f = s.partition("-")
        whole = float(w.strip())
        frac = _parse_simple_frac(f)
    elif "/" in s:
        frac = _parse_simple_frac(s)
    else:
        whole = float(s)
    return round(whole + frac, 4)


def _parse_simple_frac(s: str) -> float:
    s = s.strip()
    if "/" in s:
        num, _, den = s.partition("/")
        return float(num) / float(den)
    return float(s)


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Collapse all whitespace so regexes don't trip over newlines inside nodes.
    return " ".join(soup.get_text(" ", strip=True).split())


def parse_decision(html: str, *, url: str, meeting_date: str) -> dict | None:
    text = extract_text(html)
    m = _DECISION_RE.search(text)
    if not m:
        return None

    decision = _DIRECTION[m.group("verb").lower()]
    high = _frac_to_float(m.group("high"))
    if high is None:
        return None

    return {
        "id": f"FED_{meeting_date}",
        "bank": "FED",
        "country": "US",
        "meeting_date": meeting_date,
        "decision": decision,
        "rate_before": None,
        "rate_after": high,
        "change_bps": 0 if decision == "hold" else None,
        "target_rate_name": "federal funds target (upper)",
        "statement_url": url,
        "cited_indicators": {},
        "provenance": make_provenance(
            source_url=url,
            source_name="Federal Reserve",
            raw_content=html,
            ingest_method="scraper",
            parser="fed.py",
            parser_version=PARSER_VERSION,
        ),
    }


_RELEASE_LINK_RE = re.compile(r"/newsevents/pressreleases/monetary\d{8}[a-z]\.htm")


def parse_index(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    hrefs = []
    for a in soup.find_all("a", href=True):
        if _RELEASE_LINK_RE.search(a["href"]):
            hrefs.append(a["href"])
    return sorted(set(hrefs))
