// Tests for the leaderboard ranking/join logic (pure, no auth or IO).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildLeaderboard } from '../../netlify/functions/_lib/leaderboard.mjs';

const forecasters = [
  { id: 'a', name: 'Bank A', type: 'bank' },
  { id: 'b', name: 'Econ B', type: 'individual' },
  { id: 'c', name: 'Bank C', type: 'bank' },
];

test('joins names and ranks by win rate then error', () => {
  const rollups = [
    { forecaster_id: 'a', sample_size: 5, direction_win_rate: 0.8, avg_magnitude_error_bps: 10, bias_score: 0.0, bias_label: 'neutral' },
    { forecaster_id: 'b', sample_size: 5, direction_win_rate: 0.9, avg_magnitude_error_bps: 5, bias_score: -0.3, bias_label: 'dovish' },
    { forecaster_id: 'c', sample_size: 5, direction_win_rate: 0.8, avg_magnitude_error_bps: 4, bias_score: 0.2, bias_label: 'hawkish' },
  ];
  const board = buildLeaderboard(rollups, forecasters);
  assert.deepEqual(board.map(r => r.forecaster_id), ['b', 'c', 'a']);
  assert.equal(board[0].rank, 1);
  assert.equal(board[0].name, 'Econ B');
  // c beats a on lower magnitude error at equal win rate
  assert.equal(board[1].forecaster_id, 'c');
});

test('forecasters with a win rate outrank those without', () => {
  const rollups = [
    { forecaster_id: 'a', sample_size: 3, direction_win_rate: null, avg_magnitude_error_bps: null, bias_score: null, bias_label: null },
    { forecaster_id: 'b', sample_size: 1, direction_win_rate: 0.5, avg_magnitude_error_bps: 20, bias_score: 0, bias_label: 'neutral' },
  ];
  const board = buildLeaderboard(rollups, forecasters);
  assert.equal(board[0].forecaster_id, 'b');
  assert.equal(board[1].forecaster_id, 'a');
});

test('falls back to id when forecaster name is unknown', () => {
  const rollups = [
    { forecaster_id: 'zzz', sample_size: 1, direction_win_rate: 1, avg_magnitude_error_bps: 0, bias_score: 0, bias_label: 'neutral' },
  ];
  const board = buildLeaderboard(rollups, forecasters);
  assert.equal(board[0].name, 'zzz');
});
