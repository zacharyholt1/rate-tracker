// Pure leaderboard assembly — joins rollups to forecaster names and ranks them.
// Separated from the handler so it can be unit-tested without auth or IO.

// Rank by: highest direction win rate, then lowest magnitude error, then
// larger sample (more proven). Forecasters with no resolved point calls sort
// after those that have a win rate.
export function buildLeaderboard(rollups, forecasters) {
  const nameById = Object.fromEntries(
    forecasters.map((f) => [f.id, { name: f.name, type: f.type }])
  );

  const rows = rollups.map((r) => ({
    forecaster_id: r.forecaster_id,
    name: (nameById[r.forecaster_id] || {}).name || r.forecaster_id,
    type: (nameById[r.forecaster_id] || {}).type || null,
    sample_size: r.sample_size,
    direction_win_rate: r.direction_win_rate,
    avg_magnitude_error_bps: r.avg_magnitude_error_bps,
    bias_score: r.bias_score,
    bias_label: r.bias_label,
    // Separate indicator-accuracy tracks (inflation, unemployment), passed
    // through for the leaderboard's per-indicator columns.
    indicator_accuracy: r.indicator_accuracy || null,
  }));

  rows.sort((a, b) => {
    const wr = (b.direction_win_rate ?? -1) - (a.direction_win_rate ?? -1);
    if (wr !== 0) return wr;
    const me = (a.avg_magnitude_error_bps ?? Infinity) - (b.avg_magnitude_error_bps ?? Infinity);
    if (me !== 0) return me;
    return b.sample_size - a.sample_size;
  });

  rows.forEach((row, i) => { row.rank = i + 1; });
  return rows;
}
