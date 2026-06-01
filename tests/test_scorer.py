"""Scorer tests — the accuracy engine must be provably correct, so this is the
most thorough suite. Covers point scoring, path on-pace tracking, bias
detection, and rollups, all with fixed `today` dates for determinism.
"""

from __future__ import annotations

from datetime import date

from scrapers import scorer
from scrapers.validate import validate_records


def decision(id, bank, mdate, dec, after, bps=None):
    return {
        "id": id, "bank": bank, "country": "AU" if bank == "RBA" else "US",
        "meeting_date": mdate, "decision": dec, "rate_after": after,
        "change_bps": bps,
        "provenance": {
            "source_url": "https://www.rba.gov.au/x", "source_name": "RBA",
            "scraped_at": "2026-01-01T00:00:00+00:00", "ingest_method": "scraper",
            "content_hash": "sha256:" + "a" * 64,
        },
    }


def point_fc(fid, forecaster, target, dec, bps=None):
    return {
        "id": fid, "forecaster_id": forecaster, "country": "AU", "bank": "RBA",
        "forecast_type": "point", "published_at": "2025-01-01",
        "prediction": {"target_event": target, "decision": dec, "change_bps": bps},
        "provenance": _prov(),
    }


def path_fc(fid, forecaster, bank, cuts, start="2025-01-01", end="2025-12-31"):
    return {
        "id": fid, "forecaster_id": forecaster,
        "country": "AU" if bank == "RBA" else "US", "bank": bank,
        "forecast_type": "path", "published_at": start,
        "prediction": {"horizon_start": start, "horizon_end": end, "cuts": cuts, "raises": 0},
        "provenance": _prov(),
    }


def _prov():
    return {
        "source_url": "https://www.afr.com/x", "source_name": "AFR",
        "scraped_at": "2026-01-01T00:00:00+00:00", "ingest_method": "scraper",
        "content_hash": "sha256:" + "b" * 64,
    }


# ---- point scoring ---------------------------------------------------------

def test_point_correct_direction_and_exact_magnitude():
    fc = point_fc("f1", "westpac", "RBA_2025-05-20", "cut", -25)
    dec = decision("RBA_2025-05-20", "RBA", "2025-05-20", "cut", 3.85, -25)
    s = scorer.score_point(fc, dec)
    assert s["status"] == "resolved"
    assert s["direction_correct"] is True
    assert s["magnitude_error_bps"] == 0
    assert s["timing_correct"] is True
    validate_records([s], "score.schema.json")


def test_point_wrong_direction():
    fc = point_fc("f1", "x", "RBA_2025-05-20", "hold", 0)
    dec = decision("RBA_2025-05-20", "RBA", "2025-05-20", "cut", 3.85, -25)
    s = scorer.score_point(fc, dec)
    assert s["direction_correct"] is False
    assert s["magnitude_error_bps"] == 25


def test_point_pending_when_meeting_not_found():
    fc = point_fc("f1", "x", "RBA_2099-01-01", "cut", -25)
    s = scorer.score_point(fc, None)
    assert s["status"] == "pending"
    assert s["direction_correct"] is None
    validate_records([s], "score.schema.json")


# ---- path scoring ----------------------------------------------------------

def test_path_resolved_on_target():
    fc = path_fc("p1", "hatzius", "FED", cuts=3)
    decs = [
        decision("FED_2025-03-01", "FED", "2025-03-01", "cut", 4.0, -25),
        decision("FED_2025-06-01", "FED", "2025-06-01", "cut", 3.75, -25),
        decision("FED_2025-09-01", "FED", "2025-09-01", "cut", 3.5, -25),
    ]
    s = scorer.score_path(fc, decs, today=date(2026, 1, 15))
    assert s["status"] == "resolved"
    assert s["delivered_so_far"] == 3
    assert s["predicted_total"] == 3
    assert s["on_pace"] is True
    validate_records([s], "score.schema.json")


def test_path_resolved_missed():
    fc = path_fc("p1", "westpac", "RBA", cuts=4)
    decs = [decision("RBA_2025-05-20", "RBA", "2025-05-20", "cut", 3.85, -25)]
    s = scorer.score_path(fc, decs, today=date(2026, 1, 15))
    assert s["status"] == "resolved"
    assert s["delivered_so_far"] == 1
    assert s["predicted_total"] == 4
    assert s["on_pace"] is False


