"""Tests for the Philadelphia Fed SPF parser."""

import io
import openpyxl
import pytest

from scrapers.spf import parse_spf_excel, find_spf_links
from scrapers.validate import validate_records

URL = "https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/survey-of-professional-forecasters/data-files/files/median_UNEMP_level.xlsx"


def _make_xlsx(rows: list[list]) -> bytes:
    """Build a minimal in-memory xlsx with the given rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _unemp_xlsx() -> bytes:
    return _make_xlsx([
        ["YEAR", "QUARTER", "UNEMP1", "UNEMP2", "UNEMP3", "UNEMP4"],
        [2024, 1, 3.9, 4.0, 4.1, 4.2],
        [2024, 2, 4.0, 4.1, 4.2, 4.3],
    ])


def test_parses_unemployment_levels():
    recs = parse_spf_excel(
        _unemp_xlsx(), indicator="unemployment", col_prefix="UNEMP",
        is_rate=True, url=URL,
    )
    assert len(recs) > 0
    assert all(r["prediction"]["indicator"] == "unemployment" for r in recs)


def test_target_period_format():
    recs = parse_spf_excel(
        _unemp_xlsx(), indicator="unemployment", col_prefix="UNEMP",
        is_rate=True, url=URL,
    )
    periods = {r["prediction"]["target_period"] for r in recs}
    # All should be YYYY-QN format
    assert all("-Q" in p for p in periods), periods


def test_forecaster_id():
    recs = parse_spf_excel(
        _unemp_xlsx(), indicator="unemployment", col_prefix="UNEMP",
        is_rate=True, url=URL,
    )
    assert all(r["forecaster_id"] == "spf_philly_fed" for r in recs)


def test_since_filter():
    recs = parse_spf_excel(
        _unemp_xlsx(), indicator="unemployment", col_prefix="UNEMP",
        is_rate=True, url=URL, since="2024-06",
    )
    # Only 2024+ rows (since_year=2024), both rows qualify
    assert len(recs) > 0
    recs_before = parse_spf_excel(
        _unemp_xlsx(), indicator="unemployment", col_prefix="UNEMP",
        is_rate=True, url=URL, since="2025-01",
    )
    assert len(recs_before) == 0


def test_schema_validation():
    recs = parse_spf_excel(
        _unemp_xlsx(), indicator="unemployment", col_prefix="UNEMP",
        is_rate=True, url=URL,
    )
    validate_records(recs, "forecast.schema.json")


def test_empty_xlsx():
    xlsx = _make_xlsx([["YEAR", "QUARTER", "UNEMP1"]])
    recs = parse_spf_excel(
        xlsx, indicator="unemployment", col_prefix="UNEMP",
        is_rate=True, url=URL,
    )
    assert recs == []


def test_rejects_non_xlsx_bytes():
    # A 404 HTML page (not a zip) must raise, not crash deep in openpyxl.
    with pytest.raises(ValueError):
        parse_spf_excel(
            b"<html>404 Not Found</html>", indicator="cpi", col_prefix="CPI",
            is_rate=False, url=URL,
        )


_INDEX_HTML = """
<html><body>
  <a href="/-/media/.../median_CPI_level.xlsx?la=en&hash=ABC">CPI median level</a>
  <a href="/-/media/.../mean_CPI_level.xlsx?la=en&hash=DEF">CPI mean level</a>
  <a href="/-/media/.../median_CPCE_level.xlsx?la=en&hash=GHI">PCE median level</a>
  <a href="/-/media/.../median_UNEMP_level.xlsx?la=en&hash=JKL">Unemp median level</a>
  <a href="/-/media/.../median_RGDP_level.xlsx?la=en&hash=MNO">GDP (ignored)</a>
</body></html>
"""


def test_find_spf_links_picks_median_level_per_series():
    links = find_spf_links(_INDEX_HTML, base_url="https://www.philadelphiafed.org/x")
    assert set(links) == {"cpi", "pce", "unemployment"}
    assert "median_CPI_level.xlsx" in links["cpi"]
    assert "mean_CPI" not in links["cpi"]          # prefers median, not mean
    assert "median_CPCE_level.xlsx" in links["pce"]
    assert links["cpi"].startswith("https://www.philadelphiafed.org")  # absolute


def test_find_spf_links_empty_when_no_matches():
    assert find_spf_links("<html><body><p>nothing</p></body></html>") == {}
