'use strict';
/**
 * Leaderboard page: GoTrue auth (sign in / sign up) then fetch the gated
 * leaderboard function with the Bearer token. All rendering via textContent.
 */
(function () {
  const authPanel  = document.getElementById('auth-panel');
  const boardPanel = document.getElementById('board-panel');
  const loading    = document.getElementById('page-loading');
  const signoutBtn = document.getElementById('signout-btn');

  const form       = document.getElementById('auth-form');
  const emailEl    = document.getElementById('auth-email');
  const passEl     = document.getElementById('auth-password');
  const statusEl   = document.getElementById('auth-status');
  const submitBtn  = document.getElementById('auth-submit');
  const titleEl    = document.getElementById('auth-title');
  const toggleText = document.getElementById('auth-toggle-text');
  const toggleLink = document.getElementById('auth-toggle-link');

  let mode = 'signin'; // or 'signup'

  function el(tag, opts = {}) {
    const e = document.createElement(tag);
    if (opts.cls) e.className = opts.cls;
    if (opts.text !== undefined) e.textContent = opts.text;
    return e;
  }
  function setStatus(msg, kind) {
    statusEl.textContent = msg;
    statusEl.className = 'submit-status' + (kind ? ' ' + kind : '');
  }

  function show(panel) {
    loading.hidden = true;
    authPanel.hidden  = panel !== 'auth';
    boardPanel.hidden = panel !== 'board';
    signoutBtn.hidden = panel !== 'board';
  }

  // ---- auth UI ----
  toggleLink.addEventListener('click', e => {
    e.preventDefault();
    mode = mode === 'signin' ? 'signup' : 'signin';
    if (mode === 'signup') {
      titleEl.textContent = 'Create an account';
      submitBtn.textContent = 'Create account';
      passEl.setAttribute('autocomplete', 'new-password');
      toggleText.textContent = 'Already have an account?';
      toggleLink.textContent = 'Sign in';
    } else {
      titleEl.textContent = 'Sign in to see the leaderboard';
      submitBtn.textContent = 'Sign in';
      passEl.setAttribute('autocomplete', 'current-password');
      toggleText.textContent = 'No account?';
      toggleLink.textContent = 'Create one';
    }
    setStatus('', '');
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    submitBtn.disabled = true;
    setStatus('Working…', '');
    try {
      if (mode === 'signup') {
        const { needsConfirmation } = await Auth.signUp(emailEl.value.trim(), passEl.value);
        if (needsConfirmation) {
          setStatus('Account created. Check your email to confirm, then sign in.', 'ok');
          submitBtn.disabled = false;
          return;
        }
      } else {
        await Auth.signIn(emailEl.value.trim(), passEl.value);
      }
      await loadBoard();
    } catch (err) {
      setStatus(err.message, 'warn');
      submitBtn.disabled = false;
    }
  });

  signoutBtn.addEventListener('click', () => { Auth.signOut(); show('auth'); });

  // ---- leaderboard ----
  async function loadBoard() {
    const token = Auth.getAccessToken();
    if (!token) { show('auth'); return; }
    show('board');
    const board = document.getElementById('board');
    board.textContent = '';

    let data;
    try {
      const resp = await fetch('/.netlify/functions/leaderboard', {
        headers: { Authorization: 'Bearer ' + token },
      });
      if (resp.status === 401) { Auth.signOut(); show('auth'); setStatus('Session expired — sign in again.', 'warn'); return; }
      data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Error ' + resp.status);
    } catch (err) {
      board.append(el('div', { cls: 'state-message', text: 'Failed to load leaderboard: ' + err.message }));
      return;
    }
    // Cache the whole payload so the profile page can reuse it without a refetch.
    try { sessionStorage.setItem('rt_board', JSON.stringify(data)); } catch (e) { /* ignore */ }
    renderRecent(data.recent || []);
    renderBoard(data.leaderboard || []);
  }

  function pct(x) { return x == null ? '—' : Math.round(x * 100) + '%'; }
  function stars(n) { return n == null ? '—' : '★★★★★'.slice(0, n) + '☆☆☆☆☆'.slice(0, 5 - n); }

  function goToProfile(id) { location.href = 'forecaster.html?id=' + encodeURIComponent(id); }

  // Horizontal strip of the most recently resolved calls.
  function renderRecent(recent) {
    const wrap = document.getElementById('recent');
    if (!wrap) return;
    wrap.textContent = '';
    if (!recent.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    wrap.append(el('div', { cls: 'section-label', text: 'Recently resolved calls' }));
    const strip = el('div', { cls: 'recent-strip' });
    for (const c of recent) {
      const card = el('div', { cls: 'recent-card result-' + (c.result || 'pending') });
      card.append(el('div', { cls: 'recent-who', text: c.forecaster_name }));
      card.append(el('div', { cls: 'recent-what', text: c.label + (c.target ? ' · ' + c.target : '') }));
      if (c.forecast_type === 'indicator') {
        card.append(el('div', { cls: 'recent-nums',
          text: 'Forecast ' + c.predicted + '% → Actual ' + (c.actual == null ? '—' : c.actual + '%') }));
        const sign = c.signed_error_pp > 0 ? '+' : '';
        card.append(el('div', { cls: 'recent-err',
          text: c.error_pp == null ? '' : sign + c.signed_error_pp + 'pp · ' + resultWord(c.result) }));
      } else {
        card.append(el('div', { cls: 'recent-nums', text: 'Called: ' + (c.predicted || '—') }));
        card.append(el('div', { cls: 'recent-err', text: resultWord(c.result) }));
      }
      card.addEventListener('click', () => goToProfile(c.forecaster_id));
      strip.append(card);
    }
    wrap.append(strip);
  }

  function resultWord(r) {
    return r === 'hit' ? '✅ Hit' : r === 'close' ? '🟡 Close' : r === 'miss' ? '❌ Miss' : 'Pending';
  }

  // Cell for an indicator track: avg error in pp + a bias pill (runs hot/cold).
  function indicatorCell(acc, key) {
    const td = el('td');
    const track = acc && acc[key];
    if (!track || track.avg_error_pp == null) { td.textContent = '—'; return td; }
    td.append(el('div', { text: track.avg_error_pp + 'pp' }));
    if (track.bias_label && track.bias_label !== 'accurate') {
      td.append(el('div', { cls: 'forecaster-type', text: track.bias_label.replace('_', ' ') }));
    }
    return td;
  }

  function renderBoard(rows) {
    const board = document.getElementById('board');
    board.textContent = '';
    if (!rows.length) { board.append(el('div', { cls: 'state-message', text: 'No resolved forecasts yet.' })); return; }

    const table = el('table', { cls: 'board-table' });
    const thead = el('thead');
    const hr = el('tr');
    ['#', 'Forecaster', 'Rating', 'Rate calls', 'Inflation', 'Unemployment', 'Bias', 'Sample']
      .forEach(h => hr.append(el('th', { text: h })));
    thead.append(hr);
    table.append(thead);

    const tbody = el('tbody');
    for (const r of rows) {
      const tr = el('tr', { cls: 'board-row' });
      tr.append(el('td', { cls: 'rank', text: '#' + r.rank }));

      const nameTd = el('td');
      const nameLink = el('span', { cls: 'forecaster-name link', text: r.name });
      nameTd.append(nameLink);
      if (r.type) nameTd.append(el('div', { cls: 'forecaster-type', text: r.type }));
      tr.append(nameTd);

      tr.append(el('td', { cls: 'stars', text: stars(r.star_rating) }));
      tr.append(el('td', { text: pct(r.direction_win_rate) }));

      tr.append(indicatorCell(r.indicator_accuracy, 'cpi'));
      tr.append(indicatorCell(r.indicator_accuracy, 'unemployment'));

      const biasTd = el('td');
      if (r.bias_label) biasTd.append(el('span', { cls: 'bias-pill ' + r.bias_label, text: r.bias_label }));
      else biasTd.textContent = '—';
      tr.append(biasTd);

      tr.append(el('td', { text: String(r.sample_size) }));

      tr.addEventListener('click', () => goToProfile(r.forecaster_id));
      tbody.append(tr);
    }
    table.append(tbody);
    board.append(table);
  }

  // ---- boot ----
  if (!Auth.isConfigured()) {
    show('auth');
    setStatus('Auth is not configured on this deployment yet.', 'warn');
    submitBtn.disabled = true;
  } else if (Auth.isSignedIn()) {
    loadBoard();
  } else {
    show('auth');
  }
})();
