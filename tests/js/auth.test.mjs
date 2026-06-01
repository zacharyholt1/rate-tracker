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

// ---- ES256 (asymmetric, via JWKS) ------------------------------------------

const { publicKey: ecPub, privateKey: ecPriv } =
  crypto.generateKeyPairSync('ec', { namedCurve: 'P-256' });
const EC_JWK = { ...ecPub.export({ format: 'jwk' }), kid: 'test-kid', alg: 'ES256', use: 'sig' };

function makeES256(claims, { kid = 'test-kid' } = {}) {
  const header = b64url(JSON.stringify({ alg: 'ES256', typ: 'JWT', kid }));
  const payload = b64url(JSON.stringify(claims));
  const sig = crypto.sign('sha256', Buffer.from(`${header}.${payload}`),
    { key: ecPriv, dsaEncoding: 'ieee-p1363' });
  return `${header}.${payload}.${b64url(sig)}`;
}

function withMockJwks(keys, fn) {
  const origFetch = global.fetch;
  const origUrl = process.env.SUPABASE_URL;
  process.env.SUPABASE_URL = 'https://proj.supabase.co';
  global.fetch = async () => ({ ok: true, json: async () => ({ keys }) });
  return Promise.resolve(fn()).finally(() => {
    global.fetch = origFetch;
    if (origUrl === undefined) delete process.env.SUPABASE_URL;
    else process.env.SUPABASE_URL = origUrl;
  });
}

test('verifyTokenAsync accepts a valid ES256 token via JWKS', async () => {
  await withMockJwks([EC_JWK], async () => {
    const t = makeES256({ sub: 'ec-user', role: 'authenticated', exp: future() });
    const claims = await verifyTokenAsync(t);
    assert.equal(claims.sub, 'ec-user');
  });
});

test('verifyTokenAsync rejects an ES256 token with a tampered payload', async () => {
  await withMockJwks([EC_JWK], async () => {
    const t = makeES256({ sub: 'ec-user', role: 'authenticated', exp: future() });
    const parts = t.split('.');
    const forged = b64url(JSON.stringify({ sub: 'attacker', role: 'authenticated', exp: future() }));
    const tampered = `${parts[0]}.${forged}.${parts[2]}`;
    await assert.rejects(verifyTokenAsync(tampered), /Bad signature/);
  });
});

test('verifyTokenAsync rejects an unknown key id', async () => {
  await withMockJwks([EC_JWK], async () => {
    const t = makeES256({ sub: 'x', role: 'authenticated', exp: future() }, { kid: 'other-kid' });
    await assert.rejects(verifyTokenAsync(t), /Unknown signing key/);
  });
});

test('verifyTokenAsync still rejects alg=none', async () => {
  const header = b64url(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const payload = b64url(JSON.stringify({ sub: 'u', exp: future() }));
  await assert.rejects(verifyTokenAsync(`${header}.${payload}.`), AuthError);
});

test('verifyTokenAsync rejects an expired ES256 token', async () => {
  await withMockJwks([EC_JWK], async () => {
    const t = makeES256({ sub: 'x', role: 'authenticated', exp: past() });
    await assert.rejects(verifyTokenAsync(t), /expired/);
  });
});
