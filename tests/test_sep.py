"""Tests for the FOMC SEP projections parser."""

from scrapers.sep import parse_sep
from scrapers.validate import validate_records

# Representative SEP median-projections table (federalreserve.gov shape).
FIXTURE = """
<html><body>
<table>
  <tr><th>Variable</th><th>2024</th><th>2025</th><th>2026</th><th>Longer run</th></tr>
  <tr><td>Change in real GDP</td><td>2.1</td><td>2.0</td><td>2.0</td><td>1.8</td></tr>
  <tr><td>Unemployment rate</td><td>4.0</td><td>4.2</td><td>4.1</td><td>4.1</td></tr>
  <tr><td>PCE inflation</td><td>2.6</td><td>2.2</td><td>2.0</td><td>2.0</td></tr>
  <tr><td>Core PCE inflation</td><td>2.8</td><td>2.3</td><td>2.0</td><td></td></tr>
  <tr><td>Federal funds rate</td><td>4.4</td><td>3.4</td><td>2.9</td><td>2.8</td></tr>
</table>
</body></html>
"""

URL = "https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20240320.htm"


def test_parses_inflation_and_unemployment_only():
    recs = parse_sep(FIXTURE, url=URL, release_date="2024-03-20")
    indicators = {r["prediction"]["indicator"] for r in recs}
    assert indicators == {"unemployment", "pce", "core_pce"}  # no GDP, no fed funds


def test_one_record_per_year_including_longer_run():
    recs = parse_sep(FIXTURE, url=URL, release_date="2024-03-20")
    unemp = sorted(r["prediction"]["target_period"] for r in recs
                   if r["prediction"]["indicator"] == "unemployment")
    assert unemp == ["2024", "2025", "2026"]  # "Longer run" has no year -> skipped


def test_values_and_ids():
    recs = parse_sep(FIXTURE, url=URL, release_date="2024-03-20")
    by_key = {(r["prediction"]["indicator"], r["prediction"]["target_period"]): r for r in recs}
    assert by_key[("pce", "2025")]["prediction"]["value"] == 2.2
    assert by_key[("unemployment", "2024")]["prediction"]["value"] == 4.0
    assert by_key[("core_pce", "2026")]["id"] == "fomc_2024-03-20_US_core_pce_2026"
    assert by_key[("pce", "2025")]["forecaster_id"] == "fomc"


def test_records_pass_schema():
    recs = parse_sep(FIXTURE, url=URL, release_date="2024-03-20")
    validate_records(recs, "forecast.schema.json")  # raises on any invalid record


def test_empty_on_unrecognised_html():
    assert parse_sep("<html><body><p>no table</p></body></html>",
                     url=URL, release_date="2024-03-20") == []
