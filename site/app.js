/**
 * Rate Tracker — timeline frontend.
 *
 * Security rules enforced throughout:
 *  - All user-visible text is set via textContent (never innerHTML from data).
 *  - URLs from data are validated before being used as href/src.
 *  - No eval, no new Function, no dynamic script loading.
 */

'use strict';

// ---- data loading ----------------------------------------------------------

const DATA = {
  decisions:   null,
  indicators:  null,
  forecasters: null,
  forecasts:   null,
  scores:      null,
};

async function loadAll() {
  const files = Object.keys(DATA);
  const results = await Promise.all(
    files.map(f =>
      fetch(`data/${f}.json`)
        .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    )
  );
  files.forEach((f, i) => { DATA[f] = results[i]; });
}

// ---- safe helpers ----------------------------------------------------------

/** Validate a URL is https before using it as an href. */
function safeHref(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' ? url : null;
  } catch { return null; }
}

/** Create an element with optional className and textContent. Never innerHTML. */
function el(tag, { cls, text, attrs } = {}) {
  const e = document.createElement(tag);
  if (cls)  e.className = cls;
  if (text !== undefined) e.textContent = text;
  if (attrs) Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
  return e;
}

function fmt(date) {
  return new Date(date + 'T00:00:00').toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  });
}

function monthKey(date) {
  const d = new Date(date + 'T00:00:00');
  return d.toLocaleDateString('en-AU', { month: 'long', year: 'numeric' });
}

// ---- state -----------------------------------------------------------------

let state = {
  country: 'ALL',
  showDecisions: true,
  showPaths: true,
  showIndicators: true,
};

// ---- lookup maps -----------------------------------------------------------

function buildLookups() {
  const forecasters = Object.fromEntries(DATA.forecasters.map(f => [f.id, f]));
  const scores      = Object.fromEntries(DATA.scores.map(s => [s.forecast_id, s]));

  // Group point forecasts by target_event
  const pointsByDecision = {};
  DATA.forecasts
    .filter(f => f.forecast_type === 'point')
    .forEach(f => {
      const ev = f.prediction.target_event;
      (pointsByDecision[ev] = pointsByDecision[ev] || []).push(f);
    });

  // Path forecasts by bank + country
  const pathForecasts = DATA.forecasts.filter(f => f.forecast_type === 'path');

  // Indicator forecasts (inflation / unemployment), newest call first.
  const indicatorForecasts = DATA.forecasts
    .filter(f => f.forecast_type === 'indicator')
    .sort((a, b) => b.published_at.localeCompare(a.published_at));

  return { forecasters, scores, pointsByDecision, pathForecasts, indicatorForecasts };
}

// ---- decision card ---------------------------------------------------------

function renderBps(bps, decision) {
  if (decision === 'hold' || bps === 0 || bps == null) return '—';
  return (bps > 0 ? '+' : '') + bps + 'bp';
}

function renderRateChange(decision, rateBefore, rateAfter, changeBps) {
  if (decision === 'hold') {
    return rateAfter != null ? rateAfter.toFixed(2) + '%' : 'Hold';
  }
  if (rateBefore != null && rateAfter != null) {
    return rateAfter.toFixed(2) + '% (' + renderBps(changeBps, decision) + ')';
  }
  return renderBps(changeBps, decision);
}

function resultIcon(score) {
  if (!score || score.status === 'pending') return { icon: '⏳', title: 'Pending' };
  if (score.forecast_type === 'point') {
    if (score.direction_correct === true)  return { icon: '✅', title: 'Correct direction' };
    if (score.direction_correct === false) return { icon: '❌', title: 'Wrong direction' };
  }
  if (score.forecast_type === 'path') {
    if (score.status === 'in_progress') return { icon: '📡', title: 'In progress' };
    if (score.on_pace === true)  return { icon: '✅', title: 'On pace / correct' };
    if (score.on_pace === false) return { icon: '❌', title: 'Off pace / incorrect' };
  }
  if (score.forecast_type === 'indicator') {
    if (score.value_error == null) return { icon: '⏳', title: 'Pending' };
    // Within 0.2pp = a good call; within 0.5pp = close; beyond = miss.
    if (score.value_error <= 0.2) return { icon: '✅', title: 'Accurate (≤0.2pp)' };
    if (score.value_error <= 0.5) return { icon: '🟡', title: 'Close (≤0.5pp)' };
    return { icon: '❌', title: 'Missed (>0.5pp)' };
  }
  return { icon: '—', title: '' };
}

