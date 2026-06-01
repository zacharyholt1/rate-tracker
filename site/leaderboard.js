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
    renderBoard(data.leaderboard || []);
  }

  function pct(x) { return x == null ? '—' : Math.round(x * 100) + '%'; }

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
    ['#', 'Forecaster', 'Win rate', 'Avg error', 'Bias', 'Inflation', 'Unemployment', 'Sample']
      .forEach(h => hr.append(el('th', { text: h })));
    thead.append(hr);
    table.append(thead);

    const tbody = el('tbody');
    for (const r of rows) {
      const tr = el('tr');
      tr.append(el('td', { cls: 'rank', text: '#' + r.rank }));

      const nameTd = el('td');
      nameTd.append(el('div', { cls: 'forecaster-name', text: r.name }));
      if (r.type) nameTd.append(el('div', { cls: 'forecaster-type', text: r.type }));
      tr.append(nameTd);

      tr.append(el('td', { text: pct(r.direction_win_rate) }));
      tr.append(el('td', { text: r.avg_magnitude_error_bps == null ? '—' : r.avg_magnitude_error_bps + 'bp' }));

      const biasTd = el('td');
      if (r.bias_label) biasTd.append(el('span', { cls: 'bias-pill ' + r.bias_label, text: r.bias_label }));
      else biasTd.textContent = '—';
      tr.append(biasTd);

      // Separate indicator-accuracy tracks
      tr.append(indicatorCell(r.indicator_accuracy, 'cpi'));
      tr.append(indicatorCell(r.indicator_accuracy, 'unemployment'));

      tr.append(el('td', { text: String(r.sample_size) }));
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
