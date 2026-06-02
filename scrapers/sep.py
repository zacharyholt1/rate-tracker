"""FOMC Summary of Economic Projections (SEP) parser.

The Fed publishes median projections for unemployment and PCE inflation
(headline + core) alongside selected FOMC meetings, at:
    https://www.federalreserve.gov/monetarypolicy/fomcprojtabl{YYYYMMDD}.htm

We extract the MEDIAN row for each variable and emit one indicator forecast
per projected year. These become forecaster_id="fomc" records, so the Fed's
own projections are scored on the same leaderboard as the banks.

Only inflation + unemployment are emitted here (the product's focus). The
federal-funds dot path is a different shape (path forecast) and is left out.

Pure functions only — no network — so this is unit-tested against a fixture.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .validate import make_provenance

PARSER_VERSION = "0.1.0"

# SEP variable label -> our indicator enum value.
_VARIABLE_MAP = {
    "pce inflation": "pce",
    "core pce inflation": "core_pce",
    "unemployment rate": "unemployment",
}

_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_value(text: str) -> float | None:
    text = _clean(text)
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def parse_sep(html: str, *, url: str, release_date: str) -> list[dict]:
    """Parse a SEP projections table into indicator forecast records.

    ``release_date`` is the ISO date the projections were published (the FOMC
    meeting date), used as published_at. Returns [] if no recognised table."""
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # Map each data column index -> projection year, from the header row.
        year_by_col: dict[int, str] = {}
        for r in rows:
            cells = r.find_all(["th", "td"])
            years = {}
            for idx, c in enumerate(cells):
                m = _YEAR_RE.search(_clean(c.get_text()))
                if m:
                    years[idx] = m.group(1)
            if len(years) >= 2:          # a real header has several year columns
                year_by_col = years
                break
        if not year_by_col:
            continue

        for r in rows:
            cells = r.find_all(["th", "td"])
            if not cells:
                continue
            label = _clean(cells[0].get_text()).lower()
            indicator = _VARIABLE_MAP.get(label)
            if not indicator:
                continue
            for col, year in year_by_col.items():
                if col >= len(cells):
                    continue
                value = _parse_value(cells[col].get_text())
                if value is None:
                    continue
                key = (indicator, year)
                if key in seen:
                    continue
                seen.add(key)
                records.append(_record(indicator, year, value, url, release_date, html))

    return records


def _record(indicator, year, value, url, release_date, html) -> dict:
    rid = f"fomc_{release_date}_US_{indicator}_{year}"
    return {
        "id": rid,
        "forecaster_id": "fomc",
        "country": "US",
        "bank": None,
        "forecast_type": "indicator",
        "published_at": release_date,
        "statement_excerpt": (
            f"FOMC median projection: {indicator.replace('_', ' ')} "
            f"of {value}% for {year}."
        ),
        "prediction": {
            "indicator": indicator,
            "target_period": year,        # annual (Q4/Q4) projection
            "value": value,
        },
        "provenance": make_provenance(
            source_url=url,
            source_name="Federal Reserve (SEP)",
            raw_content=html,
            parser="sep.py",
            parser_version=PARSER_VERSION,
        ),
    }