const INDICATOR_LABELS = {
  cpi: 'Inflation (CPI)', core_cpi: 'Core inflation', pce: 'PCE',
  core_pce: 'Core PCE', unemployment: 'Unemployment',
};

// ---- indicator forecast card -----------------------------------------------

function renderIndicatorCard(fc, lookups) {
  const { forecasters, scores } = lookups;
  const f  = forecasters[fc.forecaster_id] || {};
  const sc = scores[fc.id];
  const pred = fc.prediction;

  const card = el('div', { cls: 'path-tracker' });

  const hdr = el('div', { cls: 'path-tracker-header' });
  const left = el('div');
  left.append(el('strong', { text: f.name || fc.forecaster_id }));

  const detail = el('div', { cls: 'card-meta' });
  const label = INDICATOR_LABELS[pred.indicator] || pred.indicator;
  const flag = fc.country === 'AU' ? '🇦🇺' : '🇺🇸';
  detail.textContent = `${flag} ${label} · ${pred.target_period} · forecast ${pred.value}%`;
  left.append(detail);

  const pubLine = el('div', { cls: 'card-meta', text: 'Published ' + fmt(fc.published_at) });
  left.append(pubLine);
  hdr.append(left);

  // Result badge: predicted vs actual
  if (sc) {
    const { icon: ri, title: rt } = resultIcon(sc);
    let txt, cls;
    if (sc.status !== 'resolved' || sc.actual_value == null) {
      txt = 'Pending'; cls = 'pending';
    } else {
      const errTxt = sc.value_error === 0 ? 'exact' : sc.value_error.toFixed(1) + 'pp off';
      txt = `${ri} actual ${sc.actual_value}% (${errTxt})`;
      cls = sc.value_error <= 0.2 ? 'on' : (sc.value_error <= 0.5 ? 'pending' : 'off');
    }
    const badge = el('span', { cls: `pace-badge ${cls}`, text: txt });
    badge.setAttribute('title', rt);
    hdr.append(badge);
  }
  card.append(hdr);

  if (fc.statement_excerpt) {
    card.append(el('div', { cls: 'excerpt', text: fc.statement_excerpt }));
  }
  return card;
}