def test_path_in_progress_on_pace():
    # 4 cuts predicted over the year; by July ~2 delivered is on pace.
    fc = path_fc("p1", "westpac", "RBA", cuts=4)
    decs = [
        decision("RBA_2025-02-18", "RBA", "2025-02-18", "cut", 4.10, -25),
        decision("RBA_2025-05-20", "RBA", "2025-05-20", "cut", 3.85, -25),
    ]
    s = scorer.score_path(fc, decs, today=date(2025, 7, 1))
    assert s["status"] == "in_progress"
    assert s["on_pace"] is True


def test_path_in_progress_behind_pace():
    # 4 predicted, by December only 1 delivered -> behind.
    fc = path_fc("p1", "westpac", "RBA", cuts=4)
    decs = [decision("RBA_2025-02-18", "RBA", "2025-02-18", "cut", 4.10, -25)]
    s = scorer.score_path(fc, decs, today=date(2025, 12, 1))
    assert s["status"] == "in_progress"
    assert s["on_pace"] is False


def test_path_pending_before_horizon():
    fc = path_fc("p1", "x", "RBA", cuts=3, start="2026-01-01", end="2026-12-31")
    s = scorer.score_path(fc, [], today=date(2025, 6, 1))
    assert s["status"] == "pending"


# ---- bias detection --------------------------------------------------------

def test_dovish_bias_when_overpredicting_cuts():
    # Predicts 4 cuts (path) but only 1 delivered -> too dovish.
    fcs = [path_fc("p1", "dove", "RBA", cuts=4)]
    decs = [decision("RBA_2025-05-20", "RBA", "2025-05-20", "cut", 3.85, -25)]
    scores = scorer.score_all(fcs, decs, today=date(2026, 1, 15))
    forecasters = [{"id": "dove", "name": "Dove", "type": "bank"}]
    rollups = scorer.build_rollups(forecasters, fcs, decs, scores, today=date(2026, 1, 15))
    assert rollups[0]["bias_label"] == "dovish"
    assert rollups[0]["bias_score"] < 0


def test_hawkish_bias_when_underpredicting_cuts_point():
    # Predicts a hold, reality was a 50bp cut -> hawkish lean.
    fcs = [point_fc("f1", "hawk", "RBA_2025-05-20", "hold", 0)]
    decs = [decision("RBA_2025-05-20", "RBA", "2025-05-20", "cut", 3.60, -50)]
    scores = scorer.score_all(fcs, decs, today=date(2026, 1, 15))
    forecasters = [{"id": "hawk", "name": "Hawk", "type": "bank"}]
    rollups = scorer.build_rollups(forecasters, fcs, decs, scores, today=date(2026, 1, 15))
    assert rollups[0]["bias_label"] == "hawkish"
    assert rollups[0]["bias_score"] > 0


def test_neutral_bias_when_accurate():
    fcs = [point_fc("f1", "ace", "RBA_2025-05-20", "cut", -25)]
    decs = [decision("RBA_2025-05-20", "RBA", "2025-05-20", "cut", 3.85, -25)]
    scores = scorer.score_all(fcs, decs, today=date(2026, 1, 15))
    forecasters = [{"id": "ace", "name": "Ace", "type": "bank"}]
    rollups = scorer.build_rollups(forecasters, fcs, decs, scores, today=date(2026, 1, 15))
    assert rollups[0]["bias_label"] == "neutral"
    assert rollups[0]["direction_win_rate"] == 1.0
    assert rollups[0]["avg_magnitude_error_bps"] == 0.0


# ---- rollups + full pipeline -----------------------------------------------

def test_rollup_win_rate_and_validation():
    fcs = [
        point_fc("f1", "mix", "RBA_2025-05-20", "cut", -25),   # correct
        point_fc("f2", "mix", "RBA_2025-07-08", "cut", -25),   # wrong (hold)
    ]
    decs = [
        decision("RBA_2025-05-20", "RBA", "2025-05-20", "cut", 3.85, -25),
        decision("RBA_2025-07-08", "RBA", "2025-07-08", "hold", 3.85, 0),
    ]
    scores = scorer.score_all(fcs, decs, today=date(2026, 1, 15))
    forecasters = [{"id": "mix", "name": "Mix", "type": "bank"}]
    rollups = scorer.build_rollups(forecasters, fcs, decs, scores, today=date(2026, 1, 15))
    assert rollups[0]["sample_size"] == 2
    assert rollups[0]["direction_win_rate"] == 0.5
    validate_records(scores, "score.schema.json")
    validate_records(rollups, "forecaster_rollup.schema.json")


