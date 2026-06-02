"""Forecast scorer — the accuracy engine.

Deterministic and replayable: given the append-only forecast + decision logs it
regenerates scores.json and rollups.json from scratch every run. Because it's a
pure function of the logs, a scoring-logic change just bumps SCORE_VERSION and
re-runs — old data is never mutated.

Two forecast types, graded on their own terms (per the product spec):

  point  — a call on one specific meeting. Graded on direction, magnitude
           (bps error), and timing.
  path   — a call over a horizon ("3 cuts this year"). Graded at horizon end,
           but with a live on-pace tracker while the year is still running.

Bias detection: a forecaster who systematically predicts tighter policy than
reality scores hawkish (+); looser than reality, dovish (-). Normalised to
[-1, 1] so point (bps) and path (moves) leans combine on one scale.
"""

from __future__ import annotations

from datetime import date

SCORE_VERSION = "0.1.0"

# Normalisation scales for the bias signal.
_BPS_SCALE = 50.0     # a 50bp systematic point error == fully one-sided
_MOVES_SCALE = 3.0    # a 3-move systematic path error == fully one-sided
_PP_SCALE = 1.0       # a 1.0pp systematic indicator error == fully one-sided
_BIAS_THRESHOLD = 0.15


def _to_date(s: str) -> date:
    return date.fromisoformat(s)


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---- point scoring ---------------------------------------------------------

def score_point(forecast: dict, decision: dict | None) -> dict:
    """Score a point forecast against its target decision (or None if the
    meeting hasn't happened / wasn't found yet)."""
    base = {
        "forecast_id": forecast["id"],
        "forecaster_id": forecast["forecaster_id"],
        "forecast_type": "point",
        "score_version": SCORE_VERSION,
        "on_pace": None,
        "delivered_so_far": None,
        "predicted_total": None,
    }
    if decision is None:
        return {**base, "status": "pending", "resolved_at": None,
                "direction_correct": None, "magnitude_error_bps": None,
                "timing_correct": None}

    pred = forecast["prediction"]
    direction_correct = pred["decision"] == decision["decision"]

    magnitude_error_bps = None
    if pred.get("change_bps") is not None and decision.get("change_bps") is not None:
        magnitude_error_bps = abs(pred["change_bps"] - decision["change_bps"])

    return {
        **base,
        "status": "resolved",
        "resolved_at": decision["meeting_date"],
        "direction_correct": direction_correct,
        # For a point call the meeting is fixed, so timing == direction.
        "timing_correct": direction_correct,
        "magnitude_error_bps": magnitude_error_bps,
    }


def _point_hawkish_lean(forecast: dict, decision: dict) -> float | None:
    """Signed, normalised hawkish lean for one resolved point forecast.
    + = predicted tighter than reality (hawkish), - = looser (dovish)."""
    pred = forecast["prediction"]
    if pred.get("change_bps") is None or decision.get("change_bps") is None:
        return None
    return _clamp((pred["change_bps"] - decision["change_bps"]) / _BPS_SCALE)


# ---- path scoring ----------------------------------------------------------

def _net_easing(decisions: list[dict]) -> int:
    """Net easing moves: count of cuts minus count of raises."""
    cuts = sum(1 for d in decisions if d["decision"] == "cut")
    raises = sum(1 for d in decisions if d["decision"] == "raise")
    return cuts - raises


def score_path(forecast: dict, decisions_in_horizon: list[dict], today: date) -> dict:
    """Score a path forecast. Resolves after the horizon; tracks on-pace while
    the horizon is still open."""
    pred = forecast["prediction"]
    start = _to_date(pred["horizon_start"])
    end = _to_date(pred["horizon_end"])

    predicted_total = (pred.get("cuts") or 0) - (pred.get("raises") or 0)
    delivered = _net_easing(decisions_in_horizon)

    base = {
        "forecast_id": forecast["id"],
        "forecaster_id": forecast["forecaster_id"],
        "forecast_type": "path",
        "score_version": SCORE_VERSION,
        "direction_correct": None,
        "magnitude_error_bps": None,
        "timing_correct": None,
        "predicted_total": predicted_total,
        "delivered_so_far": delivered,
    }

    if today < start:
        return {**base, "status": "pending", "resolved_at": None, "on_pace": None}

    if today > end:
        # Resolved: did total deliveries match the prediction?
        return {**base, "status": "resolved", "resolved_at": pred["horizon_end"],
                "on_pace": delivered == predicted_total}

    # In progress: compare deliveries to where they *should* be by now.
    span = (end - start).days or 1
    elapsed = (today - start).days
    expected_by_now = predicted_total * (elapsed / span)
    on_pace = abs(delivered - expected_by_now) <= 1.0
    return {**base, "status": "in_progress", "resolved_at": None, "on_pace": on_pace}