function renderDecisionCard(decision, lookups) {
  const { forecasters, scores, pointsByDecision } = lookups;

  const card = el('article', { cls: `decision-card ${decision.decision}` });
  card.setAttribute('aria-label', `${decision.bank} ${decision.decision} on ${fmt(decision.meeting_date)}`);

  // ---- header (always visible) ----
  const header = el('div', { cls: 'card-header' });
  header.setAttribute('role', 'button');
  header.setAttribute('tabindex', '0');
  header.setAttribute('aria-expanded', 'false');

  const bankBadge = el('span', { cls: 'bank-badge', text: decision.bank });
  const decBadge  = el('span', { cls: `decision-badge ${decision.decision}`, text: decision.decision });

  const titleBlock = el('div', { cls: 'card-title-block' });
  const title = el('div', { cls: 'card-title' });
  title.textContent = fmt(decision.meeting_date);
  const meta = el('div', { cls: 'card-meta' });
  meta.textContent = decision.target_rate_name || '';
  titleBlock.append(title, meta);

  const rateEl = el('div', { cls: `rate-change ${decision.decision}` });
  rateEl.textContent = renderRateChange(
    decision.decision, decision.rate_before, decision.rate_after, decision.change_bps
  );

  const icon = el('span', { cls: 'expand-icon', text: '⌄' });
  icon.setAttribute('aria-hidden', 'true');

  header.append(bankBadge, decBadge, titleBlock, rateEl, icon);
  card.append(header);

  // ---- body (collapsed by default) ----
  const body = el('div', { cls: 'card-body' });
  body.setAttribute('aria-hidden', 'true');

  // Cited indicators
  if (decision.cited_indicators && Object.keys(decision.cited_indicators).length) {
    const section = el('div');
    section.append(el('div', { cls: 'section-label', text: 'Cited at this meeting' }));
    const strip = el('div', { cls: 'indicators-strip' });
    for (const [key, val] of Object.entries(decision.cited_indicators)) {
      const chip = el('div', { cls: 'indicator-chip' });
      chip.append(
        el('span', { cls: 'indicator-name', text: key.replace(/_/g, ' ') }),
        el('span', { cls: 'indicator-value', text: val != null ? val + '%' : '—' })
      );
      strip.append(chip);
    }
    section.append(strip);
    body.append(section);
  }

  // Point forecasts for this meeting
  const pointForecasts = (pointsByDecision[decision.id] || []);
  if (pointForecasts.length) {
    const section = el('div');
    section.append(el('div', { cls: 'section-label', text: 'Forecasts for this meeting' }));

    const table = el('table', { cls: 'forecasts-table' });
    table.setAttribute('aria-label', 'Forecasts');
    const thead = el('thead');
    const headRow = el('tr');
    ['Forecaster', 'Called', 'Predicted', 'Error', 'Result'].forEach(h => {
      headRow.append(el('th', { text: h }));
    });
    thead.append(headRow);
    table.append(thead);

    const tbody = el('tbody');
    for (const fc of pointForecasts) {
      const f = forecasters[fc.forecaster_id] || {};
      const sc = scores[fc.id];
      const { icon: ri, title: rt } = resultIcon(sc);

      const row = el('tr');

      const nameCell = el('td');
      const nameDiv = el('div', { cls: 'forecaster-name', text: f.name || fc.forecaster_id });
      const typeDiv = el('div', { cls: 'forecaster-type', text: f.type || '' });
      nameCell.append(nameDiv, typeDiv);

      const calledCell = el('td', { text: fmt(fc.published_at) });

      const predCell = el('td');
      const decText = fc.prediction.decision;
      const bpsText = fc.prediction.change_bps != null
        ? ' (' + renderBps(fc.prediction.change_bps, decText) + ')'
        : '';
      predCell.textContent = decText + bpsText;

      const errCell = el('td');
      if (sc && sc.magnitude_error_bps != null) {
        errCell.textContent = sc.magnitude_error_bps === 0 ? 'Exact' : sc.magnitude_error_bps + 'bp';
      } else {
        errCell.textContent = '—';
      }

      const resCell = el('td', { cls: 'result-icon' });
      const resSpan = el('span', { text: ri });
      resSpan.setAttribute('title', rt);
      resCell.append(resSpan);

      row.append(nameCell, calledCell, predCell, errCell, resCell);
      tbody.append(row);

      // Excerpt row
      if (fc.statement_excerpt) {
        const exRow = el('tr');
        const exCell = el('td');
        exCell.setAttribute('colspan', '5');
        const exDiv = el('div', { cls: 'excerpt', text: fc.statement_excerpt });
        exCell.append(exDiv);
        exRow.append(exCell);
        tbody.append(exRow);
      }
    }
    table.append(tbody);
    section.append(table);
    body.append(section);
  }

  // Source link
  if (decision.statement_url) {
    const href = safeHref(decision.statement_url);
    if (href) {
      const link = el('a', { cls: 'source-link', text: '↗ Official statement' });
      link.href = href;
      link.rel  = 'noopener noreferrer';
      link.target = '_blank';
      body.append(link);
    }
  }

  card.append(body);

  // ---- expand/collapse ----
  function toggle() {
    const expanded = card.classList.toggle('expanded');
    header.setAttribute('aria-expanded', String(expanded));
    body.setAttribute('aria-hidden', String(!expanded));
  }
  header.addEventListener('click', toggle);
  header.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });

  return card;
}

// ---- path forecast tracker card ---- (shown at top if showPaths) -----------