def test_score_all_handles_mixed_types():
    fcs = [
        point_fc("f1", "x", "RBA_2025-05-20", "cut", -25),
        path_fc("p1", "x", "RBA", cuts=2),
    ]
    decs = [decision("RBA_2025-05-20", "RBA", "2025-05-20", "cut", 3.85, -25)]
    scores = scorer.score_all(fcs, decs, today=date(2026, 1, 15))
    assert len(scores) == 2
    validate_records(scores, "score.schema.json")


# ---- indicator scoring -----------------------------------------------------

def indicator_fc(fid, forecaster, country, indicator, period, value):
    return {
        "id": fid, "forecaster_id": forecaster, "country": country, "bank": None,
        "forecast_type": "indicator", "published_at": "2025-01-01",
        "prediction": {"indicator": indicator, "target_period": period, "value": value},
        "provenance": _prov(),
    }


def indicator_rec(country, indicator, period, value, ptype="quarterly"):
    return {
        "id": f"{country}_{indicator}_{period}", "country": country,
        "indicator": indicator, "period": period, "period_type": ptype,
        "value": value, "unit": "percent", "released_at": None,
        "provenance": {
            "source_url": "https://fred.stlouisfed.org/x", "source_name": "FRED",
            "scraped_at": "2026-01-01T00:00:00+00:00", "ingest_method": "api",
            "content_hash": "sha256:" + "c" * 64,
        },
    }


def test_indicator_resolved_error_and_signed():
    fc = indicator_fc("i1", "westpac", "AU", "cpi", "2025-Q4", 3.0)
    actual = indicator_rec("AU", "cpi", "2025-Q4", 3.2)
    s = scorer.score_indicator(fc, actual)
    assert s["status"] == "resolved"
    assert s["indicator"] == "cpi"
    assert s["predicted_value"] == 3.0
    assert s["actual_value"] == 3.2
    assert s["value_error"] == 0.2
    assert s["value_signed_error"] == -0.2   # predicted lower -> ran cold
    validate_records([s], "score.schema.json")


def test_indicator_pending_when_period_unpublished():
    fc = indicator_fc("i1", "x", "AU", "unemployment", "2099-Q1", 4.0)
    s = scorer.score_indicator(fc, None)
    assert s["status"] == "pending"
    assert s["value_error"] is None
    validate_records([s], "score.schema.json")


def test_score_all_routes_indicator_forecasts():
    fcs = [indicator_fc("i1", "x", "US", "cpi", "2025-12", 3.5)]
    inds = [indicator_rec("US", "cpi", "2025-12", 3.1, ptype="monthly")]
    scores = scorer.score_all(fcs, [], inds, today=date(2026, 1, 15))
    assert len(scores) == 1
    assert scores[0]["forecast_type"] == "indicator"
    assert scores[0]["value_error"] == 0.4
    validate_records(scores, "score.schema.json")


def test_rollup_indicator_track_and_bias():
    # Two CPI calls, both predicted high -> runs_hot.
    fcs = [
        indicator_fc("i1", "econ", "AU", "cpi", "2025-Q3", 4.0),
        indicator_fc("i2", "econ", "AU", "cpi", "2025-Q4", 4.2),
    ]
    inds = [
        indicator_rec("AU", "cpi", "2025-Q3", 3.0),
        indicator_rec("AU", "cpi", "2025-Q4", 3.0),
    ]
    scores = scorer.score_all(fcs, [], inds, today=date(2026, 1, 15))
    forecasters = [{"id": "econ", "name": "Econ", "type": "individual"}]
    rollups = scorer.build_rollups(forecasters, fcs, [], scores, today=date(2026, 1, 15))
    track = rollups[0]["indicator_accuracy"]["cpi"]
    assert track["sample_size"] == 2
    assert track["avg_error_pp"] == 1.1   # (1.0 + 1.2) / 2
    assert track["bias_label"] == "runs_hot"
    assert track["bias_score"] > 0
    validate_records(rollups, "forecaster_rollup.schema.json")
