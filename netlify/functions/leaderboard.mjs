// leaderboard — members-only ranked accuracy table.
//
// The rollup data is NOT published as a static file; it's served only here,
// behind a valid Supabase JWT. So the leaderboard is genuinely gated, not just
// hidden in the UI.
//
// Robustness: the ENTIRE handler is wrapped so it can never crash the Lambda
// (which surfaces as a 502 with no log). A `?health=1` probe returns a 200
// diagnostic with NO auth and NO secrets, so deployment can be verified from a
// browser without function logs.

import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { requireUser, AuthError } from './_lib/auth.mjs';
import { buildLeaderboard } from './_lib/leaderboard.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));

// A build/version marker so the health probe can confirm which code is live.
const VERSION = '2026-06-02-bundling-fix';

const json = (statusCode, obj) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(obj),
});

// The gated data files are bundled via netlify.toml included_files. Their exact
// on-disk location depends on how the bundler lays out the function, so try a
// few candidate roots rather than assuming one.
const DATA_CANDIDATES = [
  join(__dirname, '..', '..', 'data'),
  join(__dirname, '..', '..', '..', 'data'),
  join(process.cwd(), 'data'),
];

function dataPath(name) {
  for (const root of DATA_CANDIDATES) {
    const p = join(root, name);
    if (existsSync(p)) return p;
  }
  return null;
}

function loadJson(name) {
  const p = dataPath(name);
  if (!p) throw new Error(`Data file not found in bundle: ${name}`);
  return JSON.parse(readFileSync(p, 'utf8'));
}

// No-auth, no-secret diagnostic. Lets us confirm from a browser whether this
// code is deployed, whether env vars are present, and whether data is bundled.
function health() {
  return json(200, {
    ok: true,
    version: VERSION,
    node: process.version,
    env: {
      // Presence only — never the values.
      SUPABASE_URL: Boolean(process.env.SUPABASE_URL),
      SUPABASE_ANON_KEY: Boolean(process.env.SUPABASE_ANON_KEY),
      SUPABASE_JWT_SECRET: Boolean(process.env.SUPABASE_JWT_SECRET),
    },
    data: {
      rollups: Boolean(dataPath('rollups.json')),
      forecasters: Boolean(dataPath('forecasters.json')),
    },
  });
}

export async function handler(event) {
  // Top-level guard: nothing below can escape as an unhandled crash.
  try {
    if (event.httpMethod !== 'GET') {
      return json(405, { error: 'Method not allowed' });
    }

    // Health probe — no auth, no secrets.
    // e.g. /.netlify/functions/leaderboard?health=1
    const qs = event.queryStringParameters || {};
    if (qs.health) return health();

    // 1. Require a signed-in user.
    try {
      await requireUser(event.headers || {});
    } catch (e) {
      if (e instanceof AuthError) return json(401, { error: e.message });
      console.error('Auth verification error:', e && e.stack ? e.stack : e);
      return json(500, { error: 'Auth verification failed' });
    }

    // 2. Build and return the leaderboard.
    try {
      const rollups = loadJson('rollups.json');
      const forecasters = loadJson('forecasters.json');
      return json(200, { leaderboard: buildLeaderboard(rollups, forecasters) });
    } catch (e) {
      console.error('Leaderboard build error:', e && e.stack ? e.stack : e);
      return json(500, { error: 'Could not build leaderboard' });
    }
  } catch (e) {
    // Absolute last resort — never let the function 502.
    console.error('Unhandled leaderboard error:', e && e.stack ? e.stack : e);
    return json(500, { error: 'Internal error' });
  }
}