function renderPathCard(fc, lookups) {
  const { forecasters, scores } = lookups;
  const f  = forecasters[fc.forecaster_id] || {};
  const sc = scores[fc.id];

  const card = el('div', { cls: 'path-tracker' });

  const hdr = el('div', { cls: 'path-tracker-header' });
  const left = el('div');

  const nameSpan = el('strong', { text: f.name || fc.forecaster_id });
  left.append(nameSpan);

  const detail = el('div', { cls: 'card-meta' });
  const cuts = fc.prediction.cuts != null ? fc.prediction.cuts + ' cut' + (fc.prediction.cuts !== 1 ? 's' : '') : '';
  const raises = fc.prediction.raises != null && fc.prediction.raises > 0
    ? fc.prediction.raises + ' raise' + (fc.prediction.raises !== 1 ? 's' : '') : '';
  const endRate = fc.prediction.end_rate != null ? 'end rate ' + fc.prediction.end_rate + '%' : '';
  const parts = [fc.bank, fc.prediction.horizon_start?.slice(0,4), [cuts, raises, endRate].filter(Boolean).join(', ')].filter(Boolean);
  detail.textContent = parts.join(' · ');
  left.append(detail);

  const excSpan = el('div', { cls: 'card-meta' });
  const dateRange = fmt(fc.prediction.horizon_start) + ' → ' + fmt(fc.prediction.horizon_end);
  excSpan.textContent = 'Published ' + fmt(fc.published_at) + '  |  ' + dateRange;
  left.append(excSpan);

  hdr.append(left);

  // Status badge
  if (sc) {
    const { icon: ri, title: rt } = resultIcon(sc);
    let paceLabel, paceCls;
    if (sc.status === 'pending') { paceLabel = 'Pending'; paceCls = 'pending'; }
    else if (sc.status === 'in_progress') { paceLabel = 'In progress'; paceCls = 'pending'; }
    else if (sc.on_pace) { paceLabel = 'Correct'; paceCls = 'on'; }
    else { paceLabel = 'Missed'; paceCls = 'off'; }

    const badge = el('span', { cls: `pace-badge ${paceCls}`, text: ri + ' ' + paceLabel });
    badge.setAttribute('title', rt);
    hdr.append(badge);
  }

  card.append(hdr);

  // Progress bar
  if (sc && sc.delivered_so_far != null && sc.predicted_total != null && sc.predicted_total > 0) {
    const pct = Math.min(sc.delivered_so_far / sc.predicted_total, 1.5);
    const isOver = sc.delivered_so_far > sc.predicted_total;

    const barLabel = el('div', { cls: 'card-meta' });
    barLabel.textContent = `Delivered: ${sc.delivered_so_far} of ${sc.predicted_total} predicted`;
    card.append(barLabel);

    const track = el('div', { cls: 'progress-track' });
    const fill = el('div', { cls: `progress-fill${isOver ? ' over' : ''}` });
    fill.style.width = Math.min(pct * 100, 100) + '%';
    track.append(fill);
    card.append(track);
  }

  // Excerpt
  if (fc.statement_excerpt) {
    card.append(el('div', { cls: 'excerpt', text: fc.statement_excerpt }));
  }

  return card;
}

// ---- timeline builder ------------------------------------------------------

function buildTimeline(lookups) {
  const timeline = document.getElementById('timeline');
  timeline.setAttribute('aria-busy', 'false');
  // Clear everything including the loading spinner
  while (timeline.firstChild) timeline.removeChild(timeline.firstChild);

  // Filter decisions
  const decisions = DATA.decisions
    .filter(d => state.country === 'ALL' || d.country === state.country)
    .sort((a, b) => b.meeting_date.localeCompare(a.meeting_date));

  // Path forecasts section (if enabled)
  if (state.showPaths) {
    const pathForecasts = lookups.pathForecasts
      .filter(f => state.country === 'ALL' || f.country === state.country);

    if (pathForecasts.length) {
      const label = el('div', { cls: 'timeline-month', text: 'Annual path forecasts' });
      timeline.append(label);
      for (const fc of pathForecasts) {
        timeline.append(renderPathCard(fc, lookups));
      }
    }
  }

  // Indicator forecasts section (inflation / unemployment)
  if (state.showIndicators) {
    const indicatorForecasts = lookups.indicatorForecasts
      .filter(f => state.country === 'ALL' || f.country === state.country);

    if (indicatorForecasts.length) {
      timeline.append(el('div', { cls: 'timeline-month', text: 'Inflation & unemployment forecasts' }));
      for (const fc of indicatorForecasts) {
        timeline.append(renderIndicatorCard(fc, lookups));
      }
    }
  }

  if (!decisions.length) {
    const msg = el('div', { cls: 'state-message' });
    msg.append(
      el('div', { text: 'No decisions to show' }),
      el('div', { cls: 'sub', text: 'Try selecting a different region.' })
    );
    timeline.append(msg);
    return;
  }

  // Group by month
  let currentMonth = null;
  for (const decision of decisions) {
    const month = monthKey(decision.meeting_date);
    if (month !== currentMonth) {
      currentMonth = month;
      timeline.append(el('div', { cls: 'timeline-month', text: month }));
    }
    timeline.append(renderDecisionCard(decision, lookups));
  }
}

