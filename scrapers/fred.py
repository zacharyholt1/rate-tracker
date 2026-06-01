"""FRED parser — US and AU economic indicators from the keyless CSV endpoint.

FRED's fredgraph.csv download needs no API key (so there's no secret to leak).
Format:

    observation_date,UNRATE
    2025-01-01,4.0
    2025-02-01,4.1
    2025-03-01,.

Missing values are a literal ".". Rate series (e.g. unemployment) are used
as-is; index series (CPI, PCE) are converted to year-over-year percent.
Annual series (e.g. FPCPITOTLZGAUS) emit a YYYY period instead of YYYY-MM.
Quarterly series (e.g. LRUNTTTTAUQ156S) emit a YYYY-QN period.
"""

from __future__ import annotations

from .sources import SOURCES
from .validate import make_provenance

PARSER_VERSION = "0.1.0"

# Series whose values are already a percent rate (not an index to convert to YoY).
RATE_SERIES = {"unemployment", "au_unemployment"}

# Series FRED already reports as annual YoY percent (no index conversion needed).
ANNUAL_YOY_SERIES = {"au_cpi"}


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
    out: list[tuple[str, float | None]] = []
    for i, (date, value) in enumerate(points):
        if value is None or i < 12:
            continue
        prev = points[i - 12][1]
        if prev:
            out.append((date, round((value / prev - 1) * 100, 1)))
    return out


def _period_and_type(date_str: str, cfg: dict) -> tuple[str, str]:
    """Derive (period, period_type) from a FRED date string and series config."""
    period_type = cfg.get("period_type", "monthly")
    if period_type == "annual":
        return date_str[:4], "annual"
    if period_type == "quarterly":
        month = int(date_str[5:7])
        q = (month - 1) // 3 + 1
        return f"{date_str[:4]}-Q{q}", "quarterly"
    return date_str[:7], "monthly"   # YYYY-MM


def build_records(
    indicator_key: str,
    series_id: str,
    csv_text: str,
    *,
    since: str | None = None,
    series_cfg: dict | None = None,
) -> list[dict]:
    """Build indicator records for a FRED series.

    By default emits only the most recent point (daily-refresh behaviour). When
    ``since`` (a ``YYYY-MM`` string) is given, emits every observation in that
    month or later — used for historical backfills.
    """
    cfg = series_cfg or {"id": series_id, "country": "US", "period_type": "monthly"}
    country = cfg.get("country", "US")
    # Use canonical indicator name from config if provided (e.g. "cpi" for "au_cpi").
    indicator_name = cfg.get("indicator", indicator_key)

    points = parse_fred_csv(csv_text)
    is_rate = indicator_key in RATE_SERIES
    already_yoy = indicator_key in ANNUAL_YOY_SERIES

    if already_yoy or is_rate:
        series = [(d, v) for d, v in points if v is not None]
    else:
        series = _yoy(points)
        series = [(d, v) for d, v in series if v is not None]

    if not series:
        return []

    if since is None:
        series = [series[-1]]
    else:
        series = [(d, v) for d, v in series if d[:7] >= since]

    url = f"{SOURCES['fred']['base_url']}?id={series_id}"
    unit = "percent" if (is_rate and not already_yoy) else "percent_yoy"

    records = []
    seen_periods: set[str] = set()
    for date_str, value in series:
        period, period_type = _period_and_type(date_str, cfg)
        if period in seen_periods:
            continue  # quarterly/annual series can have multiple obs per period
        seen_periods.add(period)
        records.append({
            "id": f"{country}_{indicator_key}_{period}",
            "country": country,
            "indicator": indicator_name,
            "period": period,
            "period_type": period_type,
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
