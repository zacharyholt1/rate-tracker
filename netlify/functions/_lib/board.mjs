// Pure leaderboard/profile assembly — joins rollups, forecasters, forecasts and
// scores into the payload the gated UI renders. No IO, no import.meta, no auth,
// so it's fully unit-testable and safe under Netlify's CJS transpile.
//
// Produces three things from one fetch:
//   leaderboard — ranked rows with star rating + per-indicator tracks
//   recent      — most recently resolved calls across all forecasters
//   profiles    — per-forecaster history (predicted vs actual) for profile pages

const INDICATOR_LABELS = {
  cpi: 'Inflation (CPI)',
  core_cpi: 'Core CPI',
  pce: 'PCE',
  core_pce: 'Core PCE',
  unemployment: 'Unemployment',
};

// Human label + result for a single resolved/pending score, joined to its
// forecast for context (series, target, predicted value).
function describeCall(score, forecast, forecaster) {
  const base = {
    forecast_id: score.forecast_id,
    forecaster_id: score.forecaster_id,
    forecaster_name: forecaster ? forecaster.name : score.forecaster_id,
    forecaster_type: forecaster ? forecaster.type : null,
    forecast_type: score.forecast_type,
    status: score.status,
    published_at: forecast ? forecast.published_at : null,
    resolved_at: score.resolved_at || null,
    source_url: forecast && forecast.provenance ? forecast.provenance.source_url : null,
    excerpt: forecast ? forecast.statement_excerpt || null : null,
  };

  if (score.forecast_type === 'indicator') {
    return {
      ...base,
      label: INDICATOR_LABELS[score.indicator] || score.indicator,
      target: forecast && forecast.prediction ? forecast.prediction.target_period : null,
      predicted: score.predicted_value,
      actual: score.actual_value ?? null,
      error_pp: score.value_error ?? null,
      signed_error_pp: score.value_signed_error ?? null,
      unit: 'pp',
      result: score.status !== 'resolved' ? 'pending'
        : score.value_error == null ? 'pending'
        : score.value_error <= 0.2 ? 'hit'
        : score.value_error <= 0.5 ? 'close'
        : 'miss',
    };
  }

  // point / path rate calls
  const predicted = forecast && forecast.prediction
    ? (forecast.prediction.decision || null) : null;
  return {
    ...base,
    label: forecast && forecast.bank ? `${forecast.bank} rate call` : 'Rate call',
    target: forecast && forecast.prediction
      ? (forecast.prediction.target_event || forecast.prediction.horizon_end || null) : null,
    predicted,
    actual: null,
    error_bps: score.magnitude_error_bps ?? null,
    result: score.status !== 'resolved' ? 'pending'
      : score.direction_correct ? 'hit' : 'miss',
  };
}

// Rank by star, then quality, then win rate, then sample. Unranked sort last.
function rankRows(rows) {
  rows.sort((a, b) => {
    const st = (b.star_rating ?? -1) - (a.star_rating ?? -1);
    if (st !== 0) return st;
    const q = (b.quality_score ?? -1) - (a.quality_score ?? -1);
    if (q !== 0) return q;
    const wr = (b.direction_win_rate ?? -1) - (a.direction_win_rate ?? -1);
    if (wr !== 0) return wr;
    return (b.sample_size ?? 0) - (a.sample_size ?? 0);
  });
  rows.forEach((row, i) => { row.rank = i + 1; });
  return rows;
}

export function buildBoard(rollups, forecasters, forecasts, scores) {
  const fcById = Object.fromEntries((forecasters || []).map((f) => [f.id, f]));
  const forecastById = Object.fromEntries((forecasts || []).map((f) => [f.id, f]));
  const rollupById = Object.fromEntries((rollups || []).map((r) => [r.forecaster_id, r]));

  // ---- leaderboard rows: only forecasters that have resolved forecasts ----
  const rows = (rollups || [])
    .filter((r) => (r.sample_size || 0) > 0)
    .map((r) => {
      const fc = fcById[r.forecaster_id];
      return {
        forecaster_id: r.forecaster_id,
        name: fc ? fc.name : r.forecaster_id,
        type: fc ? fc.type : null,
        sample_size: r.sample_size,
        star_rating: r.star_rating ?? null,
        quality_score: r.quality_score ?? null,
        direction_win_rate: r.direction_win_rate ?? null,
        avg_magnitude_error_bps: r.avg_magnitude_error_bps ?? null,
        bias_score: r.bias_score ?? null,
        bias_label: r.bias_label ?? null,
        indicator_accuracy: r.indicator_accuracy || null,
      };
    });
  const leaderboard = rankRows(rows);

  // ---- recent resolved calls across everyone ----
  const resolved = (scores || []).filter((s) => s.status === 'resolved');
  const recent = resolved
    .map((s) => describeCall(s, forecastById[s.forecast_id], fcById[s.forecaster_id]))
    .sort((a, b) => String(b.resolved_at || '').localeCompare(String(a.resolved_at || '')))
    .slice(0, 12);

  // ---- per-forecaster profiles (full history, newest first) ----
  const profiles = {};
  for (const f of forecasters || []) {
    const myScores = (scores || []).filter((s) => s.forecaster_id === f.id);
    if (!myScores.length) continue;
    const history = myScores
      .map((s) => describeCall(s, forecastById[s.forecast_id], f))
      .sort((a, b) => String(b.published_at || '').localeCompare(String(a.published_at || '')));
    profiles[f.id] = {
      forecaster: {
        id: f.id, name: f.name, type: f.type,
        affiliation: f.affiliation || null,
        country_focus: f.country_focus || [],
      },
      rollup: rollupById[f.id] || null,
      history,
    };
  }

  return { leaderboard, recent, profiles, indicator_labels: INDICATOR_LABELS };
}
