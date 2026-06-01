'use strict';
/**
 * Shared session helper. The full Supabase email/password flow lands in Step 6;
 * this exposes the small surface the rest of the app needs now. The access
 * token (a Supabase JWT) is stored under one key and sent as a Bearer token to
 * gated functions. The server verifies it — the client is never trusted.
 */
window.Auth = (function () {
  const KEY = 'rt_session';

  function getSession() {
    try { return JSON.parse(localStorage.getItem(KEY) || 'null'); }
    catch { return null; }
  }

  function getAccessToken() {
    const s = getSession();
    if (!s || !s.access_token) return null;
    if (s.expires_at && Date.now() / 1000 >= s.expires_at) return null; // expired
    return s.access_token;
  }

  function isSignedIn() {
    return getAccessToken() !== null;
  }

  function signOut() {
    localStorage.removeItem(KEY);
  }

  return { getSession, getAccessToken, isSignedIn, signOut };
})();
