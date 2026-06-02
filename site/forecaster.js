'use strict';
/**
 * Forecaster profile page. Reads ?id= and renders that forecaster's track
 * record: headline rating, per-series scorecards, an accuracy-over-time
 * sparkline, and the full forecast history (predicted vs actual).
 *
 * Data comes from the gated leaderboard function (same payload as the board).
 * We reuse the sessionStorage cache the leaderboard wrote, falling back to a
 * fresh authenticated fetch. All rendering via DOM APIs (CSP-safe).
 */
(function () {
  const profileEl = document.getElementById('profile');
  const authNeeded = document.getElementById('auth-needed');
  const loading = document.getElementById('page-loading');
  const signoutBtn = document.getElementById('signout-btn');

  const params = new URLSearchParams(location.search);
  const id = params.get('id');

  let filter = 'all';

  function el(tag, opts = {}) {
    const e = document.createElement(tag);
    if (opts.cls) e.className = opts.cls;
    if (opts.text !== undefined) e.textContent = opts.text;
    return e;
  }
  function show(which) {
    loading.hidden = true;
    profileEl.hidden = which !== 'profile';
    authNeeded.hidden = which !== 'auth';
    signoutBtn.hidden = which !== 'profile';
  }
  function pct(x) { return x == null ? '—' : Math.round(x * 100) + '%'; }
  function stars(n) { return n == null ? 'Unranked' : '★★★★★'.slice(0, n) + '☆☆☆☆☆'.slice(0, 5 - n); }
  function resultWord(r) {
    return r === 'hit' ? '✅ Hit' : r === 'close' ? '🟡 Close' : r === 'miss' ? '❌ Miss' : '⏳ Pending';
  }

  if (signoutBtn) signoutBtn.addEventListener('click', () => { Auth.signOut(); location.href = 'leaderboard.html'; });

  async function getBoard() {
    // 1. Reuse the leaderboard's cached payload if present.
    try {
      const cached = sessionStorage.getItem('rt_board');
      if (cached) return JSON.parse(cached);
    } catch (e) { /* ignore */ }
    // 2. Otherwise fetch fresh (needs auth).
    const token = Auth.getAccessToken();
    if (!token) return null;
    const resp = await fetch('/.netlify/functions/leaderboard', {
      headers: { Authorization: 'Bearer ' + token },
    });
    if (resp.status === 401) { Auth.signOut(); return null; }
    if (!resp.ok) throw new Error('Error ' + resp.status);
    const data = await resp.json();
    try { sessionStorage.setItem('rt_board', JSON.stringify(data)); } catch (e) { /* ignore */ }
    return data;
  }

  // Per-call accuracy in [0,1]: indicators use 1 - error/0.5 (floored), rate
  // calls are 1 for a hit, 0 for a miss. Pending calls are skipped.
  function callAccuracy(c) {
    if (c.status !== 'resolved') return null;
    if (c.forecast_type === 'indicator') {
      if (c.error_pp == null) return null;
      return Math.max(0, Math.min(1, 1 - c.error_pp / 0.5));
    }
    return c.result === 'hit' ? 1 : 0;
  }

  // Build an SVG sparkline of running-mean accuracy over resolved calls
  // (oldest -> newest). Answers "how accurate long-term".
  function sparkline(history) {
    const resolved = history
      .filter((c) => callAccuracy(c) != null)
      .slice()
      .sort((a, b) => String(a.resolved_at || '').localeCompare(String(b.resolved_at || '')));
    if (resolved.length < 2) return null;

    const pts = [];
    let sum = 0;
    resolved.forEach((c, i) => { sum += callAccuracy(c); pts.push(sum / (i + 1)); });

    const W = 220, H = 48, pad = 4;
    const stepX = (W - pad * 2) / (pts.length - 1);
    const y = (v) => H - pad - v * (H - pad * 2);
    const coords = pts.map((v, i) => [pad + i * stepX, y(v)]);

    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('class', 'sparkline');
    svg.setAttribute('width', String(W));
    svg.setAttribute('height', String(H));

    // baseline at 50%
    const base = document.createElementNS(NS, 'line');
    base.setAttribute('x1', pad); base.setAttribute('x2', W - pad);
    base.setAttribute('y1', y(0.5)); base.setAttribute('y2', y(0.5));
    base.setAttribute('class', 'spark-base');
    svg.appendChild(base);

    const path = document.createElementNS(NS, 'polyline');
    path.setAttribute('points', coords.map((c) => c.join(',')).join(' '));
    path.setAttribute('class', 'spark-line');
    svg.appendChild(path);

    const last = coords[coords.length - 1];
    const dot = document.createElementNS(NS, 'circle');
    dot.setAttribute('cx', last[0]); dot.setAttribute('cy', last[1]); dot.setAttribute('r', '2.5');
    dot.setAttribute('class', 'spark-dot');
    svg.appendChild(dot);
    return svg;
  }

  function statTile(label, value, sub) {
    const t = el('div', { cls: 'stat-tile' });
    t.append(el('div', { cls: 'stat-label', text: label }));
    t.append(el('div', { cls: 'stat-value', text: value }));
    if (sub) t.append(el('div', { cls: 'stat-sub', text: sub }));
    return t;
  }

  function indicatorStat(label, track) {
    if (!track || track.avg_error_pp == null) return statTile(label, '—');
    const sub = track.bias_label && track.bias_label !== 'accurate'
      ? track.bias_label.replace('_', ' ') : 'on target';
    return statTile(label, track.avg_error_pp + 'pp', sub + ' · ' + track.sample_size + ' calls');
  }

  function renderHistory(container, history) {
    container.textContent = '';
    const rows = history.filter((c) => {
      if (filter === 'all') return true;
      if (filter === 'rate') return c.forecast_type !== 'indicator';
      return c.forecast_type === 'indicator' && c.label.toLowerCase().includes(filter);
    });
    if (!rows.length) { container.append(el('div', { cls: 'state-message', text: 'No forecasts in this category.' })); return; }

    const table = el('table', { cls: 'board-table' });
    const thead = el('thead');
    const hr = el('tr');
    ['Made', 'Series', 'Target', 'Predicted', 'Actual', 'Error', 'Result'].forEach((h) => hr.append(el('th', { text: h })));
    thead.append(hr); table.append(thead);

    const tbody = el('tbody');
    for (const c of rows) {
      const tr = el('tr');
      tr.append(el('td', { text: c.published_at || '—' }));
      tr.append(el('td', { text: c.label }));
      tr.append(el('td', { text: c.target || '—' }));
      if (c.forecast_type === 'indicator') {
        tr.append(el('td', { text: c.predicted + '%' }));
        tr.append(el('td', { text: c.actual == null ? '—' : c.actual + '%' }));
        const sign = c.signed_error_pp > 0 ? '+' : '';
        tr.append(el('td', { text: c.error_pp == null ? '—' : sign + c.signed_error_pp + 'pp' }));
      } else {
        tr.append(el('td', { text: c.predicted || '—' }));
        tr.append(el('td', { text: '—' }));
        tr.append(el('td', { text: c.error_bps == null ? '—' : c.error_bps + 'bp' }));
      }
      const resTd = el('td');
      resTd.append(el('span', { cls: 'result-tag ' + (c.result || 'pending'), text: resultWord(c.result) }));
      tr.append(resTd);
      tbody.append(tr);
    }
    table.append(tbody);
    container.append(table);
  }

  function render(profile) {
    const f = profile.forecaster;
    const r = profile.rollup || {};
    profileEl.textContent = '';

    // Header card
    const head = el('div', { cls: 'profile-head' });
    const titleRow = el('div', { cls: 'profile-title-row' });
    titleRow.append(el('h1', { cls: 'profile-name', text: f.name }));
    titleRow.append(el('span', { cls: 'profile-stars', text: stars(r.star_rating) }));
    head.append(titleRow);
    const metaBits = [f.type];
    if (f.affiliation) metaBits.push(f.affiliation);
    if (f.country_focus && f.country_focus.length) metaBits.push(f.country_focus.join(' / '));
    metaBits.push((r.sample_size || 0) + ' resolved forecasts');
    head.append(el('div', { cls: 'profile-meta', text: metaBits.join(' · ') }));
    profileEl.append(head);

    // Stat tiles
    const tiles = el('div', { cls: 'stat-grid' });
    tiles.append(statTile('Rate-call win rate', pct(r.direction_win_rate),
      r.bias_label ? 'leans ' + r.bias_label : null));
    const ind = r.indicator_accuracy || {};
    tiles.append(indicatorStat('Inflation error', ind.cpi));
    tiles.append(indicatorStat('Unemployment error', ind.unemployment));
    tiles.append(statTile('Quality', r.quality_score == null ? '—' : Math.round(r.quality_score * 100) + '%',
      r.star_rating == null ? 'unranked' : r.star_rating + '/5 stars'));
    profileEl.append(tiles);

    // Sparkline
    const spark = sparkline(profile.history);
    if (spark) {
      const sw = el('div', { cls: 'spark-wrap' });
      sw.append(el('div', { cls: 'section-label', text: 'Accuracy over time (running average)' }));
      sw.append(spark);
      profileEl.append(sw);
    }

    // History with filters
    profileEl.append(el('div', { cls: 'section-label history-label', text: 'Forecast history' }));
    const filters = el('div', { cls: 'filter-group profile-filters' });
    [['all', 'All'], ['rate', 'Rate calls'], ['inflation', 'Inflation'], ['unemployment', 'Unemployment']]
      .forEach(([key, label]) => {
        const b = el('button', { cls: 'filter-btn' + (key === filter ? ' active' : ''), text: label });
        b.addEventListener('click', () => {
          filter = key;
          filters.querySelectorAll('.filter-btn').forEach((x) => x.classList.remove('active'));
          b.classList.add('active');
          renderHistory(historyWrap, profile.history);
        });
        filters.append(b);
      });
    profileEl.append(filters);
    const historyWrap = el('div', { cls: 'history-wrap' });
    profileEl.append(historyWrap);
    renderHistory(historyWrap, profile.history);
  }

  // ---- boot ----
  (async function boot() {
    if (!id) { show('profile'); profileEl.textContent = ''; profileEl.append(el('div', { cls: 'state-message', text: 'No forecaster specified.' })); return; }
    if (!Auth.isConfigured() || !Auth.isSignedIn()) { show('auth'); return; }
    let board;
    try {
      board = await getBoard();
    } catch (err) {
      show('profile'); profileEl.append(el('div', { cls: 'state-message', text: 'Failed to load: ' + err.message })); return;
    }
    if (!board) { show('auth'); return; }
    const profile = (board.profiles || {})[id];
    if (!profile) {
      show('profile');
      profileEl.append(el('div', { cls: 'state-message', text: 'No track record found for this forecaster yet.' }));
      return;
    }
    show('profile');
    render(profile);
  })();
})();