// ---- filters + nav ---------------------------------------------------------

function applyFilters() {
  const lookups = buildLookups();
  buildTimeline(lookups);
}

document.querySelectorAll('[data-country]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('[data-country]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.country = btn.dataset.country;
    applyFilters();
  });
});

document.querySelectorAll('[data-type]').forEach(btn => {
  btn.addEventListener('click', () => {
    btn.classList.toggle('active');
    if (btn.dataset.type === 'decisions')  state.showDecisions  = btn.classList.contains('active');
    if (btn.dataset.type === 'paths')      state.showPaths      = btn.classList.contains('active');
    if (btn.dataset.type === 'indicators') state.showIndicators = btn.classList.contains('active');
    applyFilters();
  });
});

// ---- submit-a-source modal -------------------------------------------------

(function setupSubmit() {
  const openBtn  = document.getElementById('submit-source-btn');
  const modal    = document.getElementById('submit-modal');
  const form     = document.getElementById('submit-form');
  const urlInput = document.getElementById('submit-url');
  const statusEl = document.getElementById('submit-status');
  const cancel   = document.getElementById('submit-cancel');
  const goBtn    = document.getElementById('submit-go');
  if (!openBtn || !modal) return;

  function setStatus(msg, kind) {
    statusEl.textContent = msg;            // textContent — never innerHTML
    statusEl.className = 'submit-status' + (kind ? ' ' + kind : '');
  }

  function open() {
    setStatus('', '');
    urlInput.value = '';
    modal.hidden = false;
    if (!window.Auth || !window.Auth.isSignedIn()) {
      setStatus('You need to be signed in to submit a source — sign in on the Leaderboard page.', 'warn');
      goBtn.disabled = true;
    } else {
      goBtn.disabled = false;
      urlInput.focus();
    }
  }
  function close() { modal.hidden = true; }

  openBtn.addEventListener('click', open);
  cancel.addEventListener('click', close);
  modal.addEventListener('click', e => { if (e.target === modal) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) close(); });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const token = window.Auth && window.Auth.getAccessToken();
    if (!token) { setStatus('Sign-in required.', 'warn'); return; }

    goBtn.disabled = true;
    setStatus('Submitting…', '');
    try {
      const resp = await fetch('/.netlify/functions/scrape_url', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token,
        },
        body: JSON.stringify({ url: urlInput.value.trim() }),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) {
        setStatus(data.message || 'Submitted for review.', 'ok');
        urlInput.value = '';
      } else {
        setStatus(data.error || ('Error ' + resp.status), 'warn');
      }
    } catch (err) {
      setStatus('Network error: ' + err.message, 'warn');
    } finally {
      goBtn.disabled = false;
    }
  });
})();

// ---- boot ------------------------------------------------------------------

loadAll()
  .then(applyFilters)
  .catch(err => {
    console.error('Failed to load data:', err);
    const timeline = document.getElementById('timeline');
    while (timeline.firstChild) timeline.removeChild(timeline.firstChild);
    const msg = el('div', { cls: 'state-message' });
    msg.append(
      el('div', { text: 'Failed to load data' }),
      el('div', { cls: 'sub', text: err.message })
    );
    timeline.append(msg);
  });
