// Tests for the leaderboard/profile payload assembly.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildBoard } from '../../netlify/functions/_lib/board.mjs';

const forecasters = [
  { id: 'gs', name: 'Goldman Sachs', type: 'bank', country_focus: ['US'] },
  { id: 'wp', name: 'Westpac', type: 'bank', country_focus: ['AU'] },
  { id: 'noresolved', name: 'Nobody', type: 'research', country_focus: ['US'] },
];

const rollups = [
  { forecaster_id: 'gs', sample_size: 3, star_rating: 5, quality_score: 0.9,
    direction_win_rate: 1.0, avg_magnitude_error_bps: 0, bias_score: 0, bias_label: 'neutral',
    indicator_accuracy: { cpi: { sample_size: 2, avg_error_pp: 0.1, bias_score: 0, bias_label: 'accurate' } } },
  { forecaster_id: 'wp', sample_size: 2, star_rating: 3, quality_score: 0.6,
    direction_win_rate: 0.5, avg_magnitude_error_bps: 10, bias_score: 0.2, bias_label: 'hawkish',
    indicator_accuracy: null },
  { forecaster_id: 'noresolved', sample_size: 0, star_rating: null, quality_score: null,
    direction_win_rate: null, avg_magnitude_error_bps: null, bias_score: null, bias_label: null },
];

const forecasts = [
  { id: 'gs_cpi', forecaster_id: 'gs', country: 'US', forecast_type: 'indicator',
    published_at: '2025-01-10', statement_excerpt: 'CPI 2.8%',
    prediction: { indicator: 'cpi', target_period: '2025-03', value: 2.8 },
    provenance: { source_url: 'https://example.com/gs' } },
  { id: 'gs_fed', forecaster_id: 'gs', country: 'US', bank: 'FED', forecast_type: 'point',
    published_at: '2025-04-15', statement_excerpt: 'Hold',
    prediction: { target_event: 'FED_2025-05-07', decision: 'hold' },
    provenance: { source_url: 'https://example.com/gsfed' } },
  { id: 'wp_cash', forecaster_id: 'wp', country: 'AU', bank: 'RBA', forecast_type: 'point',
    published_at: '2025-02-01', statement_excerpt: 'Cut',
    prediction: { target_event: 'RBA_2025-03-01', decision: 'cut' },
    provenance: { source_url: 'https://example.com/wp' } },
];

const scores = [
  { forecast_id: 'gs_cpi', forecaster_id: 'gs', forecast_type: 'indicator', status: 'resolved',
    indicator: 'cpi', predicted_value: 2.8, actual_value: 2.7, value_error: 0.1, value_signed_error: 0.1,
    resolved_at: '2025-03' },
  { forecast_id: 'gs_fed', forecaster_id: 'gs', forecast_type: 'point', status: 'resolved',
    direction_correct: true, magnitude_error_bps: 0, resolved_at: '2025-05-07' },
  { forecast_id: 'wp_cash', forecaster_id: 'wp', forecast_type: 'point', status: 'resolved',
    direction_correct: false, magnitude_error_bps: 25, resolved_at: '2025-03-01' },
];

test('leaderboard ranks by star then quality, excludes zero-sample forecasters', () => {
  const { leaderboard } = buildBoard(rollups, forecasters, forecasts, scores);
  assert.equal(leaderboard.length, 2);             // noresolved excluded
  assert.equal(leaderboard[0].forecaster_id, 'gs'); // 5 stars first
  assert.equal(leaderboard[0].rank, 1);
  assert.equal(leaderboard[1].forecaster_id, 'wp');
  assert.equal(leaderboard[0].star_rating, 5);
});

test('recent calls are sorted newest-first and labelled', () => {
  const { recent } = buildBoard(rollups, forecasters, forecasts, scores);
  assert.equal(recent.length, 3);
  assert.equal(recent[0].resolved_at, '2025-05-07'); // newest
  const cpi = recent.find((r) => r.forecast_id === 'gs_cpi');
  assert.equal(cpi.label, 'Inflation (CPI)');
  assert.equal(cpi.predicted, 2.8);
  assert.equal(cpi.actual, 2.7);
  assert.equal(cpi.result, 'hit'); // 0.1pp <= 0.2
});

test('indicator result thresholds: hit/close/miss', () => {
  const s = [{ forecast_id: 'gs_cpi', forecaster_id: 'gs', forecast_type: 'indicator',
    status: 'resolved', indicator: 'cpi', predicted_value: 2.8, actual_value: 3.5,
    value_error: 0.7, value_signed_error: -0.7, resolved_at: '2025-03' }];
  const { recent } = buildBoard(rollups, forecasters, forecasts, s);
  assert.equal(recent[0].result, 'miss'); // 0.7 > 0.5
});

test('profiles carry full per-forecaster history and rollup', () => {
  const { profiles } = buildBoard(rollups, forecasters, forecasts, scores);
  assert.ok(profiles.gs);
  assert.equal(profiles.gs.forecaster.name, 'Goldman Sachs');
  assert.equal(profiles.gs.history.length, 2);
  assert.equal(profiles.gs.history[0].published_at, '2025-04-15'); // newest first
  assert.equal(profiles.gs.rollup.star_rating, 5);
  assert.ok(!profiles.noresolved); // no scores -> no profile
});

test('rate call describes direction + result', () => {
  const { profiles } = buildBoard(rollups, forecasters, forecasts, scores);
  const fed = profiles.gs.history.find((h) => h.forecast_id === 'gs_fed');
  assert.equal(fed.predicted, 'hold');
  assert.equal(fed.result, 'hit');
  const cash = profiles.wp.history.find((h) => h.forecast_id === 'wp_cash');
  assert.equal(cash.result, 'miss');
  assert.equal(cash.error_bps, 25);
});
