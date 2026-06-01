"""Forecast extractor tests — representative article phrasings -> schema-valid
forecast records, and the discipline of dropping calls that can't be resolved.
"""

from __future__ import annotations

from scrapers import forecasts
from scrapers.validate import validate_records

CALENDAR = {("RBA", "may", 2025): "RBA_2025-05-20"}

POINT_ARTICLE = """<p>In a note to clients, Westpac expects the RBA to cut the
cash rate by 25 basis points in May, citing softer inflation.</p>"""

PATH_ARTICLE = """<p>Goldman Sachs expects three cuts from the Fed in 2025 as the
labour market cools.</p>"""

NO_BANK_ARTICLE = """<p>Westpac expects the RBA to cut rates soon.</p>"""


def test_extracts_point_forecast_resolved_to_meeting():
    recs = forecasts.extract_forecasts(
        POINT_ARTICLE, url="https://www.afr.com/x", source_name="AFR",
        published_at="2025-04-10", meeting_calendar=CALENDAR, default_year=2025)
    point = [r for r in recs if r["forecast_type"] == "point"]
    assert len(point) == 1
    r = point[0]
    assert r["forecaster_id"] == "westpac"
    assert r["prediction"]["target_event"] == "RBA_2025-05-20"
    assert r["prediction"]["decision"] == "cut"
    assert r["prediction"]["change_bps"] == -25
    assert "Westpac" in r["statement_excerpt"]
    validate_records(point, "forecast.schema.json")


def test_extracts_path_forecast():
    recs = forecasts.extract_forecasts(
        PATH_ARTICLE, url="https://www.reuters.com/x", source_name="Reuters",
        published_at="2025-01-10", default_year=2025)
    path = [r for r in recs if r["forecast_type"] == "path"]
    assert len(path) == 1
    r = path[0]
    assert r["forecaster_id"] == "goldman_sachs"
    assert r["bank"] == "FED"
    assert r["prediction"]["cuts"] == 3
    assert r["prediction"]["horizon_end"] == "2025-12-31"
    validate_records(path, "forecast.schema.json")


def test_drops_point_call_without_resolvable_meeting():
    # No month named -> can't pin to a meeting -> dropped.
    recs = forecasts.extract_forecasts(
        NO_BANK_ARTICLE, url="https://www.afr.com/x", source_name="AFR",
        published_at="2025-04-10", meeting_calendar=CALENDAR, default_year=2025)
    assert [r for r in recs if r["forecast_type"] == "point"] == []


def test_ignores_unknown_forecaster():
    article = "<p>Some Random Guy expects the RBA to cut in May.</p>"
    recs = forecasts.extract_forecasts(
        article, url="https://www.afr.com/x", source_name="AFR",
        published_at="2025-04-10", meeting_calendar=CALENDAR, default_year=2025)
    assert recs == []