# ---- indicator scoring -----------------------------------------------------

def score_indicator(forecast: dict, actual: dict | None) -> dict:
    """Score an inflation/unemployment forecast against the realised figure.

    ``actual`` is the indicator record for the forecast's country+indicator+period,
    or None if that period hasn't been published yet."""
    pred = forecast["prediction"]
    base = {
        "forecast_id": forecast["id"],
        "forecaster_id": forecast["forecaster_id"],
        "forecast_type": "indicator",
        "score_version": SCORE_VERSION,
        "indicator": pred["indicator"],
        "predicted_value": pred["value"],
        # Rate-call fields don't apply.
        "direction_correct": None, "magnitude_error_bps": None,
        "timing_correct": None, "on_pace": None,
        "delivered_so_far": None, "predicted_total": None,
    }
    if actual is None:
        return {**base, "status": "pending", "resolved_at": None,
                "actual_value": None, "value_error": None,
                "value_signed_error": None}

    actual_value = actual["value"]
    signed = round(pred["value"] - actual_value, 2)
    return {
        **base,
        "status": "resolved",
        "resolved_at": actual.get("released_at") or actual["period"],
        "actual_value": actual_value,
        "value_error": abs(signed),
        "value_signed_error": signed,
    }


def _indicator_lean(score: dict) -> float | None:
    """Normalised over/under lean for a resolved indicator forecast.
    + = predicted higher than reality (ran hot), - = lower (ran cold)."""
    if score["status"] != "resolved" or score.get("value_signed_error") is None:
        return None
    return _clamp(score["value_signed_error"] / _PP_SCALE)


def _path_hawkish_lean(score: dict) -> float | None:
    """Normalised hawkish lean for a resolved path forecast.
    Predicting more easing than delivered = dovish (-)."""
    if score["status"] != "resolved":
        return None
    # actual_easing - predicted_easing: predicted more easing -> negative -> dovish
    return _clamp((score["delivered_so_far"] - score["predicted_total"]) / _MOVES_SCALE)


# ---- top-level scoring -----------------------------------------------------

def score_all(
    forecasts: list[dict],
    decisions: list[dict],
    indicators: list[dict] | None = None,
    today: date | None = None,
) -> list[dict]:
    """Produce a score for every forecast."""
    today = today or date.today()
    by_id = {d["id"]: d for d in decisions}
    # Index indicators by (country, indicator, period) for O(1) resolution.
    ind_by_key = {
        (i["country"], i["indicator"], i["period"]): i
        for i in (indicators or [])
    }

    scores = []
    for fc in forecasts:
        ftype = fc["forecast_type"]
        if ftype == "point":
            decision = by_id.get(fc["prediction"]["target_event"])
            scores.append(score_point(fc, decision))
        elif ftype == "indicator":
            pred = fc["prediction"]
            actual = ind_by_key.get((fc["country"], pred["indicator"], pred["target_period"]))
            scores.append(score_indicator(fc, actual))
        else:
            pred = fc["prediction"]
            start, end = pred["horizon_start"], pred["horizon_end"]
            in_horizon = [
                d for d in decisions
                if d["bank"] == fc["bank"] and start <= d["meeting_date"] <= end
            ]
            scores.append(score_path(fc, in_horizon, today))
    return scores


# ---- rollups (the leaderboard data) ----------------------------------------

