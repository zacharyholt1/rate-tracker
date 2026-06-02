"""Philadelphia Fed Survey of Professional Forecasters (SPF) parser.

The SPF is a quarterly survey of professional forecasters. The Philly Fed
publishes median projections for CPI, PCE, and unemployment as Excel files at:
  https://www.philadelphiafed.org/surveys-and-data/real-time-data-sets-and-other-data/survey-of-professional-forecasters

We consume the "level" Excel files for:
  - CPCE (PCE inflation)     median_CPCE_level.xlsx
  - CPI                      median_CPI_level.xlsx
  - UNEMP (unemployment)     median_UNEMP_level.xlsx

Each file has columns: YEAR, QUARTER, <SER>1 .. <SER>6
where <SER>N is the median forecast for the series N quarters ahead.
We convert level forecasts to annual % change (YoY) where applicable.

Records use forecaster_id="spf_philly_fed".
"""

from __future__ import annotations

import io
import re
from typing import Iterator

import openpyxl

from .validate import make_provenance

PARSER_VERSION = "0.1.0"

_BASE = (
    "https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/"
    "survey-of-professional-forecasters/data-files/files"
)

# (indicator, xlsx filename, column prefix, is_rate [True = level already %, no YoY calc])
SPF_SERIES = [
    ("pce",          "median_CPCE_level.xlsx",  "CPCE",  False),
    ("cpi",          "median_CPI_level.xlsx",   "CPI",   False),
    ("unemployment", "median_UNEMP_level.xlsx",  "UNEMP", True),
]


def spf_url(filename: str) -> str:
    return f"{_BASE}/{filename}"


def _quarter_end_date(year: int, quarter: int) -> str:
    """ISO date of the last month of a quarter (used as target_period)."""
    month = quarter * 3
    return f"{year}-{month:02d}"


def _target_period(survey_year: int, survey_quarter: int, horizon: int) -> tuple[int, int]:
    """Given survey timing and horizon (quarters ahead), return (year, quarter)."""
    total = (survey_quarter - 1) + horizon
    y = survey_year + total // 4
    q = (total % 4) + 1
    return y, q


def parse_spf_excel(
    xlsx_bytes: bytes,
    *,
    indicator: str,
    col_prefix: str,
    is_rate: bool,
    url: str,
    since: str | None = None,
) -> list[dict]:
    """Parse a Philly Fed SPF level Excel file into forecast records.

    ``since`` is YYYY-MM; rows with YEAR < since[:4] are skipped."""
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Find header row — first row containing "YEAR"
    header_row = None
    data_start = 0
    for i, row in enumerate(rows):
        row_str = [str(c).upper() if c is not None else "" for c in row]
        if "YEAR" in row_str:
            header_row = row_str
            data_start = i + 1
            break
    if header_row is None:
        return []

    # Map column name -> index
    col_idx: dict[str, int] = {name: i for i, name in enumerate(header_row)}
    year_col = col_idx.get("YEAR")
    quarter_col = col_idx.get("QUARTER")
    if year_col is None or quarter_col is None:
        return []

    # Horizon columns: CPCE1 .. CPCE6 (or CPI1..4, UNEMP1..4)
    horizon_cols: list[tuple[int, int]] = []
    for name, idx in col_idx.items():
        m = re.fullmatch(re.escape(col_prefix) + r"(\d)", name)
        if m:
            horizon_cols.append((idx, int(m.group(1))))
    horizon_cols.sort(key=lambda x: x[1])

    since_year = int(since[:4]) if since else 0
    records: list[dict] = []
    prev_level: dict[tuple[int, int], float] = {}  # (year, quarter) -> level, for YoY

    for row in rows[data_start:]:
        try:
            survey_year = int(row[year_col])
            survey_quarter = int(row[quarter_col])
        except (TypeError, ValueError):
            continue
        if survey_year < since_year:
            continue

        release_date = _quarter_end_date(survey_year, survey_quarter)

        for col, horizon in horizon_cols:
            if col >= len(row) or row[col] is None:
                continue
            try:
                level = float(row[col])
            except (TypeError, ValueError):
                continue

            target_year, target_quarter = _target_period(survey_year, survey_quarter, horizon)
            target_period = f"{target_year}-Q{target_quarter}"

            if is_rate:
                value = level
            else:
                # Compute YoY % change: compare this level to same quarter one year prior
                prior_key = (target_year - 1, target_quarter)
                prior = prev_level.get(prior_key)
                if prior and prior > 0:
                    value = round((level / prior - 1) * 100, 2)
                else:
                    # Store current level for future YoY computation, skip this record
                    prev_level[(target_year, target_quarter)] = level
                    continue

            prev_level[(target_year, target_quarter)] = level

            rid = f"spf_philly_fed_{release_date}_{indicator}_{target_period}"
            records.append({
                "id": rid,
                "forecaster_id": "spf_philly_fed",
                "country": "US",
                "bank": None,
                "forecast_type": "indicator",
                "published_at": release_date,
                "statement_excerpt": (
                    f"SPF median forecast: {indicator} of {value}{'%' if is_rate else '% YoY'} "
                    f"for {target_period} (survey {survey_year} Q{survey_quarter})."
                ),
                "prediction": {
                    "indicator": indicator,
                    "target_period": target_period,
                    "value": value,
                },
                "provenance": make_provenance(
                    source_url=url,
                    source_name="Philadelphia Fed SPF",
                    raw_content="<binary xlsx>",
                    parser="spf.py",
                    parser_version=PARSER_VERSION,
                ),
            })

    return records
