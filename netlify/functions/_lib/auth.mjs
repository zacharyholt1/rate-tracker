// Supabase JWT verification — server-side, zero extra dependencies.
//
// Strategy: validate tokens by calling Supabase's own /auth/v1/user endpoint.
// This is simpler and more reliable than local JWKS verification in a Lambda:
//   * Works with any alg Supabase uses (HS256, ES256, RS256) without key mgmt.
//   * Handles revoked tokens correctly (Supabase checks its own DB).
//   * No JWKS fetches that can hang and cause 502s.
//
// HS256 local verification (verifyToken) is kept for back-compat and tests.
// The primary auth path for functions is requireUser → verifyWithSupabase.

import crypto from 'node:crypto';

export class AuthError extends Error {}

const ALLOWED_ALGS = new Set(['HS256', 'ES256', 'RS256']);

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
  if (claims.role && claims.role !== 'authenticated') {
    throw new AuthError('Not an authenticated user');
  }
  return claims;
}

// ---- HS256 (legacy shared secret) — synchronous ----------------------------

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

// ---- Supabase /auth/v1/user proxy verification — async ---------------------
//
// Validates the token by calling Supabase's own auth server. Works for any
// signing algorithm Supabase uses. A 5-second timeout prevents Lambda hangs.

async function verifyWithSupabase(token) {
  const base = process.env.SUPABASE_URL;
  const anonKey = process.env.SUPABASE_ANON_KEY;
  if (!base || !anonKey) throw new AuthError('Server auth not configured');

  const url = `${base.replace(/\/$/, '')}/auth/v1/user`;
  let resp;
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 5000);
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

  if (resp.status === 401 || resp.status === 403) {
    throw new AuthError('Invalid or expired token');
  }
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

// ---- async path (used by all function handlers) ----------------------------

// Verify any Supabase token. Uses the Supabase auth server for all algs.
// Falls back to local HS256 if SUPABASE_URL/ANON_KEY are not set (e.g. tests).
export async function verifyTokenAsync(token) {
  const { header } = decodeSegments(token);
  if (!ALLOWED_ALGS.has(header.alg)) throw new AuthError(`Unexpected alg ${header.alg}`);

  // If Supabase URL + anon key are configured, use the auth server (primary).
  if (process.env.SUPABASE_URL && process.env.SUPABASE_ANON_KEY) {
    return verifyWithSupabase(token);
  }
  // Fallback: local HS256 (tests, or deployments with only JWT secret).
  if (header.alg === 'HS256') {
    return verifyToken(token);
  }
  throw new AuthError('Server auth not configured');
}

// ---- request helpers -------------------------------------------------------

export function bearerFromHeaders(headers) {
  const h = headers.authorization || headers.Authorization || '';
  const m = /^Bearer\s+(.+)$/i.exec(h);
  return m ? m[1].trim() : null;
}

export async function requireUser(headers) {
  const token = bearerFromHeaders(headers);
  if (!token) throw new AuthError('Sign-in required');
  return verifyTokenAsync(token);
}
