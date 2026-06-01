"""Parser tests — each scraper parses representative source content into
schema-valid records. Fixtures mirror real source wording.
"""

from __future__ import annotations

import pytest

from scrapers import abs as abs_mod
from scrapers import fed, fred, rba
from scrapers.validate import validate_records


# ---- FRED ------------------------------------------------------------------

UNRATE_CSV = """observation_date,UNRATE
2025-01-01,4.0
2025-02-01,4.1
2025-03-01,4.2
2025-04-01,4.2
"""

CPI_CSV = "observation_date,CPIAUCSL\n" + "".join(
    f"2024-{m:02d}-01,{300 + m}\n" for m in range(1, 13)
) + "".join(
    f"2025-{m:02d}-01,{307 + m}\n" for m in range(1, 5)
)


def test_fred_parses_rate_series():
    recs = fred.build_records("unemployment", "UNRATE", UNRATE_CSV)
    assert len(recs) == 1
    r = recs[0]
    assert r["id"] == "US_unemployment_2025-04"
    assert r["value"] == 4.2
    assert r["unit"] == "percent"
    validate_records(recs, "indicator.schema.json")


def test_fred_converts_index_to_yoy():
    recs = fred.build_records("cpi", "CPIAUCSL", CPI_CSV)
    assert len(recs) == 1
    r = recs[0]
    assert r["unit"] == "percent_yoy"
    assert r["period"] == "2025-04"
    # 2025-04 index 311 vs 2024-04 index 304 -> ~2.3%
    assert r["value"] == pytest.approx(2.3, abs=0.1)
    validate_records(recs, "indicator.schema.json")


def test_fred_handles_missing_values():
    csv = "observation_date,UNRATE\n2025-03-01,.\n2025-04-01,4.2\n"
    recs = fred.build_records("unemployment", "UNRATE", csv)
    assert recs[0]["value"] == 4.2


def test_fred_backfill_emits_full_history_since():
    # Default emits only the latest; --since emits every point from that month.
    recs = fred.build_records("unemployment", "UNRATE", UNRATE_CSV, since="2025-02")
    periods = [r["period"] for r in recs]
    assert periods == ["2025-02", "2025-03", "2025-04"]   # 2025-01 excluded
    validate_records(recs, "indicator.schema.json")


# ---- RBA -------------------------------------------------------------------

RBA_CUT = """<html><body><p>At its meeting today, the Board decided to lower the
cash rate target by 25 basis points to 3.85 per cent. Inflation has continued
to moderate.</p></body></html>"""

RBA_HOLD = """<html><body><p>At its meeting today, the Board decided to leave the
cash rate target unchanged at 4.35 per cent.</p></body></html>"""

RBA_RAISE = """<html><body><p>The Board decided to raise the cash rate target by
25 basis points to 4.35 per cent.</p></body></html>"""


def test_rba_parses_cut():
    r = rba.parse_decision(RBA_CUT, url="https://www.rba.gov.au/x.html", meeting_date="2025-05-20")
    assert r["decision"] == "cut"
    assert r["rate_after"] == 3.85
    assert r["change_bps"] == -25
    assert r["rate_before"] == 4.10
    validate_records([r], "decision.schema.json")


def test_rba_parses_hold():
    r = rba.parse_decision(RBA_HOLD, url="https://www.rba.gov.au/x.html", meeting_date="2025-04-01")
    assert r["decision"] == "hold"
    assert r["rate_after"] == 4.35
    assert r["change_bps"] == 0
    validate_records([r], "decision.schema.json")


def test_rba_parses_raise():
    r = rba.parse_decision(RBA_RAISE, url="https://www.rba.gov.au/x.html", meeting_date="2023-11-07")
    assert r["decision"] == "raise"
    assert r["change_bps"] == 25
    assert r["rate_before"] == 4.10


def test_rba_returns_none_on_unmatched():
    assert rba.parse_decision("<p>No decision here.</p>", url="https://www.rba.gov.au/x.html", meeting_date="2025-01-01") is None


def test_rba_parse_index():
    html = """<a href="/media-releases/2025/mr-25-12.html">May</a>
              <a href="/media-releases/2025/mr-25-09.html">April</a>
              <a href="/about/">about</a>"""
    links = rba.parse_index(html)
    assert links == ["/media-releases/2025/mr-25-09.html", "/media-releases/2025/mr-25-12.html"]


# ---- Fed -------------------------------------------------------------------

FED_HOLD = """<html><body><p>In support of its goals, the Committee decided to
maintain the target range for the federal funds rate at 4-1/4 to 4-1/2 percent.
</p></body></html>"""

FED_CUT = """<html><body><p>The Committee decided to lower the target range for
the federal funds rate by 1/4 percentage point to 4 to 4-1/4 percent.
</p></body></html>"""


def test_fed_parses_hold():
    r = fed.parse_decision(FED_HOLD, url="https://www.federalreserve.gov/x.htm", meeting_date="2025-05-07")
    assert r["decision"] == "hold"
    assert r["rate_after"] == 4.5
    assert r["change_bps"] == 0
    validate_records([r], "decision.schema.json")


def test_fed_parses_cut():
    r = fed.parse_decision(FED_CUT, url="https://www.federalreserve.gov/x.htm", meeting_date="2024-12-18")
    assert r["decision"] == "cut"
    assert r["rate_after"] == 4.25
    validate_records([r], "decision.schema.json")


def test_fed_fraction_parsing():
    assert fed._frac_to_float("4-1/4") == 4.25
    assert fed._frac_to_float("4-1/2") == 4.5
    assert fed._frac_to_float("4") == 4.0
    assert fed._frac_to_float("1/2") == 0.5


# ---- ABS -------------------------------------------------------------------

ABS_CPI = """<html><body><p>The Consumer Price Index (CPI) rose 0.9 per cent in
the March 2025 quarter and 2.4 per cent annually.</p></body></html>"""

ABS_UNEMP = """<html><body><p>The unemployment rate remained at 4.1 per cent in
April 2025, the ABS reported today.</p></body></html>"""


def test_abs_parses_cpi():
    r = abs_mod.parse_cpi(ABS_CPI, url="https://www.abs.gov.au/x")
    assert r["indicator"] == "cpi"
    assert r["period"] == "2025-Q1"
    assert r["value"] == 2.4
    assert r["unit"] == "percent_yoy"
    validate_records([r], "indicator.schema.json")


def test_abs_parses_unemployment():
    r = abs_mod.parse_unemployment(ABS_UNEMP, url="https://www.abs.gov.au/x")
    assert r["indicator"] == "unemployment"
    assert r["period"] == "2025-04"
    assert r["value"] == 4.1
    validate_records([r], "indicator.schema.json")