def build_rollups(
    forecasters: list[dict],
    forecasts: list[dict],
    decisions: list[dict],
    scores: list[dict],
    today: date | None = None,
) -> list[dict]:
    """Aggregate per-forecaster accuracy + bias from resolved forecasts."""
    today = today or date.today()
    fc_by_id = {f["id"]: f for f in forecasts}
    dec_by_id = {d["id"]: d for d in decisions}
    scores_by_fc = {s["forecast_id"]: s for s in scores}

    rollups = []
    for forecaster in forecasters:
        fid = forecaster["id"]
        my_scores = [s for s in scores if s["forecaster_id"] == fid and s["status"] == "resolved"]

        point_results = [s for s in my_scores if s["forecast_type"] == "point"]
        wins = [s for s in point_results if s["direction_correct"]]
        mag_errors = [s["magnitude_error_bps"] for s in point_results if s["magnitude_error_bps"] is not None]

        # Rate bias: combine point + path leans on the same normalised scale.
        # Indicator forecasts have their own bias track (_indicator_tracks).
        leans: list[float] = []
        for s in my_scores:
            fc = fc_by_id[s["forecast_id"]]
            if s["forecast_type"] == "point":
                dec = dec_by_id.get(fc["prediction"]["target_event"])
                if dec:
                    lean = _point_hawkish_lean(fc, dec)
                    if lean is not None:
                        leans.append(lean)
            elif s["forecast_type"] == "path":
                lean = _path_hawkish_lean(s)
                if lean is not None:
                    leans.append(lean)

        bias_score = round(sum(leans) / len(leans), 3) if leans else 0.0
        if bias_score > _BIAS_THRESHOLD:
            bias_label = "hawkish"
        elif bias_score < -_BIAS_THRESHOLD:
            bias_label = "dovish"
        else:
            bias_label = "neutral"

        indicator_accuracy = _indicator_tracks(my_scores)
        win_rate = round(len(wins) / len(point_results), 3) if point_results else None

        quality, stars = _star_rating(win_rate, indicator_accuracy, len(my_scores))

        rollup = {
            "forecaster_id": fid,
            "as_of": today.isoformat(),
            "sample_size": len(my_scores),
            "direction_win_rate": win_rate,
            "avg_magnitude_error_bps": round(sum(mag_errors) / len(mag_errors), 1) if mag_errors else None,
            "bias_score": bias_score if leans else None,
            "bias_label": bias_label if leans else None,
            "quality_score": quality,
            "star_rating": stars,
            "score_version": SCORE_VERSION,
        }
        if indicator_accuracy:
            rollup["indicator_accuracy"] = indicator_accuracy
        rollups.append(rollup)
    return rollups


# Min resolved forecasts before a forecaster earns a star rating (TipRanks-style
# significance gate — keeps a single lucky call from topping the board).
_MIN_RANKED = 3
# An indicator forecast this far off (in pp) scores zero accuracy; 0pp scores 1.
_INDICATOR_ERR_FLOOR = 0.5


def _star_rating(win_rate, indicator_accuracy: dict, sample_size: int):
    """Composite quality score in [0,1] and a 1-5 star rating.

    Blends rate-call directional win rate with inflation/unemployment accuracy
    (1 - error, floored). Returns (quality_score|None, star_rating|None).
    Forecasters under the significance gate are unranked (None)."""
    parts: list[float] = []
    if win_rate is not None:
        parts.append(win_rate)
    for track in (indicator_accuracy or {}).values():
        err = track.get("avg_error_pp")
        if err is not None:
            parts.append(_clamp(1 - err / _INDICATOR_ERR_FLOOR, 0.0, 1.0))

    if not parts or sample_size < _MIN_RANKED:
        return None, None

    quality = round(sum(parts) / len(parts), 3)
    stars = int(round(quality * 4)) + 1          # 0.0 -> 1 star, 1.0 -> 5 stars
    return quality, max(1, min(5, stars))


def _indicator_tracks(my_scores: list[dict]) -> dict:
    """Per-indicator accuracy + over/under bias, as a separate leaderboard track.

    Returns {indicator: {sample_size, avg_error_pp, bias_score, bias_label}} for
    each indicator the forecaster has resolved calls on. Empty if none."""
    ind_scores = [s for s in my_scores if s["forecast_type"] == "indicator"]
    by_indicator: dict[str, list[dict]] = {}
    for s in ind_scores:
        by_indicator.setdefault(s["indicator"], []).append(s)

    tracks = {}
    for indicator, group in by_indicator.items():
        errors = [s["value_error"] for s in group if s.get("value_error") is not None]
        leans = [l for l in (_indicator_lean(s) for s in group) if l is not None]
        bias = round(sum(leans) / len(leans), 3) if leans else None
        if bias is None:
            label = None
        elif bias > _BIAS_THRESHOLD:
            label = "runs_hot"
        elif bias < -_BIAS_THRESHOLD:
            label = "runs_cold"
        else:
            label = "accurate"
        tracks[indicator] = {
            "sample_size": len(group),
            "avg_error_pp": round(sum(errors) / len(errors), 2) if errors else None,
            "bias_score": bias,
            "bias_label": label,
        }
    return tracks
