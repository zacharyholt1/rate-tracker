// leaderboard — members-only ranked accuracy table.
//
// Auth is inlined; only board.mjs (pure, no IO/import.meta) is imported. The
// real 502 cause was import.meta.url being undefined under Netlify's CJS
// transpile, NOT relative imports — so a pure relative import is safe.
//
// The rollup data is NOT a static file; it is served only here, behind a valid
// Supabase JWT. A `?health=1` probe (no auth, no secrets) lets deployment be
// verified from a browser without function logs.

import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

// Relative import is safe under Netlify's CJS transpile (the 502 bug was
// import.meta.url, not relative imports). board.mjs is pure — no IO, no
// import.meta — so it bundles and loads cleanly.
import { buildBoard } from './_lib/board.mjs';

// NOTE: deliberately NO import.meta.url / fileURLToPath here. Netlify
// transpiles these .mjs functions to CommonJS, where import.meta.url is
// undefined — calling fileURLToPath(undefined) throws at MODULE LOAD time,
// which is a 502 with "No log" (the bug that defeated every prior attempt).
// Path resolution below uses process.cwd() and the Lambda task root instead.
const VERSION = '2026-06-02-board-v2';

const json = (statusCode, obj) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(obj),
});

// ---- auth (inlined) --------------------------------------------------------

class AuthError extends Error {}

function bearerFromHeaders(headers) {
  const h = (headers && (headers.authorization || headers.Authorization)) || '';
  const m = /^Bearer\s+(.+)$/i.exec(h);
  return m ? m[1].trim() : null;
}

// Validate the token by asking Supabase's own auth server. Works for any
// signing algorithm (HS256/ES256/RS256) and respects revocation. 5s timeout.
async function verifyWithSupabase(token) {
  const base = process.env.SUPABASE_URL;
  const anonKey = process.env.SUPABASE_ANON_KEY;
  if (!base || !anonKey) throw new AuthError('Server auth not configured');

  const url = `${base.replace(/\/$/, '')}/auth/v1/user`;
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 5000);
  let resp;
  try {
    resp = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, apikey: anonKey },
      signal: ac.signal,
    });
  } catch {
    throw new AuthError('Could not verify token');
  } finally {
    clearTimeout(timer);
  }

  if (resp.status === 401 || resp.status === 403) throw new AuthError('Invalid or expired token');
  if (!resp.ok) throw new AuthError('Could not verify token');

  let user;
  try {
    user = await resp.json();
  } catch {
    throw new AuthError('Could not verify token');
  }
  if (!user || !user.id) throw new AuthError('Invalid token');
  return { sub: user.id, email: user.email, role: 'authenticated' };
}

async function requireUser(headers) {
  const token = bearerFromHeaders(headers);
  if (!token) throw new AuthError('Sign-in required');
  return verifyWithSupabase(token);
}

// ---- data files (bundled via netlify.toml included_files) ------------------

// included_files preserves the repo-relative path, and the function bundle
// root in the Lambda is the working dir (/var/task). Try the most likely
// locations; whichever exists wins.
const DATA_CANDIDATES = [
  join(process.cwd(), 'data'),
  '/var/task/data',
  join(process.cwd(), 'netlify', 'functions', 'data'),
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

// ---- handler ---------------------------------------------------------------

function health() {
  return json(200, {
    ok: true,
    version: VERSION,
    node: process.version,
    env: {
      SUPABASE_URL: Boolean(process.env.SUPABASE_URL),
      SUPABASE_ANON_KEY: Boolean(process.env.SUPABASE_ANON_KEY),
      SUPABASE_JWT_SECRET: Boolean(process.env.SUPABASE_JWT_SECRET),
    },
    data: {
      rollups: Boolean(dataPath('rollups.json')),
      forecasters: Boolean(dataPath('forecasters.json')),
      forecasts: Boolean(dataPath('forecasts.json')),
      scores: Boolean(dataPath('scores.json')),
    },
  });
}

export async function handler(event) {
  try {
    if (event.httpMethod !== 'GET') return json(405, { error: 'Method not allowed' });

    const qs = event.queryStringParameters || {};
    if (qs.health) return health();

    try {
      await requireUser(event.headers || {});
    } catch (e) {
      if (e instanceof AuthError) return json(401, { error: e.message });
      console.error('Auth verification error:', e && e.stack ? e.stack : e);
      return json(500, { error: 'Auth verification failed' });
    }

    try {
      const rollups = loadJson('rollups.json');
      const forecasters = loadJson('forecasters.json');
      const forecasts = loadJson('forecasts.json');
      const scores = loadJson('scores.json');
      return json(200, buildBoard(rollups, forecasters, forecasts, scores));
    } catch (e) {
      console.error('Leaderboard build error:', e && e.stack ? e.stack : e);
      return json(500, { error: 'Could not build leaderboard' });
    }
  } catch (e) {
    console.error('Unhandled leaderboard error:', e && e.stack ? e.stack : e);
    return json(500, { error: 'Internal error' });
  }
}
