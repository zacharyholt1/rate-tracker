"""Forecast extractor — pulls economist / bank rate calls out of news coverage.

This is the fuzziest scraper by nature (free-text journalism), so it follows
the same discipline as the decision parsers: extract what's clearly stated,
return nothing when unsure. A missed forecast is fixable; a fabricated one
corrupts the leaderboard.

It produces *forecast* records only — scoring is a separate, deterministic
step (scorer.py). Point calls naming a month are resolved to a concrete meeting
id via a known meeting calendar; calls we can't pin to a meeting are dropped.

Known limitation: tuned against representative fixtures, not yet against live
article HTML. Phrasing coverage will need expanding once pointed at real feeds.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .validate import make_provenance

PARSER_VERSION = "0.1.0"

# Forecasters we recognise by name -> (slug, type). Auto-discovery in the sense
# that whoever appears in coverage gets tracked; this map normalises names.
KNOWN_FORECASTERS = {
    "goldman sachs": ("goldman_sachs", "bank"),
    "jpmorgan": ("jpmorgan", "bank"),
    "j.p. morgan": ("jpmorgan", "bank"),
    "morgan stanley": ("morgan_stanley", "bank"),
    "bank of america": ("bank_of_america", "bank"),
    "citi": ("citi", "bank"),
    "ubs": ("ubs", "bank"),
    "barclays": ("barclays", "bank"),
    "deutsche bank": ("deutsche_bank", "bank"),
    "westpac": ("westpac", "bank"),
    "nab": ("nab", "bank"),
    "national australia bank": ("nab", "bank"),
    "commonwealth bank": ("cba", "bank"),
    "cba": ("cba", "bank"),
    "anz": ("anz", "bank"),
}

_BANKS = {"rba": ("RBA", "AU"), "fed": ("FED", "US"), "fomc": ("FED", "US"),
          "federal reserve": ("FED", "US"), "reserve bank": ("RBA", "AU")}

_FORECAST_VERB = r"(?:expects?|forecasts?|sees|predicts?|tips|pencils in|looks for|anticipates?|projects?)"
_CUT = r"(?:cut|lower|reduce|ease|trim)"
_RAISE = r"(?:raise|hike|lift|increase)"
_HOLD = r"(?:hold|keep|leave|pause|maintain)"

_MONTHS = ("january february march april may june july august september "
           "october november december").split()

# "<Forecaster> expects the RBA to cut ... by 25 basis points ... in May"
_POINT_RE = re.compile(
    r"(?P<who>" + "|".join(re.escape(k) for k in KNOWN_FORECASTERS) + r")"
    r"\s+" + _FORECAST_VERB + r"\s+the\s+(?P<bank>rba|fed|fomc|federal reserve|reserve bank)"
    r"\s+to\s+(?P<dir>" + _CUT + r"|" + _RAISE + r"|" + _HOLD + r")"
    r"(?:[^.]*?by\s+(?P<bps>\d+)\s+basis points)?"
    r"(?:[^.]*?(?:in|at the)\s+(?P<month>" + "|".join(_MONTHS) + r")\b)?",
    re.IGNORECASE,
)

# "<Forecaster> expects N cuts (from the RBA) (in 2025)"
_PATH_RE = re.compile(
    r"(?P<who>" + "|".join(re.escape(k) for k in KNOWN_FORECASTERS) + r")"
    r"\s+" + _FORECAST_VERB + r"\s+(?P<n>\d+|two|three|four|five)\s+"
    r"(?P<dir>" + _CUT + r"s|" + _RAISE + r"s)"
    r"(?:[^.]*?(?P<bank>rba|fed|fomc|federal reserve|reserve bank))?"
    r"(?:[^.]*?(?:in|through|during)\s+(?P<year>20\d{2}))?",
    re.IGNORECASE,
)

_WORD_NUM = {"two": 2, "three": 3, "four": 4, "five": 5}


def _dir_label(word: str) -> str:
    w = word.lower()
    if re.match(_CUT, w):
        return "cut"
    if re.match(_RAISE, w):
        return "raise"
    return "hold"


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def extract_forecasts(
    html: str,
    *,
    url: str,
    source_name: str,
    published_at: str,
    meeting_calendar: dict[tuple[str, str, int], str] | None = None,
    default_year: int | None = None,
) -> list[dict]:
    """Extract forecast records from one article.

    meeting_calendar maps (bank, month_name_lower, year) -> decision id, used to
    resolve point calls that name a month. Point calls that can't be resolved to
    a concrete meeting are dropped.
    """
    text = extract_text(html)
    calendar = meeting_calendar or {}
    results: list[dict] = []

    # ---- path calls ----
    for m in _PATH_RE.finditer(text):
        slug, _ = KNOWN_FORECASTERS[m.group("who").lower()]
        bank_raw = (m.group("bank") or "").lower()
        if bank_raw not in _BANKS:
            continue
        bank, country = _BANKS[bank_raw]
        n_raw = m.group("n").lower()
        n = int(n_raw) if n_raw.isdigit() else _WORD_NUM.get(n_raw)
        if not n:
            continue
        direction = _dir_label(m.group("dir"))
        year = int(m.group("year")) if m.group("year") else default_year
        if not year:
            continue
        results.append({
            "id": f"{slug}_{published_at}_{bank}_{year}-path",
            "forecaster_id": slug,
            "country": country, "bank": bank,
            "forecast_type": "path", "published_at": published_at,
            "statement_excerpt": _sentence_around(text, m.start()),
            "prediction": {
                "horizon_start": f"{year}-01-01", "horizon_end": f"{year}-12-31",
                "cuts": n if direction == "cut" else 0,
                "raises": n if direction == "raise" else 0,
            },
            "provenance": make_provenance(
                source_url=url, source_name=source_name, raw_content=html,
                ingest_method="scraper", parser="forecasts.py",
                parser_version=PARSER_VERSION),
        })

    # ---- point calls ----
    for m in _POINT_RE.finditer(text):
        bank_raw = m.group("bank").lower()
        if bank_raw not in _BANKS:
            continue
        bank, country = _BANKS[bank_raw]
        month = (m.group("month") or "").lower()
        year = default_year or int(published_at[:4])
        target = calendar.get((bank, month, year)) if month else None
        if not target:
            continue  # can't pin to a meeting -> drop
        slug, _ = KNOWN_FORECASTERS[m.group("who").lower()]
        direction = _dir_label(m.group("dir"))
        bps = int(m.group("bps")) if m.group("bps") else None
        change_bps = None
        if direction == "hold":
            change_bps = 0
        elif bps:
            change_bps = bps * (-1 if direction == "cut" else 1)
        results.append({
            "id": f"{slug}_{published_at}_{target}",
            "forecaster_id": slug,
            "country": country, "bank": bank,
            "forecast_type": "point", "published_at": published_at,
            "statement_excerpt": _sentence_around(text, m.start()),
            "prediction": {
                "target_event": target, "decision": direction,
                "change_bps": change_bps,
            },
            "provenance": make_provenance(
                source_url=url, source_name=source_name, raw_content=html,
                ingest_method="scraper", parser="forecasts.py",
                parser_version=PARSER_VERSION),
        })

    return results


def _sentence_around(text: str, pos: int) -> str:
    """Grab the sentence containing position `pos`, for the receipt."""
    start = text.rfind(".", 0, pos) + 1
    end = text.find(".", pos)
    if end == -1:
        end = len(text)
    return text[start:end + 1].strip()
