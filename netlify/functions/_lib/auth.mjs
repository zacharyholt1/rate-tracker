// Supabase JWT verification — server-side, zero dependencies (Node crypto only).
//
// Supports both signing schemes Supabase uses:
//   * HS256 — legacy symmetric secret (SUPABASE_JWT_SECRET), verified locally.
//   * ES256 / RS256 — asymmetric "JWT signing keys", verified against the
//     project's public JWKS (${SUPABASE_URL}/auth/v1/.well-known/jwks.json).
//
// So a client claiming "I'm logged in" means nothing — only a valid, unexpired,
// correctly-signed token with role=authenticated is trusted. The alg is checked
// against an allowlist and alg=none is always rejected (no downgrade).
//
// Shared by scrape_url and the leaderboard function.

import crypto from 'node:crypto';

export class AuthError extends Error {}

// Only these algs are ever accepted. alg=none and anything else is rejected.
const ALLOWED_ALGS = new Set(['HS256', 'ES256', 'RS256']);

// JWKS cache: public keys rarely change, so cache by kid with a short TTL. A
// cache miss for a kid triggers a refetch (handles key rotation).
const JWKS_TTL_MS = 10 * 60 * 1000;
let _jwks = { url: null, keys: new Map(), fetchedAt: 0 };

function b64urlDecode(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  return Buffer.from(str, 'base64');
}

function decodeSegments(token) {
  if (!token || typeof token !== 'string') throw new AuthError('Missing token');
  const parts = token.split('.');
  if (parts.length !== 3) throw new AuthError('Malformed token');
  const [headerB64, payloadB64, sigB64] = parts;

  let header, payload;
  try {
    header = JSON.parse(b64urlDecode(headerB64).toString('utf8'));
  } catch {
    throw new AuthError('Malformed header');
  }
  try {
    payload = JSON.parse(b64urlDecode(payloadB64).toString('utf8'));
  } catch {
    throw new AuthError('Malformed payload');
  }
  return { header, payload, headerB64, payloadB64, sigB64 };
}

function assertClaims(claims) {
  const now = Math.floor(Date.now() / 1000);
  if (claims.exp && now >= claims.exp) throw new AuthError('Token expired');
  if (claims.nbf && now < claims.nbf) throw new AuthError('Token not yet valid');
  // Supabase authenticated users carry role "authenticated".
  if (claims.role && claims.role !== 'authenticated') {
    throw new AuthError('Not an authenticated user');
  }
  return claims;
}

// ---- HS256 (legacy shared secret) — synchronous ----------------------------

// Verify an HS256 token with the project's JWT secret. Kept synchronous and
// exported for back-compat and for projects still on the symmetric secret.
export function verifyToken(token, secret = process.env.SUPABASE_JWT_SECRET) {
  if (!secret) throw new AuthError('Server auth not configured');
  const { header, payload, headerB64, payloadB64, sigB64 } = decodeSegments(token);
  if (header.alg !== 'HS256') throw new AuthError(`Unexpected alg ${header.alg}`);

  const expected = crypto
    .createHmac('sha256', secret)
    .update(`${headerB64}.${payloadB64}`)
    .digest();
  const provided = b64urlDecode(sigB64);
  if (expected.length !== provided.length ||
      !crypto.timingSafeEqual(expected, provided)) {
    throw new AuthError('Bad signature');
  }
  return assertClaims(payload);
}

// ---- ES256 / RS256 (asymmetric via JWKS) — async ---------------------------

async function getSigningKey(kid) {
  const base = process.env.SUPABASE_URL;
  if (!base) throw new AuthError('Server auth not configured');
  const url = `${base.replace(/\/$/, '')}/auth/v1/.well-known/jwks.json`;

  const fresh = Date.now() - _jwks.fetchedAt < JWKS_TTL_MS;
  if (_jwks.url === url && fresh && _jwks.keys.has(kid)) {
    return _jwks.keys.get(kid);
  }

  let resp;
  try {
    resp = await fetch(url);
  } catch {
    throw new AuthError('Could not fetch signing keys');
  }
  if (!resp.ok) throw new AuthError('Could not fetch signing keys');

  let body;
  try {
    body = await resp.json();
  } catch {
    throw new AuthError('Malformed JWKS');
  }

  const keys = new Map();
  for (const k of body.keys || []) {
    if (k.kid) keys.set(k.kid, k);
  }
  _jwks = { url, keys, fetchedAt: Date.now() };

  if (!keys.has(kid)) throw new AuthError('Unknown signing key');
  return keys.get(kid);
}

function verifyAsymmetricSignature(header, headerB64, payloadB64, sigBuf, jwk) {
  // Build the public key from the JWK; never trust a private component.
  const pub = crypto.createPublicKey({ key: jwk, format: 'jwk' });
  const data = Buffer.from(`${headerB64}.${payloadB64}`);
  if (header.alg === 'ES256') {
    // JOSE ES256 signatures are raw R||S (IEEE P1363), not DER.
    return crypto.verify('sha256', data, { key: pub, dsaEncoding: 'ieee-p1363' }, sigBuf);
  }
  if (header.alg === 'RS256') {
    return crypto.verify('sha256', data, pub, sigBuf);
  }
  return false;
}

// Verify any supported token (HS256 locally, ES256/RS256 via JWKS). Async
// because asymmetric verification may need to fetch the JWKS.
export async function verifyTokenAsync(token) {
  const { header, payload, headerB64, payloadB64, sigB64 } = decodeSegments(token);
  if (!ALLOWED_ALGS.has(header.alg)) throw new AuthError(`Unexpected alg ${header.alg}`);

  if (header.alg === 'HS256') {
    return verifyToken(token); // uses SUPABASE_JWT_SECRET
  }

  if (!header.kid) throw new AuthError('Missing key id');
  const jwk = await getSigningKey(header.kid);
  const sigBuf = b64urlDecode(sigB64);

  let ok = false;
  try {
    ok = verifyAsymmetricSignature(header, headerB64, payloadB64, sigBuf, jwk);
  } catch {
    throw new AuthError('Bad signature');
  }
  if (!ok) throw new AuthError('Bad signature');
  return assertClaims(payload);
}

// ---- request helpers -------------------------------------------------------

// Pull a bearer token out of the Authorization header (case-insensitive).
export function bearerFromHeaders(headers) {
  const h = headers.authorization || headers.Authorization || '';
  const m = /^Bearer\s+(.+)$/i.exec(h);
  return m ? m[1].trim() : null;
}

// Convenience: verify the request's bearer token, returning claims or throwing.
// Async — supports both signing schemes.
export async function requireUser(headers) {
  const token = bearerFromHeaders(headers);
  if (!token) throw new AuthError('Sign-in required');
  return verifyTokenAsync(token);
}
