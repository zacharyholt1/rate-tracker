// Tests for Supabase JWT verification.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

import {
  verifyToken,
  verifyTokenAsync,
  bearerFromHeaders,
  requireUser,
  AuthError,
} from '../../netlify/functions/_lib/auth.mjs';

const SECRET = 'test-jwt-secret-value';

function b64url(buf) {
  return Buffer.from(buf).toString('base64')
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function makeToken(claims, { secret = SECRET, alg = 'HS256' } = {}) {
  const header = b64url(JSON.stringify({ alg, typ: 'JWT' }));
  const payload = b64url(JSON.stringify(claims));
  const sig = crypto.createHmac('sha256', secret)
    .update(`${header}.${payload}`).digest();
  return `${header}.${payload}.${b64url(sig)}`;
}

const future = () => Math.floor(Date.now() / 1000) + 3600;
const past = () => Math.floor(Date.now() / 1000) - 3600;

test('accepts a valid token', () => {
  const t = makeToken({ sub: 'user-123', role: 'authenticated', exp: future() });
  const claims = verifyToken(t, SECRET);
  assert.equal(claims.sub, 'user-123');
});

test('rejects a tampered signature', () => {
  const t = makeToken({ sub: 'u', role: 'authenticated', exp: future() });
  const tampered = t.slice(0, -3) + (t.endsWith('aaa') ? 'bbb' : 'aaa');
  assert.throws(() => verifyToken(tampered, SECRET), AuthError);
});

test('rejects a token signed with a different secret', () => {
  const t = makeToken({ sub: 'u', role: 'authenticated', exp: future() }, { secret: 'other' });
  assert.throws(() => verifyToken(t, SECRET), AuthError);
});

test('rejects an expired token', () => {
  const t = makeToken({ sub: 'u', role: 'authenticated', exp: past() });
  assert.throws(() => verifyToken(t, SECRET), /expired/);
});

test('rejects a non-authenticated role', () => {
  const t = makeToken({ sub: 'u', role: 'anon', exp: future() });
  assert.throws(() => verifyToken(t, SECRET), AuthError);
});

test('rejects the alg=none downgrade', () => {
  const header = b64url(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const payload = b64url(JSON.stringify({ sub: 'u', exp: future() }));
  assert.throws(() => verifyToken(`${header}.${payload}.`, SECRET), AuthError);
});

test('rejects malformed tokens', () => {
  assert.throws(() => verifyToken('not.a.jwt', SECRET), AuthError);
  assert.throws(() => verifyToken('', SECRET), AuthError);
  assert.throws(() => verifyToken('onlyonepart', SECRET), AuthError);
});

test('bearerFromHeaders parses case-insensitively', () => {
  assert.equal(bearerFromHeaders({ authorization: 'Bearer abc' }), 'abc');
  assert.equal(bearerFromHeaders({ Authorization: 'bearer xyz' }), 'xyz');
  assert.equal(bearerFromHeaders({}), null);
});

test('requireUser rejects without a token', async () => {
  await assert.rejects(requireUser({}), AuthError);
});

test('requireUser returns claims with a valid HS256 token', async () => {
  process.env.SUPABASE_JWT_SECRET = SECRET; // requireUser reads the env secret
  const t = makeToken({ sub: 'user-9', role: 'authenticated', exp: future() });
  const claims = await requireUser({ authorization: `Bearer ${t}` });
  assert.equal(claims.sub, 'user-9');
});

// ---- ES256 / async path — verifyTokenAsync via Supabase proxy --------------
//
// verifyTokenAsync now delegates to Supabase's /auth/v1/user endpoint.
// Tests mock the fetch global to simulate Supabase responses.

function makeES256Token(claims) {
  // Minimal ES256 token: the signature is NOT verified locally any more,
  // only the alg header is inspected before proxying to Supabase.
  const { publicKey: pub, privateKey: priv } =
    crypto.generateKeyPairSync('ec', { namedCurve: 'P-256' });
  const header = b64url(JSON.stringify({ alg: 'ES256', typ: 'JWT', kid: 'k1' }));
  const payload = b64url(JSON.stringify(claims));
  const sig = crypto.sign('sha256', Buffer.from(`${header}.${payload}`),
    { key: priv, dsaEncoding: 'ieee-p1363' });
  return `${header}.${payload}.${b64url(sig)}`;
}

// Wraps a test with a mocked Supabase user endpoint.
function withMockSupabase({ userId = 'mock-user', email = 'u@test.com', ok = true, status = 200 } = {}, fn) {
  const origFetch = global.fetch;
  const origUrl = process.env.SUPABASE_URL;
  const origKey = process.env.SUPABASE_ANON_KEY;
  process.env.SUPABASE_URL = 'https://proj.supabase.co';
  process.env.SUPABASE_ANON_KEY = 'test-anon-key';
  global.fetch = async () => ({
    ok,
    status,
    json: async () => (ok ? { id: userId, email } : { error: 'invalid' }),
  });
  return Promise.resolve(fn()).finally(() => {
    global.fetch = origFetch;
    if (origUrl === undefined) delete process.env.SUPABASE_URL;
    else process.env.SUPABASE_URL = origUrl;
    if (origKey === undefined) delete process.env.SUPABASE_ANON_KEY;
    else process.env.SUPABASE_ANON_KEY = origKey;
  });
}

test('verifyTokenAsync accepts a valid ES256 token via Supabase proxy', async () => {
  await withMockSupabase({ userId: 'ec-user' }, async () => {
    const t = makeES256Token({ sub: 'ec-user', role: 'authenticated', exp: future() });
    const claims = await verifyTokenAsync(t);
    assert.equal(claims.sub, 'ec-user');
  });
});

test('verifyTokenAsync rejects when Supabase returns 401', async () => {
  await withMockSupabase({ ok: false, status: 401 }, async () => {
    const t = makeES256Token({ sub: 'x', exp: future() });
    await assert.rejects(verifyTokenAsync(t), /Invalid or expired token/);
  });
});

test('verifyTokenAsync rejects when Supabase returns 403', async () => {
  await withMockSupabase({ ok: false, status: 403 }, async () => {
    const t = makeES256Token({ sub: 'x', exp: future() });
    await assert.rejects(verifyTokenAsync(t), /Invalid or expired token/);
  });
});

test('verifyTokenAsync still rejects alg=none', async () => {
  const header = b64url(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const payload = b64url(JSON.stringify({ sub: 'u', exp: future() }));
  await assert.rejects(verifyTokenAsync(`${header}.${payload}.`), AuthError);
});

test('verifyTokenAsync falls back to HS256 when only JWT secret is set', async () => {
  const origUrl = process.env.SUPABASE_URL;
  const origKey = process.env.SUPABASE_ANON_KEY;
  delete process.env.SUPABASE_URL;
  delete process.env.SUPABASE_ANON_KEY;
  process.env.SUPABASE_JWT_SECRET = SECRET;
  try {
    const t = makeToken({ sub: 'fallback-user', role: 'authenticated', exp: future() });
    const claims = await verifyTokenAsync(t);
    assert.equal(claims.sub, 'fallback-user');
  } finally {
    if (origUrl !== undefined) process.env.SUPABASE_URL = origUrl;
    if (origKey !== undefined) process.env.SUPABASE_ANON_KEY = origKey;
  }
});
