"""FRED parser — US economic indicators from the keyless CSV endpoint.

FRED's fredgraph.csv download needs no API key (so there's no secret to leak).
Format:

    observation_date,UNRATE
    2025-01-01,4.0
    2025-02-01,4.1
    2025-03-01,.

Missing values are a literal ".". Rate series (e.g. unemployment) are used
as-is; index series (CPI, PCE) are converted to year-over-year percent.
"""

from __future__ import annotations

from .sources import SOURCES
from .validate import make_provenance

PARSER_VERSION = "0.1.0"

# Series whose values are already a percent rate; everything else is an index
# we convert to YoY percent.
RATE_SERIES = {"unemployment"}


def parse_fred_csv(text: str) -> list[tuple[str, float | None]]:
    """Parse FRED CSV into [(YYYY-MM-DD, value|None), ...]."""
    points: list[tuple[str, float | None]] = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for line in lines[1:]:  # skip header
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date, raw = parts[0].strip(), parts[1].strip()
        if not date:
            continue
        value = None if raw in ("", ".") else float(raw)
        points.append((date, value))
    return points


def _yoy(points: list[tuple[str, float | None]]) -> list[tuple[str, float | None]]:
    """Convert a monthly index series to YoY percent (value vs 12 months prior)."""
    by_date = {d: v for d, v in points}
    out: list[tuple[str, float | None]] = []
    for i, (date, value) in enumerate(points):
        if value is None or i < 12:
            continue
        prev = points[i - 12][1]
        if prev:
            out.append((date, round((value / prev - 1) * 100, 1)))
    return out


def build_records(
    indicator_key: str,
    series_id: str,
    csv_text: str,
    *,
    since: str | None = None,
) -> list[dict]:
    """Build indicator records for a FRED series.

    By default emits only the most recent point (daily-refresh behaviour). When
    ``since`` (a ``YYYY-MM`` string) is given, emits every observation in that
    month or later — used for historical backfills.
    """
    points = parse_fred_csv(csv_text)
    is_rate = indicator_key in RATE_SERIES
    series = points if is_rate else _yoy(points)
    series = [(d, v) for d, v in series if v is not None]
    if not series:
        return []

    if since is None:
        series = [series[-1]]               # latest only
    else:
        series = [(d, v) for d, v in series if d[:7] >= since]

    url = f"{SOURCES['fred']['base_url']}?id={series_id}"
    unit = "percent" if is_rate else "percent_yoy"

    records = []
    for date, value in series:
        period = date[:7]                   # YYYY-MM
        records.append({
            "id": f"US_{indicator_key}_{period}",
            "country": "US",
            "indicator": indicator_key,
            "period": period,
            "period_type": "monthly",
            "value": value,
            "unit": unit,
            "released_at": None,
            "provenance": make_provenance(
                source_url=url,
                source_name="FRED",
                raw_content=csv_text,
                ingest_method="api",
                parser="fred.py",
                parser_version=PARSER_VERSION,
            ),
        })
    return records
