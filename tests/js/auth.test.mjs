// Tests for Supabase JWT verification.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

import {
  verifyToken,
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

test('requireUser throws without a token', () => {
  assert.throws(() => requireUser({}), AuthError);
});

test('requireUser returns claims with a valid token', () => {
  process.env.SUPABASE_JWT_SECRET = SECRET; // requireUser reads the env secret
  const t = makeToken({ sub: 'user-9', role: 'authenticated', exp: future() });
  const claims = requireUser({ authorization: `Bearer ${t}` });
  assert.equal(claims.sub, 'user-9');
});
