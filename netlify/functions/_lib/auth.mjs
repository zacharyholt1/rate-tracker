// Supabase JWT verification — server-side, zero dependencies.
//
// Supabase issues HS256-signed access tokens to signed-in users. We verify the
// signature with the project's JWT secret (SUPABASE_JWT_SECRET, server-only env
// var) so the client claiming "I'm logged in" means nothing — only a valid,
// unexpired, correctly-signed token is trusted.
//
// Shared by scrape_url (this step) and the leaderboard function (step 6).

import crypto from 'node:crypto';

export class AuthError extends Error {}

function b64urlDecode(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  return Buffer.from(str, 'base64');
}

// Verify and decode a Supabase access token. Returns the claims, or throws.
export function verifyToken(token, secret = process.env.SUPABASE_JWT_SECRET) {
  if (!secret) throw new AuthError('Server auth not configured');
  if (!token || typeof token !== 'string') throw new AuthError('Missing token');

  const parts = token.split('.');
  if (parts.length !== 3) throw new AuthError('Malformed token');
  const [headerB64, payloadB64, sigB64] = parts;

  let header;
  try {
    header = JSON.parse(b64urlDecode(headerB64).toString('utf8'));
  } catch {
    throw new AuthError('Malformed header');
  }
  if (header.alg !== 'HS256') throw new AuthError(`Unexpected alg ${header.alg}`);

  // Recompute the signature and compare in constant time.
  const expected = crypto
    .createHmac('sha256', secret)
    .update(`${headerB64}.${payloadB64}`)
    .digest();
  const provided = b64urlDecode(sigB64);
  if (expected.length !== provided.length ||
      !crypto.timingSafeEqual(expected, provided)) {
    throw new AuthError('Bad signature');
  }

  let claims;
  try {
    claims = JSON.parse(b64urlDecode(payloadB64).toString('utf8'));
  } catch {
    throw new AuthError('Malformed payload');
  }

  const now = Math.floor(Date.now() / 1000);
  if (claims.exp && now >= claims.exp) throw new AuthError('Token expired');
  if (claims.nbf && now < claims.nbf) throw new AuthError('Token not yet valid');
  // Supabase authenticated users carry role "authenticated".
  if (claims.role && claims.role !== 'authenticated') {
    throw new AuthError('Not an authenticated user');
  }
  return claims;
}

// Pull a bearer token out of the Authorization header (case-insensitive).
export function bearerFromHeaders(headers) {
  const h = headers.authorization || headers.Authorization || '';
  const m = /^Bearer\s+(.+)$/i.exec(h);
  return m ? m[1].trim() : null;
}

// Convenience: verify the request's bearer token, returning claims or throwing.
export function requireUser(headers) {
  const token = bearerFromHeaders(headers);
  if (!token) throw new AuthError('Sign-in required');
  return verifyToken(token);
}
