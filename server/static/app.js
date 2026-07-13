/* ============================================================
   DEPTH — app.js
   Vanilla JS, no build step, no external network calls.
   Chart is hand-built inline SVG (no charting library) so its
   text nodes stay directly click-to-edit and portable into export.
   ============================================================ */

(function () {
  'use strict';

  /* ---------------- constants ---------------- */
  const MONO_STACK = "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace";
  const DISPLAY_STACK = "'Inter','Helvetica Neue',Arial,sans-serif";
  const API_EXAMPLES = '/api/examples';
  const API_EXAMPLE = (id) => `/api/examples/${encodeURIComponent(id)}`;
  const API_ANALYZE = '/api/analyze';

  /* ---------------- state ---------------- */
  const state = {
    theme: 'paper',
    examples: [],
    meta: null,
    control: [],
    treatment: [],
    method: 'ks_band',
    alpha: 0.05,
    n_boot: 2000,
    datasetId: null,
    result: null,
    edits: {},        // { title, subtitle, xlabel, ylabel } — single source of truth
    themeColors: null
  };

  let activeEditor = null; // { cleanup() } for the currently-open inline text editor

  /* ---------------- tiny utils ---------------- */
  const $ = (id) => document.getElementById(id);
  const prefersReducedMotion = () =>
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function escapeXml(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&apos;');
  }
  const escapeHtml = escapeXml;

  function clamp01(v) { return Math.max(0, Math.min(1, v)); }

  function fmtInt(v) { return Number.isFinite(v) ? String(Math.round(v)) : 'n/a'; }
  function fmtSigned(v, d) {
    if (!Number.isFinite(v)) return 'n/a';
    return `${v >= 0 ? '+' : ''}${v.toFixed(d)}`;
  }
  function fmtP(v) {
    if (v === null || v === undefined || !Number.isFinite(v)) return 'n/a';
    if (v !== 0 && Math.abs(v) < 0.001) return v.toExponential(2);
    return v.toFixed(3);
  }
  function fmtAxisNum(v) {
    if (!Number.isFinite(v)) return 'n/a';
    const abs = Math.abs(v);
    if (abs === 0) return '0';
    if (abs >= 1000) return v.toFixed(0);
    if (abs >= 10) return v.toFixed(1);
    return v.toFixed(2);
  }
  function pad2(n) { return String(n).padStart(2, '0'); }
  function yyyymmdd(d) { return `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}`; }

  /* ---------------- network layer (never throws) ---------------- */
  async function apiFetch(path, opts) {
    try {
      const res = await fetch(path, opts);
      let data = null;
      try { data = await res.json(); } catch (_e) { data = null; }
      if (!res.ok || !data || data.ok === false) {
        const msg = (data && data.error) ? data.error : `Request failed (HTTP ${res.status})`;
        return { ok: false, error: msg, status: res.status };
      }
      return { ok: true, data };
    } catch (_err) {
      return { ok: false, error: 'Could not reach the DEPTH backend.', status: 0, networkError: true };
    }
  }

  /* ---------------- theme ---------------- */
  function currentThemeColors() {
    const cs = getComputedStyle(document.documentElement);
    const get = (name, fallback) => {
      const v = cs.getPropertyValue(name);
      return v && v.trim() ? v.trim() : fallback;
    };
    return {
      ink: get('--ink', '#15130F'),
      fg: get('--fg', '#15130F'),
      fgMuted: get('--fg-muted', '#5B5648'),
      accent: get('--accent', '#6C4CF1'),
      signal: get('--signal', '#F0603A'),
      paper: get('--bg', '#F7F5EF'),
      surface: get('--surface', '#FFFFFF'),
      warm: get('--warm', '#E7C9A9'),
      border: get('--border', 'rgba(21,19,15,0.14)')
    };
  }

  function applyTheme(theme) {
    const t = theme === 'depth' ? 'depth' : 'paper';
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('depth-theme', t); } catch (_e) { /* storage unavailable — non-fatal */ }
    state.theme = t;
    const btn = $('theme-toggle');
    const label = $('theme-toggle-label');
    if (btn) btn.setAttribute('aria-pressed', t === 'depth' ? 'true' : 'false');
    if (label) label.textContent = t === 'depth' ? 'Depth' : 'Paper';
    if (state.result) renderChart(); // rebuild chart with fresh resolved colors
  }

  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem('depth-theme'); } catch (_e) { /* ignore */ }
    applyTheme(saved === 'depth' ? 'depth' : 'paper');
  }

  function wireThemeToggle() {
    const btn = $('theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => applyTheme(state.theme === 'depth' ? 'paper' : 'depth'));
  }

  /* ---------------- ticker + banner ---------------- */
  function showBackendBanner(show) {
    const el = $('backend-banner');
    if (el) el.hidden = !show;
  }
  function updateTicker(patch) {
    if (patch.status !== undefined) { const el = $('ticker-status'); if (el) el.textContent = `BACKEND · ${patch.status}`; }
    if (patch.method !== undefined) { const el = $('ticker-method'); if (el) el.textContent = `METHOD · ${String(patch.method).toUpperCase()}`; }
    if (patch.alpha !== undefined) { const el = $('ticker-alpha'); if (el) el.textContent = `α · ${patch.alpha}`; }
    if (patch.dataset !== undefined) { const el = $('ticker-dataset'); if (el) el.textContent = `DATASET · ${patch.dataset}`; }
  }

  /* ---------------- examples ---------------- */
  async function loadExamples() {
    const res = await apiFetch(API_EXAMPLES);
    if (!res.ok) {
      showBackendBanner(true);
      updateTicker({ status: 'OFFLINE' });
      renderExampleCardsError();
      return;
    }
    showBackendBanner(false);
    updateTicker({ status: 'OK' });
    state.examples = Array.isArray(res.data.examples) ? res.data.examples : [];
    renderExampleCards(state.examples);
  }

  function renderExampleCardsError() {
    const wrap = $('example-cards');
    if (!wrap) return;
    wrap.innerHTML = '<p class="inline-error">Examples unavailable: the backend is not reachable. You can still paste or upload your own data below.</p>';
  }

  function renderExampleCards(examples) {
    const wrap = $('example-cards');
    if (!wrap) return;
    if (!examples.length) {
      wrap.innerHTML = '<p class="inline-error">No examples returned by the backend.</p>';
      return;
    }
    wrap.innerHTML = examples.map((ex) => `
      <button class="example-card" type="button" data-id="${escapeHtml(ex.id)}">
        <div class="example-card__top">
          <span class="example-card__name">${escapeHtml(ex.name)}</span>
          <span class="example-card__size">${escapeHtml(ex.size_label)}</span>
        </div>
        <p class="example-card__desc">${escapeHtml(ex.description || '')}</p>
        <p class="example-card__counts">n=${escapeHtml(ex.n)} · m=${escapeHtml(ex.m)}${ex.unit ? ' · ' + escapeHtml(ex.unit) : ''}</p>
      </button>
    `).join('');
    wrap.querySelectorAll('.example-card').forEach((btn) => {
      btn.addEventListener('click', () => selectExample(btn.dataset.id));
    });
  }

  function markActiveCard(id) {
    document.querySelectorAll('.example-card').forEach((btn) => {
      btn.classList.toggle('is-active', btn.dataset.id === id);
    });
  }
  function unmarkActiveCard() {
    document.querySelectorAll('.example-card').forEach((btn) => btn.classList.remove('is-active'));
  }

  async function selectExample(id) {
    clearRunError();
    closeActiveEditor();
    const res = await apiFetch(API_EXAMPLE(id));
    if (!res.ok) {
      showRunError(res.error || 'Could not load that example.');
      if (res.networkError) showBackendBanner(true);
      return;
    }
    const { meta, control, treatment } = res.data;
    markActiveCard(id);
    state.method = meta && meta.default_method === 'bootstrap' ? 'bootstrap' : 'ks_band';
    syncMethodToggleUI();
    setActiveData(control, treatment, meta, id);
    await runAnalysis();
  }

  function defaultEdits(meta) {
    const unit = meta && meta.unit ? ` (${meta.unit})` : '';
    const cLabel = (meta && meta.control_label) || 'Control';
    const tLabel = (meta && meta.treatment_label) || 'Treatment';
    return {
      title: (meta && meta.suggested_title) || `${tLabel} vs ${cLabel}`,
      subtitle: `${cLabel} (control) vs ${tLabel} (treatment)${unit}`,
      xlabel: `Control quantile (${cLabel})`,
      ylabel: `Shift Δ${unit}`
    };
  }

  function setActiveData(control, treatment, meta, datasetId) {
    state.control = control || [];
    state.treatment = treatment || [];
    state.meta = meta || {};
    state.datasetId = datasetId;
    state.edits = defaultEdits(state.meta);
    const runBtn = $('run-analysis');
    if (runBtn) runBtn.disabled = false;
    updateTicker({ dataset: `${(meta && meta.name) || datasetId} (n=${state.control.length}, m=${state.treatment.length})` });
  }

  /* ---------------- CSV parsing (client-side) ---------------- */
  function parseCSV(text) {
    const raw = String(text || '').replace(/\r\n/g, '\n').trim();
    if (!raw) throw new Error('Paste or upload some data first.');

    // Attempt 1: two delimiter-separated numeric columns (comma / tab / semicolon)
    const lines = raw.split('\n').map((l) => l.trim()).filter((l) => l.length > 0);
    const delim = /[,;\t]/;
    const delimLineCount = lines.filter((l) => delim.test(l)).length;
    if (lines.length >= 2 && delimLineCount >= lines.length * 0.6) {
      const control = [];
      const treatment = [];
      lines.forEach((line, i) => {
        const parts = line.split(delim).map((s) => s.trim()).filter((s) => s.length);
        if (parts.length < 2) return;
        const a = parseFloat(parts[0]);
        const b = parseFloat(parts[1]);
        if (!Number.isFinite(a) || !Number.isFinite(b)) {
          if (i === 0) return; // tolerate a header row
          return; // skip malformed row
        }
        control.push(a);
        treatment.push(b);
      });
      if (control.length >= 10 && treatment.length >= 10) {
        return { control, treatment };
      }
    }

    // Attempt 2: two newline-separated groups (blank line between blocks)
    const blocks = raw.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
    if (blocks.length >= 2) {
      const parseBlock = (b) => b.split('\n')
        .map((s) => s.trim().replace(/[,;]$/, ''))
        .filter(Boolean)
        .map((s) => parseFloat(s))
        .filter((n) => Number.isFinite(n));
      const control = parseBlock(blocks[0]);
      const treatment = parseBlock(blocks[1]);
      if (control.length >= 10 && treatment.length >= 10) {
        return { control, treatment };
      }
    }

    throw new Error('Could not parse this as two numeric groups. Use two comma- or tab-separated columns, or two blocks of numbers separated by a blank line; each group needs at least 10 values.');
  }

  function wireCustomData() {
    const useBtn = $('csv-use');
    const fileInput = $('csv-file');
    const pasteArea = $('csv-paste');
    if (useBtn) {
      useBtn.addEventListener('click', () => handleCSVText(pasteArea ? pasteArea.value : ''));
    }
    if (fileInput) {
      fileInput.addEventListener('change', async (e) => {
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        try {
          const text = await file.text();
          if (pasteArea) pasteArea.value = text;
          await handleCSVText(text);
        } catch (_err) {
          showCSVError('Could not read that file.');
        }
      });
    }
  }

  async function handleCSVText(text) {
    clearCSVError();
    clearRunError();
    let parsed;
    try {
      parsed = parseCSV(text);
    } catch (err) {
      showCSVError(err.message || 'Could not parse this data.');
      return;
    }
    closeActiveEditor();
    unmarkActiveCard();
    const meta = {
      id: 'custom',
      name: 'Custom data',
      size_label: 'custom',
      n: parsed.control.length,
      m: parsed.treatment.length,
      description: 'User-provided data.',
      provenance: 'User-provided data (pasted or uploaded in the browser), not one of the bundled examples.',
      unit: '',
      control_label: 'Control',
      treatment_label: 'Treatment',
      suggested_title: 'Custom dataset shift',
      default_method: 'ks_band'
    };
    state.method = 'ks_band';
    syncMethodToggleUI();
    setActiveData(parsed.control, parsed.treatment, meta, 'custom');
    await runAnalysis();
  }

  /* ---------------- method / alpha controls ---------------- */
  function syncMethodToggleUI() {
    document.querySelectorAll('.pill-toggle__option').forEach((btn) => {
      const active = btn.dataset.method === state.method;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-checked', active ? 'true' : 'false');
    });
    updateTicker({ method: state.method });
  }

  function wireMethodToggle() {
    document.querySelectorAll('.pill-toggle__option').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.dataset.method === state.method) return;
        state.method = btn.dataset.method;
        syncMethodToggleUI();
        if (state.control.length) runAnalysis();
      });
    });
  }

  function wireAlphaInput() {
    const input = $('alpha-input');
    if (!input) return;
    input.addEventListener('change', () => {
      let v = parseFloat(input.value);
      if (!Number.isFinite(v) || v <= 0 || v > 0.5) {
        v = 0.05;
        input.value = '0.05';
      }
      state.alpha = v;
      updateTicker({ alpha: v });
      if (state.control.length) runAnalysis();
    });
  }

  /* ---------------- errors ---------------- */
  function showRunError(msg) { const el = $('run-error'); if (el) { el.textContent = msg; el.hidden = false; } }
  function clearRunError() { const el = $('run-error'); if (el) { el.hidden = true; el.textContent = ''; } }
  function showCSVError(msg) { const el = $('csv-error'); if (el) { el.textContent = msg; el.hidden = false; } }
  function clearCSVError() { const el = $('csv-error'); if (el) { el.hidden = true; el.textContent = ''; } }

  function setRunLoading(loading) {
    const btn = $('run-analysis');
    if (!btn) return;
    btn.disabled = loading || !state.control.length;
    btn.textContent = loading ? 'Running…' : 'Run analysis';
  }

  /* ---------------- analysis ---------------- */
  async function runAnalysis() {
    if (!state.control.length || !state.treatment.length) return;
    clearRunError();
    setRunLoading(true);
    const body = {
      control: state.control,
      treatment: state.treatment,
      alpha: state.alpha,
      method: state.method,
      n_boot: state.n_boot,
      quantile_grid: null
    };
    const res = await apiFetch(API_ANALYZE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    setRunLoading(false);
    if (!res.ok) {
      if (res.networkError) showBackendBanner(true);
      showRunError(res.error || 'Analysis failed.');
      return;
    }
    showBackendBanner(false);
    state.result = res.data;
    renderResults(state.result);
    updateTicker({ status: 'OK', method: state.method, alpha: state.alpha });
  }

  /* ---------------- stat tiles (count-up) ---------------- */
  function countUp(el, target, formatFn, duration) {
    if (prefersReducedMotion()) { el.textContent = formatFn(target); return; }
    const start = performance.now();
    function frame(now) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const val = target * eased;
      el.textContent = formatFn(val);
      if (t < 1) requestAnimationFrame(frame);
      else el.textContent = formatFn(target);
    }
    requestAnimationFrame(frame);
  }

  function renderStatTiles(result) {
    const setTile = (key, target, formatFn) => {
      const el = document.querySelector(`[data-stat="${key}"]`);
      if (!el) return;
      if (!Number.isFinite(target)) { el.textContent = formatFn(target); return; }
      countUp(el, target, formatFn, 700);
    };
    setTile('n', result.n, fmtInt);
    setTile('m', result.m, fmtInt);
    setTile('mean_diff', result.mean_diff, (v) => fmtSigned(v, 3));
    setTile('median_shift', result.median_shift, (v) => fmtSigned(v, 3));
    setTile('welch_p', result.welch_p, fmtP);
    setTile('ks_p', result.ks_p, fmtP);

    const chip = $('verdict-chip');
    if (chip) {
      chip.textContent = result.any_significant ? 'Shift detected' : 'No shift detected';
      chip.classList.toggle('is-significant', !!result.any_significant);
      chip.classList.toggle('is-null', !result.any_significant);
    }
  }

  /* ---------------- plain-language callout ---------------- */
  // Display-only: merge significant regions separated by less than `gapTol`
  // on the quantile axis so prose/lists don't enumerate band-flicker
  // fragments ("92-92%, 92-92%"). The chart itself keeps the raw regions.
  function mergeRegionsForDisplay(regions, gapTol) {
    gapTol = gapTol === undefined ? 0.01 : gapTol;
    const rs = (Array.isArray(regions) ? regions : [])
      .map((r) => [Number(r[0]), Number(r[1])])
      .filter((r) => Number.isFinite(r[0]) && Number.isFinite(r[1]))
      .sort((a, b) => a[0] - b[0]);
    const out = [];
    rs.forEach((r) => {
      const last = out[out.length - 1];
      if (last && r[0] - last[1] <= gapTol) last[1] = Math.max(last[1], r[1]);
      else out.push([r[0], r[1]]);
    });
    return out;
  }

  function fmtRegionPct(r) {
    const a = Math.round(r[0] * 100);
    const b = Math.round(r[1] * 100);
    return a === b ? `${a}%` : `${a}–${b}%`;
  }

  function computeCallout(result, meta) {
    meta = meta || {};
    result = result || {};
    const cLabel = meta.control_label || 'Control';
    const tLabel = meta.treatment_label || 'Treatment';
    const unit = meta.unit ? ` ${meta.unit}` : '';
    const alpha = Number.isFinite(result.alpha) ? result.alpha : 0.05;
    const regions = mergeRegionsForDisplay(result.significant_regions);

    if (!result.any_significant || !regions.length) {
      return `Across the full distribution, ${tLabel} and ${cLabel} do not reliably differ at α=${alpha}. Whatever gap appears in the mean (Δ=${fmtSigned(result.mean_diff, 3)}${unit}) is not supported by any quantile range the shift function can identify.`;
    }

    const curve = Array.isArray(result.curve) ? result.curve : [];
    let best = null;
    curve.forEach((p) => {
      if (p && p.significant && Number.isFinite(p.delta)) {
        if (!best || Math.abs(p.delta) > Math.abs(best.delta)) best = p;
      }
    });

    const shown = regions.slice(0, 3);
    let regionStr = shown.map(fmtRegionPct).join(', ');
    if (regions.length > 3) regionStr += ` (and ${regions.length - 3} more)`;
    const direction = best ? (best.delta > 0 ? 'higher' : 'lower') : 'different';
    const magNum = best ? Math.abs(best.delta).toLocaleString('en-GB',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : null;
    const magnitude = magNum ? `${magNum}${unit}` : 'a measurable amount';

    // "the <label> distribution" keeps the sentence grammatical whatever
    // the label's number; a single merged point gets "at", ranges "between".
    const single = regions.length === 1 &&
      Math.round(regions[0][0] * 100) === Math.round(regions[0][1] * 100);
    if (single) {
      return `At the ${regionStr} percentile of ${cLabel}, the ${tLabel} distribution is ${magnitude} ${direction}. The overall mean (Δ=${fmtSigned(result.mean_diff, 3)}${unit}) obscures this, because it averages across the entire range.`;
    }
    return `Between the ${regionStr} percentiles of ${cLabel}, the ${tLabel} distribution runs as much as ${magnitude} ${direction}. The overall mean (Δ=${fmtSigned(result.mean_diff, 3)}${unit}) obscures this pattern, because it averages across the entire range.`;
  }

  function renderProvenance() {
    const el = $('provenance');
    if (!el) return;
    if (state.meta && state.meta.provenance) {
      el.textContent = `Source: ${state.meta.provenance}`;
    } else {
      el.textContent = 'Source: user-provided data.';
    }
  }

  function renderResults(result) {
    const empty = $('results-empty');
    const content = $('results-content');
    if (empty) empty.hidden = true;
    if (content) content.hidden = false;
    renderStatTiles(result);
    renderChart();
    const calloutBody = $('callout-body');
    if (calloutBody) calloutBody.textContent = computeCallout(result, state.meta || {});
    renderProvenance();
    const dl = $('download-report');
    if (dl) dl.disabled = false;
  }

  /* ---------------- chart geometry + SVG string builder ----------------
     Pure function of (curve, meta, edits, result, colors) so it can be
     reused identically for the live chart AND the exported report, and
     called directly by QA with a mock state. Colors are baked in as
     concrete values (not CSS var() refs) so the exported file needs no
     external stylesheet. */
  function computeYDomain(curve) {
    const vals = [0];
    curve.forEach((p) => {
      if (Number.isFinite(p.delta)) vals.push(p.delta);
      if (Number.isFinite(p.lower)) vals.push(p.lower);
      if (Number.isFinite(p.upper)) vals.push(p.upper);
    });
    let min = Math.min.apply(null, vals);
    let max = Math.max.apply(null, vals);
    if (min === max) { min -= 1; max += 1; }
    const pad = (max - min) * 0.12;
    return { min: min - pad, max: max + pad };
  }

  function editableGroup(key, x, y, text, cls, anchor, extra) {
    anchor = anchor || 'start';
    extra = extra || '';
    // Affordance is the dotted underline alone (no pencil glyph) — the
    // aria-label carries the "editable" semantics for assistive tech.
    return `<g class="depth-editable" data-edit-key="${key}" tabindex="0" role="button" aria-label="Edit ${escapeXml(key)}">
      <text class="${cls}" x="${x}" y="${y}" text-anchor="${anchor}" ${extra}>${escapeXml(text)}</text>
      <line class="depth-editable__underline" x1="0" y1="0" x2="0" y2="0"></line>
    </g>`;
  }

  function buildChartSVGString(curve, meta, edits, result, colors) {
    curve = Array.isArray(curve) ? curve : [];
    meta = meta || {};
    edits = edits || {};
    result = result || {};
    colors = colors || currentThemeColors();

    const width = 920, height = 520;
    const marginLeft = 68, marginRight = 24, marginTop = 108, marginBottom = 56;
    const plotW = width - marginLeft - marginRight;
    const plotH = height - marginTop - marginBottom;
    const topEdgeY = marginTop;
    const bottomEdgeY = marginTop + plotH;

    const { min: yMin, max: yMax } = computeYDomain(curve);
    const ySpan = (yMax - yMin) || 1;
    const xScale = (q) => marginLeft + clamp01(q) * plotW;
    const yScale = (v) => marginTop + plotH - ((v - yMin) / ySpan) * plotH;

    const pts = curve.map((p) => ({
      q: p.q,
      x: xScale(p.q),
      yDelta: Number.isFinite(p.delta) ? yScale(p.delta) : yScale(0),
      yUpper: Number.isFinite(p.upper) ? yScale(p.upper) : topEdgeY,
      yLower: Number.isFinite(p.lower) ? yScale(p.lower) : bottomEdgeY,
      value: p.value
    }));

    const linePath = pts.length
      ? 'M ' + pts.map((p) => `${p.x.toFixed(2)},${p.yDelta.toFixed(2)}`).join(' L ')
      : '';

    const bandPath = pts.length
      ? 'M ' + pts.map((p) => `${p.x.toFixed(2)},${p.yUpper.toFixed(2)}`).join(' L ') +
        ' L ' + pts.slice().reverse().map((p) => `${p.x.toFixed(2)},${p.yLower.toFixed(2)}`).join(' L ') +
        ' Z'
      : '';

    const zeroY = yScale(0);
    const xTicks = [0, 0.2, 0.4, 0.6, 0.8, 1.0];

    function findNearest(q) {
      if (!pts.length) return null;
      let best = pts[0], bestD = Math.abs(pts[0].q - q);
      for (const p of pts) {
        const d = Math.abs(p.q - q);
        if (d < bestD) { best = p; bestD = d; }
      }
      return best;
    }

    const yTickCount = 5;
    const yTicks = Array.from({ length: yTickCount }, (_, i) => yMin + (yMax - yMin) * (i / (yTickCount - 1)));
    const sigRegions = Array.isArray(result.significant_regions) ? result.significant_regions : [];

    const title = edits.title || meta.suggested_title || 'Shift function';
    const subtitle = edits.subtitle || `${meta.control_label || 'Control'} vs ${meta.treatment_label || 'Treatment'}`;
    const xlabel = edits.xlabel || `Control quantile (${meta.control_label || 'control'})`;
    const ylabel = edits.ylabel || `Shift Δ${meta.unit ? ' (' + meta.unit + ')' : ''}`;

    const styleBlock = `<style>
      .d-bg { fill: ${colors.surface}; }
      .d-band { fill: ${colors.accent}; fill-opacity: 0.16; }
      .d-line { fill: none; stroke: ${colors.accent}; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
      .d-zero { stroke: ${colors.fgMuted}; stroke-width: 1; stroke-dasharray: 4 4; }
      .d-sig { fill: ${colors.signal}; fill-opacity: 0.18; }
      .d-axis-line { stroke: ${colors.border}; stroke-width: 1; }
      .d-tick-label { font-family: ${MONO_STACK}; font-size: 12px; fill: ${colors.fgMuted}; }
      .d-axis-label { font-family: ${DISPLAY_STACK}; font-size: 13px; font-weight: 700; fill: ${colors.fg}; }
      .d-title { font-family: ${DISPLAY_STACK}; font-size: 26px; font-weight: 800; fill: ${colors.ink}; }
      .d-subtitle { font-family: ${DISPLAY_STACK}; font-size: 14px; font-weight: 500; fill: ${colors.fgMuted}; }
      .d-secondary-label { font-family: ${MONO_STACK}; font-size: 11px; fill: ${colors.accent}; }
      .depth-editable { cursor: pointer; }
      .depth-editable:hover .depth-editable__underline,
      .depth-editable:focus-visible .depth-editable__underline { opacity: 1; }
      .depth-editable__underline { opacity: 0; stroke: ${colors.accent}; stroke-width: 1; stroke-dasharray: 2 2; transition: opacity .15s ease; }
    </style>`;

    const secondaryTicks = xTicks.map((t) => {
      const nearest = findNearest(t);
      const label = nearest && Number.isFinite(nearest.value) ? fmtAxisNum(nearest.value) : '–';
      return `<text class="d-secondary-label" x="${xScale(t).toFixed(1)}" y="${marginTop - 14}" text-anchor="middle">${escapeXml(label)}</text>`;
    }).join('');

    const yGrid = yTicks.map((v) => `
      <line class="d-axis-line" x1="${marginLeft}" y1="${yScale(v).toFixed(1)}" x2="${width - marginRight}" y2="${yScale(v).toFixed(1)}" opacity="0.5"></line>
      <text class="d-tick-label" x="${marginLeft - 10}" y="${(yScale(v) + 4).toFixed(1)}" text-anchor="end">${fmtAxisNum(v)}</text>
    `).join('');

    const sigRects = sigRegions.map((r) => `<rect class="d-sig" x="${xScale(r[0]).toFixed(1)}" y="${marginTop}" width="${Math.max(0, xScale(r[1]) - xScale(r[0])).toFixed(1)}" height="${plotH}"></rect>`).join('');

    const xTicksMarkup = xTicks.map((t) => `
      <line class="d-axis-line" x1="${xScale(t).toFixed(1)}" y1="${bottomEdgeY}" x2="${xScale(t).toFixed(1)}" y2="${bottomEdgeY + 5}"></line>
      <text class="d-tick-label" x="${xScale(t).toFixed(1)}" y="${bottomEdgeY + 20}" text-anchor="middle">${t.toFixed(1)}</text>
    `).join('');

    const midY = marginTop + plotH / 2;

    return `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" font-family="${DISPLAY_STACK}">
${styleBlock}
<rect class="d-bg" x="0" y="0" width="${width}" height="${height}" rx="0"></rect>
${editableGroup('title', marginLeft, 34, title, 'd-title')}
${editableGroup('subtitle', marginLeft, 56, subtitle, 'd-subtitle')}
<g>
  <text class="d-secondary-label" x="${marginLeft}" y="${marginTop - 30}" text-anchor="start" opacity="0.85">approx. ${escapeXml(meta.control_label || 'control')} value${meta.unit ? ' (' + escapeXml(meta.unit) + ')' : ''} &#8594;</text>
  ${secondaryTicks}
</g>
<g>
  ${yGrid}
  ${sigRects}
  <path class="d-band" d="${bandPath}"></path>
  <line class="d-zero" x1="${marginLeft}" y1="${zeroY.toFixed(1)}" x2="${width - marginRight}" y2="${zeroY.toFixed(1)}"></line>
  <path class="d-line" d="${linePath}" data-line-id="depth-delta-line"></path>
  ${xTicksMarkup}
  <rect x="${marginLeft}" y="${marginTop}" width="${plotW}" height="${plotH}" fill="none" stroke="${colors.border}"></rect>
</g>
${editableGroup('xlabel', marginLeft + plotW / 2, height - 10, xlabel, 'd-axis-label', 'middle')}
${editableGroup('ylabel', 16, midY, ylabel, 'd-axis-label', 'middle', `transform="rotate(-90 16 ${midY})"`)}
</svg>`;
  }

  /* ---------------- chart rendering + interactivity ---------------- */
  function renderChart() {
    const container = $('chart-container');
    if (!container) return;
    closeActiveEditor();
    state.themeColors = currentThemeColors();
    const svgStr = buildChartSVGString(state.result ? state.result.curve : [], state.meta, state.edits, state.result, state.themeColors);
    container.innerHTML = svgStr;
    wireEditableText(container);
    requestAnimationFrame(() => animateChartIn(container));
  }

  function animateChartIn(container) {
    if (prefersReducedMotion()) return;
    const line = container.querySelector('[data-line-id="depth-delta-line"]');
    if (line && line.getTotalLength) {
      try {
        const len = line.getTotalLength();
        line.style.strokeDasharray = `${len}`;
        line.style.strokeDashoffset = `${len}`;
        line.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.16,.84,.44,1)';
        requestAnimationFrame(() => requestAnimationFrame(() => { line.style.strokeDashoffset = '0'; }));
      } catch (_e) { /* non-fatal — SVG may not be laid out yet in some hosts */ }
    }
    const band = container.querySelector('.d-band');
    if (band) {
      band.style.opacity = '0';
      band.style.transform = 'scaleY(0.6)';
      band.style.transformOrigin = 'center';
      band.style.transition = 'opacity .8s ease .3s, transform .8s cubic-bezier(.16,.84,.44,1) .3s';
      requestAnimationFrame(() => requestAnimationFrame(() => { band.style.opacity = '1'; band.style.transform = 'scaleY(1)'; }));
    }
    container.querySelectorAll('.d-sig').forEach((rect, i) => {
      rect.style.transform = 'scaleX(0)';
      rect.style.transformOrigin = 'left';
      rect.style.transition = `transform .6s cubic-bezier(.16,.84,.44,1) ${0.5 + i * 0.1}s`;
      requestAnimationFrame(() => requestAnimationFrame(() => { rect.style.transform = 'scaleX(1)'; }));
    });
  }

  function measureEditableAffordances(container) {
    container.querySelectorAll('.depth-editable').forEach((g) => {
      const textEl = g.querySelector('text');
      const underline = g.querySelector('.depth-editable__underline');
      if (!textEl || !underline) return;
      try {
        const bbox = textEl.getBBox();
        const uy = bbox.y + bbox.height + 3;
        underline.setAttribute('x1', bbox.x);
        underline.setAttribute('x2', bbox.x + bbox.width);
        underline.setAttribute('y1', uy);
        underline.setAttribute('y2', uy);
      } catch (_e) { /* getBBox unavailable until laid out — skip sizing this pass */ }
    });
  }

  function wireEditableText(container) {
    measureEditableAffordances(container);
    container.querySelectorAll('.depth-editable').forEach((g) => {
      const key = g.getAttribute('data-edit-key');
      const textEl = g.querySelector('text');
      if (!textEl) return;
      const open = () => openTextEditor(g, textEl, key, container);
      g.addEventListener('click', open);
      g.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
    });
  }

  function closeActiveEditor() {
    if (activeEditor) { activeEditor.cleanup(); activeEditor = null; }
  }

  function openTextEditor(group, textEl, key, container) {
    closeActiveEditor();
    let rect, containerRect;
    try {
      rect = textEl.getBoundingClientRect();
      containerRect = container.getBoundingClientRect();
    } catch (_e) { return; }

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'svg-edit-input';
    input.value = state.edits[key] !== undefined ? state.edits[key] : textEl.textContent;

    const computed = window.getComputedStyle(textEl);
    input.style.left = Math.max(0, rect.left - containerRect.left - 4) + 'px';
    input.style.top = Math.max(0, rect.top - containerRect.top - 2) + 'px';
    input.style.width = Math.max(90, rect.width + 32) + 'px';
    input.style.fontSize = computed.fontSize;
    input.style.fontWeight = computed.fontWeight;
    input.style.fontFamily = computed.fontFamily;

    textEl.style.opacity = '0';
    container.appendChild(input);
    input.focus();
    input.select();

    function onBlur() { commit(); }

    function commit() {
      const val = input.value.trim();
      if (val) {
        state.edits[key] = val;
        textEl.textContent = val;
      }
      cleanup();
      measureEditableAffordances(container);
    }
    function cancel() { cleanup(); }
    function cleanup() {
      textEl.style.opacity = '1';
      input.removeEventListener('blur', onBlur);
      if (input.parentNode) input.remove();
      activeEditor = null;
    }

    input.addEventListener('blur', onBlur);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
      else if (e.key === 'Escape') {
        e.preventDefault();
        input.removeEventListener('blur', onBlur);
        cancel();
      }
    });

    activeEditor = { cleanup };
  }

  /* ---------------- export: self-contained report ---------------- */
  function buildReportHTML(st) {
    st = st || {};
    const meta = st.meta || {};
    const result = st.result || {};
    const edits = st.edits || {};
    const colors = st.themeColors || currentThemeColors();
    const svg = buildChartSVGString(result.curve, meta, edits, result, colors);
    const generatedOn = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';

    const rows = [
      ['n', fmtInt(result.n)],
      ['m', fmtInt(result.m)],
      ['method', result.method || 'n/a'],
      ['alpha', Number.isFinite(result.alpha) ? result.alpha : 'n/a'],
      ['mean diff', fmtSigned(result.mean_diff, 4)],
      ['median shift', fmtSigned(result.median_shift, 4)],
      ['welch p', fmtP(result.welch_p)],
      ['ks p', fmtP(result.ks_p)],
      ['verdict', result.any_significant ? 'Shift detected' : 'No shift detected']
    ];

    const regions = mergeRegionsForDisplay(result.significant_regions);
    const regionsList = regions.length
      ? regions.map((r) => `<li>${Number(r[0]).toFixed(3)} – ${Number(r[1]).toFixed(3)} (control quantile)</li>`).join('')
      : '<li>None: no significant region at this α.</li>';

    const callout = computeCallout(result, meta);
    const provenance = meta.provenance ? `Source: ${escapeHtml(meta.provenance)}` : 'Source: user-provided data.';
    const titleText = escapeHtml(edits.title || meta.suggested_title || 'DEPTH report');

    return `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>${titleText} (DEPTH report)</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: ${colors.paper};
    color: ${colors.ink};
    font-family: ${DISPLAY_STACK};
    padding: 2.5rem 1.25rem 4rem;
  }
  .wrap { max-width: 760px; margin: 0 auto; }
  .wordmark { font-weight: 900; font-size: 2.4rem; letter-spacing: -0.02em; margin: 0; }
  .wordmark span { color: ${colors.accent}; }
  .tagline { color: ${colors.fgMuted}; margin: 0.3rem 0 2rem; }
  h2 { font-size: 1rem; text-transform: uppercase; letter-spacing: 0.06em; color: ${colors.fgMuted}; margin: 0 0 0.75rem; }
  .chart-wrap { border: 1px solid ${colors.border}; padding: 1rem; margin-bottom: 2rem; background: ${colors.surface}; }
  .chart-wrap svg { width: 100%; height: auto; display: block; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 2rem; font-family: ${MONO_STACK}; font-size: 0.9rem; }
  td, th { padding: 0.5rem 0.75rem; border-bottom: 1px solid ${colors.border}; text-align: left; }
  th { color: ${colors.fgMuted}; font-weight: 600; width: 40%; }
  .callout { background: ${colors.warm}; border-left: 4px solid ${colors.signal}; padding: 1rem 1.25rem; margin-bottom: 2rem; line-height: 1.55; }
  .callout p:first-child { margin-top: 0; }
  .regions { margin: 0 0 2rem; padding-left: 1.25rem; }
  .regions li { font-family: ${MONO_STACK}; font-size: 0.85rem; margin-bottom: 0.25rem; }
  .footer { color: ${colors.fgMuted}; font-size: 0.78rem; border-top: 1px solid ${colors.border}; padding-top: 1rem; line-height: 1.6; }
  @media print { body { padding: 0; } }
</style>
</head>
<body>
<div class="wrap">
  <p class="wordmark">DEPTH<span>.</span></p>
  <p class="tagline">See what the mean is hiding.</p>
  <div class="chart-wrap">${svg}</div>
  <h2>Stats</h2>
  <table>
    ${rows.map(([k, v]) => `<tr><th>${escapeHtml(k)}</th><td>${escapeHtml(v)}</td></tr>`).join('')}
  </table>
  <h2>Significant regions (control quantile)</h2>
  <ul class="regions">${regionsList}</ul>
  <div class="callout">
    <p><strong>What the mean hides</strong></p>
    <p>${escapeHtml(callout)}</p>
  </div>
  <p class="footer">
    ${provenance}<br>
    Generated on ${generatedOn} by DEPTH (local shift-function analysis).<br>
    This file is fully self-contained (inline styles, inline chart, no external requests) and opens offline in any browser.
  </p>
</div>
</body>
</html>`;
  }

  function downloadReport() {
    if (!state.result) return;
    state.themeColors = currentThemeColors();
    const html = buildReportHTML(state);
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const idPart = state.datasetId || 'custom';
    a.href = url;
    a.download = `depth-report-${idPart}-${yyyymmdd(new Date())}.html`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  function wireDownloadButton() {
    const btn = $('download-report');
    if (btn) btn.addEventListener('click', downloadReport);
  }

  function wireBackendRetry() {
    const btn = $('backend-banner-retry');
    if (btn) btn.addEventListener('click', () => loadExamples());
  }

  /* ---------------- help panel (slide-over) ---------------- */
  let helpOpenerEl = null;

  function helpFocusableEls(panel) {
    return Array.prototype.slice.call(
      panel.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
    ).filter((el) => !el.hasAttribute('disabled') && el.getClientRects().length > 0);
  }

  function helpKeydown(e) {
    const panel = $('help-panel');
    if (!panel || !panel.classList.contains('is-open')) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      closeHelp();
      return;
    }
    if (e.key === 'Tab') {
      const focusable = helpFocusableEls(panel);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  function openHelp(opener) {
    const panel = $('help-panel');
    const backdrop = $('help-backdrop');
    const toggle = $('help-toggle');
    if (!panel || !backdrop) return;
    helpOpenerEl = opener || toggle || document.activeElement;
    panel.hidden = false;
    backdrop.hidden = false;
    // force layout so the transform/visibility transition actually runs
    // eslint-disable-next-line no-unused-expressions
    panel.offsetHeight;
    panel.classList.add('is-open');
    backdrop.classList.add('is-open');
    if (toggle) toggle.setAttribute('aria-expanded', 'true');
    document.addEventListener('keydown', helpKeydown, true);
    panel.focus();
  }

  function closeHelp() {
    const panel = $('help-panel');
    const backdrop = $('help-backdrop');
    const toggle = $('help-toggle');
    if (!panel || !backdrop || !panel.classList.contains('is-open')) return;
    panel.classList.remove('is-open');
    backdrop.classList.remove('is-open');
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
    document.removeEventListener('keydown', helpKeydown, true);
    const finish = () => { panel.hidden = true; backdrop.hidden = true; };
    if (prefersReducedMotion()) {
      finish();
    } else {
      let done = false;
      const onEnd = (e) => {
        if (e.target !== panel || done) return;
        done = true;
        panel.removeEventListener('transitionend', onEnd);
        finish();
      };
      panel.addEventListener('transitionend', onEnd);
      setTimeout(() => { if (!done) { done = true; finish(); } }, 500);
    }
    const back = helpOpenerEl || $('help-toggle');
    if (back && typeof back.focus === 'function') back.focus();
    helpOpenerEl = null;
  }

  function wireHelpPanel() {
    const toggle = $('help-toggle');
    const closeBtn = $('help-close');
    const backdrop = $('help-backdrop');
    if (toggle) toggle.addEventListener('click', () => openHelp(toggle));
    if (closeBtn) closeBtn.addEventListener('click', () => closeHelp());
    if (backdrop) backdrop.addEventListener('click', () => closeHelp());
  }

  function wireRunButton() {
    const btn = $('run-analysis');
    if (btn) btn.addEventListener('click', () => runAnalysis());
  }

  /* ---------------- load-in animation ---------------- */
  function animateHeaderIn() {
    if (prefersReducedMotion()) return;
    const targets = [
      document.querySelector('.site-header'),
      ...document.querySelectorAll('.panel-block'),
      document.querySelector('.results-panel')
    ].filter(Boolean);
    targets.forEach((el, i) => {
      el.classList.add('anim-in');
      el.style.animationDelay = `${i * 80}ms`;
    });
  }

  /* ---------------- init ---------------- */
  async function init() {
    initTheme();
    wireThemeToggle();
    wireCustomData();
    wireMethodToggle();
    wireAlphaInput();
    wireRunButton();
    wireDownloadButton();
    wireBackendRetry();
    wireHelpPanel();
    animateHeaderIn();
    await loadExamples();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* ---------------- QA / test surface ---------------- */
  window.DEPTH = {
    state,
    buildReportHTML,
    buildChartSVGString,
    parseCSV,
    computeCallout,
    currentThemeColors,
    runAnalysis,
    selectExample,
    applyTheme,
    defaultEdits
  };
})();
