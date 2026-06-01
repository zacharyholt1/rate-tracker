// leaderboard — members-only ranked accuracy table.
//
// The rollup data is NOT published as a static file; it's served only here,
// behind a valid Supabase JWT. So the leaderboard is genuinely gated, not just
// hidden in the UI.

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { requireUser, AuthError } from './_lib/auth.mjs';
import { buildLeaderboard } from './_lib/leaderboard.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
// Bundled with the function via netlify.toml [functions] included_files.
const DATA = join(__dirname, '..', '..', 'data');

const json = (statusCode, obj) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(obj),
});

function loadJson(name) {
  return JSON.parse(readFileSync(join(DATA, name), 'utf8'));
}

export async function handler(event) {
  if (event.httpMethod !== 'GET') return json(405, { error: 'Method not allowed' });

  try {
    requireUser(event.headers || {});
  } catch (e) {
    if (e instanceof AuthError) return json(401, { error: e.message });
    throw e;
  }

  try {
    const rollups = loadJson('rollups.json');
    const forecasters = loadJson('forecasters.json');
    return json(200, { leaderboard: buildLeaderboard(rollups, forecasters) });
  } catch (e) {
    console.error('Leaderboard error:', e.message);
    return json(500, { error: 'Could not build leaderboard' });
  }
}
