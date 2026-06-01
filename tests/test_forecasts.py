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


# ---- indicator forecasts ---------------------------------------------------

INDICATOR_ARTICLE = """<p>Goldman Sachs expects US inflation to ease to 2.8 per
cent by December 2025. Westpac sees Australian unemployment rising to 4.5 per
cent in the December 2025 quarter. NAB forecasts Australian inflation at 3.2 per
cent in 2025.</p>"""


def test_extracts_indicator_forecasts():
    recs = [r for r in forecasts.extract_forecasts(
        INDICATOR_ARTICLE, url="https://www.afr.com/x", source_name="AFR",
        published_at="2025-03-01") if r["forecast_type"] == "indicator"]
    by_who = {r["forecaster_id"]: r for r in recs}
    assert by_who["goldman_sachs"]["country"] == "US"
    assert by_who["goldman_sachs"]["prediction"] == {
        "indicator": "cpi", "target_period": "2025-12", "value": 2.8}
    assert by_who["westpac"]["prediction"]["indicator"] == "unemployment"
    assert by_who["westpac"]["prediction"]["target_period"] == "2025-Q4"
    assert by_who["nab"]["prediction"]["target_period"] == "2025"
    validate_records(recs, "forecast.schema.json")


def test_drops_indicator_call_without_period():
    # No year anywhere -> can't pin a target period -> dropped.
    html = "<p>NAB sees Australian inflation around 3 per cent eventually.</p>"
    recs = [r for r in forecasts.extract_forecasts(
        html, url="https://www.afr.com/x", source_name="AFR",
        published_at="2025-03-01") if r["forecast_type"] == "indicator"]
    assert recs == []


def test_drops_indicator_call_with_ambiguous_country():
    # Sentence names neither US nor AU -> country unknown -> dropped.
    html = "<p>Citi expects inflation to be 2.5 per cent in 2025.</p>"
    recs = [r for r in forecasts.extract_forecasts(
        html, url="https://www.afr.com/x", source_name="AFR",
        published_at="2025-03-01") if r["forecast_type"] == "indicator"]
    assert recs == []
