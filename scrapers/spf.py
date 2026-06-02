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
from urllib.parse import urljoin

import openpyxl
from bs4 import BeautifulSoup

from .validate import make_provenance

PARSER_VERSION = "0.1.0"

# Page that lists the individual-variable data files (with their CDN hashes).
INDEX_URL = (
    "https://www.philadelphiafed.org/surveys-and-data/real-time-data-sets-"
    "and-other-data/survey-of-professional-forecasters/data-files"
)

# indicator -> (filename token, level-column prefix, is_rate)
#   is_rate=True  -> the level is already a percentage rate (unemployment); use as-is.
#   is_rate=False -> the level is an index; convert to YoY % change.
# The Philly Fed file names contain these tokens, e.g. "median_CPCE_level.xlsx".
SPF_SERIES = [
    ("pce",          "cpce",  "CPCE",  False),
    ("cpi",          "cpi",   "CPI",   False),
    ("unemployment", "unemp", "UNEMP", True),
]


def find_spf_links(index_html: str, base_url: str = INDEX_URL) -> dict[str, str]:
    """Find the median level-forecast xlsx link for each series on the SPF
    data-files page. Returns {indicator: absolute_url}.

    Matches an <a href> ending in .xlsx whose filename contains the series token
    and 'median' and 'level' (so we get the median level file, not mean/growth).
    Resolving links from the page is what picks up the mandatory CDN ?hash= param
    that a hand-built URL would miss (the cause of the BadZipFile error)."""
    soup = BeautifulSoup(index_html, "html.parser")
    # Prefer cpce match before cpi, since "cpce" does not contain "cpi" but we
    # still want the most specific token to win if both somehow match.
    links: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        low = href.lower()
        if ".xlsx" not in low or "median" not in low or "level" not in low:
            continue
        for indicator, token, _prefix, _is_rate in SPF_SERIES:
            if token in low and indicator not in links:
                links[indicator] = urljoin(base_url, href)
                break
    return links


def _looks_like_xlsx(data: bytes) -> bool:
    """xlsx files are zip archives — they start with the PK magic bytes. A 404
    or redirect HTML page won't, so this catches a bad URL before openpyxl
    raises a cryptic BadZipFile deep in the run."""
    return data[:2] == b"PK"


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

    ``since`` is YYYY-MM; rows with YEAR < since[:4] are skipped.
    Raises ValueError if the bytes aren't a real xlsx (e.g. a 404 HTML page)."""
    if not _looks_like_xlsx(xlsx_bytes):
        raise ValueError(f"not an xlsx file (bad URL?): {url}")
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
