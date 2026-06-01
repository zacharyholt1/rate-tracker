'use strict';
/**
 * Session + auth helper. Talks to Supabase GoTrue's REST API directly with
 * fetch — no SDK, so nothing external loads and the strict CSP stands. The
 * access token (a Supabase JWT) is stored under one key and sent as a Bearer
 * token to gated functions; the server verifies it, the client is never trusted.
 */
window.Auth = (function () {
  const KEY = 'rt_session';
  const cfg = window.RT_CONFIG || {};
  const configured = Boolean(cfg.SUPABASE_URL && cfg.SUPABASE_ANON_KEY);

  function isConfigured() { return configured; }

  function getSession() {
    try { return JSON.parse(localStorage.getItem(KEY) || 'null'); }
    catch { return null; }
  }

  function setSession(s) { localStorage.setItem(KEY, JSON.stringify(s)); }

  function getAccessToken() {
    const s = getSession();
    if (!s || !s.access_token) return null;
    if (s.expires_at && Date.now() / 1000 >= s.expires_at) return null; // expired
    return s.access_token;
  }

  function isSignedIn() { return getAccessToken() !== null; }

  function currentUser() {
    const s = getSession();
    return s && s.user ? s.user : null;
  }

  function signOut() { localStorage.removeItem(KEY); }

  async function _gotrue(path, body) {
    if (!configured) throw new Error('Auth is not configured on this deployment.');
    const resp = await fetch(`${cfg.SUPABASE_URL}/auth/v1${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', apikey: cfg.SUPABASE_ANON_KEY },
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.error_description || data.msg || data.error || `Error ${resp.status}`);
    }
    return data;
  }

  // Persist a GoTrue token response as our session shape.
  function _store(data) {
    if (!data.access_token) return null;
    const expires_at = data.expires_at ||
      Math.floor(Date.now() / 1000) + (data.expires_in || 3600);
    const session = {
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_at,
      user: data.user || null,
    };
    setSession(session);
    return session;
  }

  async function signIn(email, password) {
    const data = await _gotrue('/token?grant_type=password', { email, password });
    return _store(data);
  }

  async function signUp(email, password) {
    const data = await _gotrue('/signup', { email, password });
    // If email confirmation is disabled, signup returns a session; otherwise not.
    if (data.access_token) return { session: _store(data), needsConfirmation: false };
    return { session: null, needsConfirmation: true };
  }

  return {
    isConfigured, getSession, getAccessToken, isSignedIn,
    currentUser, signOut, signIn, signUp,
  };
})();
