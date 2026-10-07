/* At a glance: every published measure for a school, each placed against
   schools of the same level. Three views share one data file
   (data/metrics.json, built by scripts/build_metrics.py):
     - the school sheet (right-hand panel)
     - the lineup (every school in view as a row, every measure as a column)
     - "color dots by" on the map
   Colors: measures with a clear better/worse direction use FAV (least to
   most favorable fifth among peers). Measures with no agreed direction
   (spending, enrollment, suspensions, demographics) use SEQ (lowest to
   highest fifth) so the color never implies a judgment. */

const FAV = ['#ee5f53', '#a84d47', '#4b4e58', '#2f6db8', '#4893e8'];
const SEQ = ['#4d4675', '#665d9e', '#8277c2', '#a89be5', '#d3cbfb'];
const CHALKBEAT_GUIDE = 'https://www.chalkbeat.org/newyork/2026/10/07/how-to-find-nyc-public-schools-parents-guide/';
const LEVEL_NAME = { ES: 'elementary', MS: 'middle', HS: 'high', HST: 'transfer high', D75: 'District 75', EC: 'early childhood', ALL: '' };
const LINEUP_CAP = 250;

let MX = null;
const MI = {};
let colorBy = '';
let selectedDbn = null;
const pinned = [];

function loadGlance() {
  return fetch(`./data/metrics.json?v=${DATA_V}`).then(r => r.json()).then(d => {
    MX = d;
    d.metrics.forEach((m, i) => { MI[m.id] = i; m.i = i; });
    // Accessibility tags: replace the 2021 directory tags with DOE's current
    // Building Accessibility Profile list, so the sidebar filter uses it too.
    for (const s of allSchools) {
      if (s.sector === 'private' || !s.programs) continue;
      s.programs = s.programs.filter(p => !/accessible/i.test(p));
      const a = mval(s.dbn, 'access');
      if (a === 'Fully Accessible') s.programs.push('Fully accessible');
      else if (a === 'Partially Accessible') s.programs.push('Partially accessible');
    }
    buildColorBy();
  });
}

// ---------- lookups ----------
function rec(dbn) { return MX && MX.schools[dbn]; }
function mval(dbn, id) { const r = rec(dbn); return r ? r.v[MI[id]] ?? null : null; }
function mpct(dbn, id) { const r = rec(dbn); return r ? r.p[MI[id]] ?? null : null; }
function peerKey(m, level) { return (MX.dist[m.id] && MX.dist[m.id][level]) ? level : 'ALL'; }
function peerPhrase(m, level) {
  const k = peerKey(m, level);
  const n = MX.dist[m.id][k] ? MX.dist[m.id][k].n : 0;
  const lv = LEVEL_NAME[k];
  return `${n.toLocaleString()} ${lv ? lv + ' ' : ''}schools`;
}
function favorable(m, p) { return m.dir === -1 ? 100 - p : p; }
function cellColor(m, p) {
  if (p == null) return null;
  if (m.dir) return FAV[Math.min(4, Math.floor(favorable(m, p) / 20))];
  return SEQ[Math.min(4, Math.floor(p / 20))];
}

function fmt(m, v) {
  if (v == null) return '—';
  if (typeof v === 'string') return v;
  switch (m.unit) {
    case 'pct': return `${Math.round(v * 100)}%`;
    case 'pct1': return `${(v * 100).toFixed(1)}%`;
    case 'change': return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(Math.round(v * 100))}%`;
    case 'dollars': return v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${Math.round(v).toLocaleString()}`;
    case 'count': return Math.round(v).toLocaleString();
    default: return (m.dp != null ? v.toFixed(m.dp) : String(v));
  }
}

function ordinal(n) {
  const s = ['th', 'st', 'nd', 'rd'], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function rankSentence(m, p, level) {
  if (p == null) return '';
  const peers = peerPhrase(m, level);
  const r = Math.round(p);
  return r >= 50 ? `Higher than ${r}% of ${peers}` : `Lower than ${100 - r}% of ${peers}`;
}

// ---------- strip: peer distribution with this school marked ----------
function stripSVG(m, v, level, p) {
  const d = MX.dist[m.id] && MX.dist[m.id][peerKey(m, level)];
  if (!d || v == null || typeof v === 'string') return '<span class="strip-empty"></span>';
  const W = 104, H = 18, n = d.hist.length, bw = W / n, max = Math.max(...d.hist, 1);
  const [lo, hi] = MX.dist[m.id].domain;
  const x = t => Math.max(1.5, Math.min(W - 1.5, ((t - lo) / ((hi - lo) || 1)) * W));
  let bars = '';
  for (let i = 0; i < n; i++) {
    const h = Math.max(d.hist[i] ? 1 : 0, (d.hist[i] / max) * (H - 4));
    if (h) bars += `<rect x="${(i * bw + 0.5).toFixed(1)}" y="${(H - h).toFixed(1)}" width="${Math.max(0.5, bw - 1).toFixed(1)}" height="${h.toFixed(1)}"/>`;
  }
  const c = cellColor(m, p) || '#9099ab';
  const med = x(d.median);
  return `<svg class="strip" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">
    <g class="hist">${bars}</g>
    <line class="med" x1="${med}" x2="${med}" y1="0" y2="${H}"/>
    <rect class="you-ring" x="${(x(v) - 2.5).toFixed(1)}" y="0" width="5" height="${H}"/>
    <rect x="${(x(v) - 1.5).toFixed(1)}" y="0" width="3" height="${H}" fill="${c}"/>
  </svg>`;
}

// ---------- the school sheet ----------
function openSheet(s, opts = {}) {
  selectedDbn = s.dbn;
  const el = document.getElementById('sheet');
  el.innerHTML = renderSheet(s);
  el.hidden = false;
  el.scrollTop = 0;
  document.body.classList.add('sheet-open');
  const photo = el.querySelector('[data-photo]');
  if (photo) loadPhoto(s, photo);
  if (history.replaceState) history.replaceState(null, '', `#school=${encodeURIComponent(s.dbn)}`);
  markSelected();
  map.invalidateSize();
  if (!opts.noPan) {
    const m = markerIndex.get(s.dbn);
    const ll = m ? m.getLatLng() : L.latLng(s.lat, s.lon);
    if (opts.zoom) map.setView(ll, opts.zoom); else if (!map.getBounds().pad(-0.1).contains(ll)) map.panTo(ll);
  }
}

function closeSheet() {
  selectedDbn = null;
  const el = document.getElementById('sheet');
  el.hidden = true;
  document.body.classList.remove('sheet-open');
  if (history.replaceState) history.replaceState(null, '', location.pathname + location.search);
  markSelected();
  map.invalidateSize();
}

function markSelected() {
  document.querySelectorAll('.mk.selected').forEach(n => n.classList.remove('selected'));
  if (!selectedDbn) return;
  const n = document.querySelector(`.mk[data-dbn="${CSS.escape(selectedDbn)}"]`);
  if (n) n.classList.add('selected');
}

function renderSheet(s) {
  const r = rec(s.dbn);
  const sectorLabel = s.sector === 'public' ? 'District public school' : s.sector === 'charter' ? 'Charter school' : 'Private school';
  const meta = [
    sectorLabel,
    s.grades ? `Grades ${escapeHtml(s.grades)}` : '',
    s.boro ? escapeHtml(s.boro) : '',
    s.dbn && !s.dbn.startsWith('PRIV-') ? escapeHtml(s.dbn) : '',
  ].filter(Boolean).join(' · ');

  let html = `<button class="sheet-close" type="button" aria-label="Close">&times;</button>
    <div class="sheet-photo" data-photo data-lat="${s.lat}" data-lon="${s.lon}" style="display:none"></div>
    <div class="sheet-head">
      <h2>${escapeHtml(s.name || 'Unnamed school')}</h2>
      <div class="sheet-meta"><span class="mk-mini ${sectorClass(s)}"></span>${meta}</div>
      ${s.address ? `<div class="sheet-addr">${escapeHtml(s.address)}${s.zip ? ', ' + escapeHtml(s.zip) : ''}</div>` : ''}
    </div>`;

  if (s.sector === 'private') {
    html += `<div class="sheet-block"><p class="sheet-note">Private schools don&rsquo;t report the measures below to the city or state. Location and name come from the federal private school survey.</p></div>`;
    html += sheetLinks(s);
    return html;
  }
  if (!r) {
    html += `<div class="sheet-block"><p class="sheet-note">No school-level measures were published for this school.</p></div>${sheetLinks(s)}`;
    return html;
  }

  const lvl = r.level;
  html += `<div class="sheet-block sheet-intro">
      <p>Each bar shows how this school compares with other ${LEVEL_NAME[lvl] ? LEVEL_NAME[lvl] + ' ' : ''}schools: the gray shape is every school, the dashed line is the median and the colored mark is this school. Hover a row for its definition, source and year.</p>
      <div class="key"><span class="ramp">${FAV.map(c => `<span style="background:${c}"></span>`).join('')}</span><span>least to most favorable fifth</span><span class="ramp">${SEQ.map(c => `<span style="background:${c}"></span>`).join('')}</span><span>lowest to highest, where neither is better</span></div>
      <p>What the measures mean and how to use them: <a href="${CHALKBEAT_GUIDE}" target="_blank" rel="noopener">Chalkbeat and The City Reporter&rsquo;s guide to vetting a school</a>.</p>
    </div>`;

  html += renderCallouts(s, r);

  for (const g of MX.groups) {
    const ms = MX.metrics.filter(m => m.group === g.id && r.v[m.i] != null);
    if (!ms.length) continue;
    const srcs = [...new Set(ms.map(m => `${m.source}, ${m.vintage}`))].join('; ');
    html += `<section class="sheet-block grp"><h3>${escapeHtml(g.label)}</h3>${g.note ? `<p class="grp-note">${g.note}</p>` : ''}<div class="mrows">${ms.map(m => metricRow(s, r, m)).join('')}</div>${g.id === 'students' ? studentExtras(s) : ''}<p class="grp-src">${escapeHtml(srcs)}.</p></section>`;
  }

  if (r.x && Object.keys(r.x).length) {
    const facts = Object.entries(r.x).map(([k, v]) => `<div class="fact"><span>${escapeHtml(MX.extras[k] || k)}</span><b>${escapeHtml(String(v))}</b></div>`).join('');
    html += `<section class="sheet-block grp"><h3>Also on file</h3><div class="facts">${facts}</div></section>`;
  }

  const progs = (s.programs || []).filter(p => !/accessible/i.test(p));
  if (progs.length) {
    html += `<section class="sheet-block grp"><h3>Programs</h3><div class="chips">${progs.slice(0, 24).map(p => `<span class="chip">${escapeHtml(truncate(p, 60))}</span>`).join('')}</div><p class="grp-note">From DOE&rsquo;s 2021 school directories; a missing tag isn&rsquo;t proof a program doesn&rsquo;t exist.</p></section>`;
  }
  if (s.admission) html += `<section class="sheet-block grp"><h3>Admissions</h3><p class="sheet-note">${escapeHtml(s.admission)}</p></section>`;
  html += `<section class="sheet-block grp">${renderNearby(s)}</section>`;
  html += sheetLinks(s);
  return html;
}

function metricRow(s, r, m) {
  const v = r.v[m.i];
  if (v == null) return '';
  const p = r.p[m.i];
  const label = escapeHtml(m.short || m.label);
  if (typeof v === 'string') {
    return `<div class="mrow text" data-m="${m.id}"><div class="ml">${label}</div><div class="mv txt">${escapeHtml(v)}</div></div>`;
  }
  return `<div class="mrow" data-m="${m.id}" tabindex="0">
    <div class="ml">${label}</div>
    ${stripSVG(m, v, r.level, p)}
    <div class="mv">${(r.t && r.t[m.i]) || fmt(m, v)}</div>
  </div>`;
}

function renderCallouts(s, r) {
  const worst = [], best = [];
  for (const m of MX.metrics) {
    const v = r.v[m.i], p = r.p[m.i];
    if (v == null || p == null || !m.dir || typeof v === 'string') continue;
    const f = favorable(m, p);
    const line = `<li><span class="sw" style="background:${cellColor(m, p)}"></span><span><b>${escapeHtml(m.short || m.label)}</b> ${(r.t && r.t[m.i]) || fmt(m, v)}. ${rankSentence(m, p, r.level)}.</span></li>`;
    if (f < 10) worst.push([f, line]); else if (f >= 90) best.push([-f, line]);
  }
  for (const b of (r.b || [])) worst.push([-1, `<li><span class="sw" style="background:${FAV[0]}"></span><span>${escapeHtml(b)}</span></li>`]);
  if (!worst.length && !best.length) return '';
  worst.sort((a, b) => a[0] - b[0]); best.sort((a, b) => a[0] - b[0]);
  const list = arr => {
    const shown = arr.slice(0, 6).map(x => x[1]).join('');
    return `<ul>${shown}</ul>${arr.length > 6 ? `<p class="grp-note">And ${arr.length - 6} more below.</p>` : ''}`;
  };
  let h = '<section class="sheet-block callouts">';
  if (worst.length) h += `<h3>Worth asking about</h3><p class="grp-note">Measures where this school is in the least favorable tenth of its peers, plus any benchmark the guide names.</p>${list(worst)}`;
  if (best.length) h += `<h3>Stands out</h3><p class="grp-note">Measures where it is in the most favorable tenth.</p>${list(best)}`;
  return h + '</section>';
}

function studentExtras(s) {
  const d = s.demo;
  if (!d) return '';
  const spark = sparklineSVG(s.trend);
  const race = [
    ['Asian', d.pct_asian, 'var(--demo-asian)'],
    ['Black', d.pct_black, 'var(--demo-black)'],
    ['Hispanic', d.pct_hispanic, 'var(--demo-hisp)'],
    ['White', d.pct_white, 'var(--demo-white)'],
    ['Multiracial', d.pct_multi, 'var(--demo-multi)'],
  ].filter(x => x[1] != null && x[1] > 0).map(([l, v, c]) => barRow(l, v, c)).join('');
  return `${spark ? `<div class="enroll-spark"><div class="es-lbl">Enrollment by year</div>${spark}</div>` : ''}
    <div class="bars">${race}</div>`;
}

function sheetLinks(s) {
  const links = [];
  if (s.website) links.push(`<a href="${ensureHttp(s.website)}" target="_blank" rel="noopener">School website</a>`);
  const u = (rec(s.dbn) || {}).u || {};
  if (u.authorizer) links.push(`<a href="${escapeHtml(u.authorizer)}" target="_blank" rel="noopener">Authorizer&rsquo;s page</a>`);
  if (u.nysed) links.push(`<a href="${escapeHtml(u.nysed)}" target="_blank" rel="noopener">State charter page</a>`);
  const st = (rec(s.dbn) || {}).st;
  if (st) links.push(`<a href="https://tools.nycenet.edu/snapshot/2025/${encodeURIComponent(s.dbn)}/${st}/" target="_blank" rel="noopener">DOE quality snapshot</a>`);
  if (s.sector !== 'private') {
    links.push(`<a href="https://www.google.com/search?q=${encodeURIComponent(s.name + ' ' + s.dbn + ' site:chalkbeat.org OR site:thecityreporter.nyc')}" target="_blank" rel="noopener">News coverage</a>`);
  }
  links.push(`<a href="https://www.google.com/maps/search/?api=1&query=${s.lat},${s.lon}" target="_blank" rel="noopener">Map</a>`);
  links.push(`<a href="${CHALKBEAT_GUIDE}" target="_blank" rel="noopener">How to vet a school</a>`);
  return `<div class="sheet-links">${links.join('')}</div>`;
}

// ---------- tooltip ----------
const tip = document.createElement('div');
tip.id = 'tip';
tip.hidden = true;
document.body.appendChild(tip);
function showTip(html, x, y) {
  tip.innerHTML = html;
  tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  const left = Math.min(window.innerWidth - w - 8, x + 14);
  const top = y + h + 20 > window.innerHeight ? y - h - 12 : y + 14;
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${Math.max(8, top)}px`;
}
function hideTip() { tip.hidden = true; }

function metricTip(m, dbn) {
  const r = rec(dbn);
  const v = r ? r.v[m.i] : null, p = r ? r.p[m.i] : null;
  const d = r && MX.dist[m.id] && MX.dist[m.id][peerKey(m, r.level)];
  return `<div class="tip-h">${escapeHtml(m.label)}</div>
    ${v != null ? `<div class="tip-v">${(r.t && r.t[m.i]) || fmt(m, v)}${p != null ? ` <span>${rankSentence(m, p, r.level)}</span>` : ''}</div>` : '<div class="tip-v">No data</div>'}
    ${d ? `<div class="tip-m">Median among ${LEVEL_NAME[peerKey(m, r.level)] || 'all'} schools: ${fmt(m, d.median)}</div>` : ''}
    <div class="tip-d">${escapeHtml(m.def)}</div>
    <div class="tip-s">${escapeHtml(m.source)}, ${escapeHtml(m.vintage)}</div>`;
}

document.addEventListener('mouseover', e => {
  const row = e.target.closest('#sheet .mrow');
  if (row && selectedDbn) { showTip(metricTip(MX.metrics[MI[row.dataset.m]], selectedDbn), e.clientX, e.clientY); return; }
  const cell = e.target.closest('#lineup td.c');
  if (cell) {
    const m = MX.metrics[+cell.dataset.i];
    const s = schoolByDbn.get(cell.parentNode.dataset.dbn);
    showTip(`<div class="tip-school">${escapeHtml(s.name)}</div>${metricTip(m, s.dbn)}`, e.clientX, e.clientY);
    return;
  }
  const th = e.target.closest('#lineup th.mh');
  if (th) {
    const m = MX.metrics[+th.dataset.i];
    showTip(`<div class="tip-h">${escapeHtml(m.label)}</div><div class="tip-d">${escapeHtml(m.def)}</div><div class="tip-s">${escapeHtml(m.source)}, ${escapeHtml(m.vintage)}. Click to sort.</div>`, e.clientX, e.clientY);
    return;
  }
});
document.addEventListener('mousemove', e => {
  if (tip.hidden) return;
  if (!e.target.closest('#sheet .mrow, #lineup td.c, #lineup th.mh')) { hideTip(); return; }
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, e.clientX + 14))}px`;
  tip.style.top = `${Math.max(8, e.clientY + h + 20 > window.innerHeight ? e.clientY - h - 12 : e.clientY + 14)}px`;
});
document.addEventListener('focusin', e => {
  const row = e.target.closest('#sheet .mrow');
  if (row && selectedDbn) { const b = row.getBoundingClientRect(); showTip(metricTip(MX.metrics[MI[row.dataset.m]], selectedDbn), b.left, b.bottom); }
});
document.addEventListener('focusout', hideTip);

document.addEventListener('click', e => {
  if (e.target.closest('.sheet-close')) { closeSheet(); return; }
  const chip = e.target.closest('#sheet .nearby-chip');
  if (chip && chip.dataset.dbn) { const s = schoolByDbn.get(chip.dataset.dbn); if (s) openSheet(s); return; }
  const nm = e.target.closest('#lineup td.nm');
  if (nm) { const s = schoolByDbn.get(nm.parentNode.dataset.dbn); if (s) openSheet(s); return; }
  const unpin = e.target.closest('#lineup .unpin');
  if (unpin) { togglePin(schoolByDbn.get(unpin.dataset.dbn)); return; }
  const th = e.target.closest('#lineup th.mh');
  if (th) {
    const i = +th.dataset.i;
    lineupSort = lineupSort === i ? -1 : i;
    renderLineup();
    return;
  }
  if (e.target.closest('#lineup-close')) { toggleLineup(false); return; }
  if (e.target.closest('#lineup-btn')) { toggleLineup(); return; }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !document.getElementById('sheet').hidden) closeSheet();
});

// ---------- color dots by ----------
function buildColorBy() {
  const sel = document.getElementById('colorby');
  if (!sel) return;
  let h = '<option value="">Sector (default)</option>';
  for (const g of MX.groups) {
    const ms = MX.metrics.filter(m => m.group === g.id && m.unit !== 'text');
    if (!ms.length) continue;
    h += `<optgroup label="${escapeHtml(g.label)}">${ms.map(m => `<option value="${m.id}">${escapeHtml(m.short || m.label)}</option>`).join('')}</optgroup>`;
  }
  sel.innerHTML = h;
  sel.addEventListener('change', () => { colorBy = sel.value; renderColorLegend(); renderSchools(); if (!document.getElementById('lineup').hidden) renderLineup(); });
}

function renderColorLegend() {
  const el = document.getElementById('colorby-legend');
  if (!colorBy) { el.hidden = true; return; }
  const m = MX.metrics[MI[colorBy]];
  const pal = m.dir ? FAV : SEQ;
  const ends = m.dir ? ['Least favorable fifth', 'Most favorable fifth'] : ['Lowest fifth', 'Highest fifth'];
  const counts = Object.values(MX.schools).filter(r => r.v[m.i] != null).length;
  el.innerHTML = `<div class="cb-scale">${pal.map(c => `<span style="background:${c}"></span>`).join('')}</div>
    <div class="cb-ends"><span>${ends[0]}</span><span>${ends[1]}</span></div>
    <p>${escapeHtml(m.label)}. Each school is ranked against schools of its own level. ${counts.toLocaleString()} schools have this measure; hollow dots don&rsquo;t.</p>
    <p class="cb-src">${escapeHtml(m.source)}, ${escapeHtml(m.vintage)}</p>`;
  el.hidden = false;
}

function markerFill(s) {
  if (!colorBy || !MX) return null;
  const m = MX.metrics[MI[colorBy]];
  return cellColor(m, mpct(s.dbn, colorBy));
}

// ---------- lineup ----------
let lineupSort = -1;
function toggleLineup(force) {
  const el = document.getElementById('lineup');
  const on = force == null ? el.hidden : force;
  el.hidden = !on;
  document.body.classList.toggle('lineup-open', on);
  document.getElementById('lineup-btn').classList.toggle('on', on);
  if (on) renderLineup();
}

function togglePin(s) {
  if (!s || s.sector === 'private') return;
  const i = pinned.indexOf(s.dbn);
  if (i >= 0) pinned.splice(i, 1); else pinned.push(s.dbn);
  renderPinTray();
  if (!document.getElementById('lineup').hidden) renderLineup(); else if (pinned.length) toggleLineup(true);
}

function renderPinTray() {
  const empty = document.getElementById('compare-empty');
  const tray = document.getElementById('compare-tray');
  if (!pinned.length) { empty.style.display = ''; tray.hidden = true; return; }
  empty.style.display = 'none'; tray.hidden = false;
  tray.innerHTML = pinned.map(d => `<div class="cmp-pill"><span>${escapeHtml(schoolByDbn.get(d).name)}</span><span class="x" data-dbn="${d}">&times;</span></div>`).join('');
  tray.querySelectorAll('.x').forEach(x => x.addEventListener('click', () => togglePin(schoolByDbn.get(x.dataset.dbn))));
}

function renderLineup() {
  if (!MX) return;
  const el = document.getElementById('lineup');
  // Only the part of the map the lineup doesn't cover.
  const sz = map.getSize();
  const b = L.latLngBounds(map.containerPointToLatLng([0, 0]), map.containerPointToLatLng([sz.x, Math.max(40, sz.y - el.offsetHeight)]));
  const inView = allSchools.filter(s => s.sector !== 'private' && passesFilters(s) && b.contains([s.lat, s.lon]) && !pinned.includes(s.dbn));
  const rows = pinned.map(d => schoolByDbn.get(d)).concat(inView);
  const metrics = MX.metrics.filter(m => m.unit !== 'text');
  const sortM = lineupSort >= 0 ? MX.metrics[lineupSort] : null;
  const pinnedRows = rows.slice(0, pinned.length);
  let rest = rows.slice(pinned.length);
  if (sortM) {
    const key = s => { const p = mpct(s.dbn, sortM.id); return p == null ? -1 : (sortM.dir ? favorable(sortM, p) : p); };
    rest.sort((a, c) => key(c) - key(a));
  } else {
    const ctr = map.getCenter();
    rest.sort((a, c) => (a.lat - ctr.lat) ** 2 + (a.lon - ctr.lng) ** 2 - ((c.lat - ctr.lat) ** 2 + (c.lon - ctr.lng) ** 2));
  }
  const total = rest.length;
  rest = rest.slice(0, LINEUP_CAP);
  const shown = pinnedRows.concat(rest);

  let groupRow = '<tr class="gr"><th class="nm-h"></th>';
  for (const g of MX.groups) {
    const n = metrics.filter(m => m.group === g.id).length;
    if (n) groupRow += `<th colspan="${n}" class="gh"><span>${escapeHtml(g.short || g.label)}</span></th>`;
  }
  groupRow += '</tr>';
  let head = `<tr><th class="nm-h">${pinned.length ? `${pinned.length} pinned, then ` : ''}${sortM ? 'sorted by ' + escapeHtml(sortM.col || sortM.short) + ', best placed among its own level first' : 'nearest the map center first. Click a column to sort'}</th>`;
  head += metrics.map(m => `<th class="mh${lineupSort === m.i ? ' sorted' : ''}" data-i="${m.i}"><span>${escapeHtml(m.col || m.short)}</span></th>`).join('') + '</tr>';

  const body = shown.map((s, idx) => {
    const r = rec(s.dbn);
    const isPin = idx < pinnedRows.length;
    const cells = metrics.map(m => {
      const p = r ? r.p[m.i] : null;
      const v = r ? r.v[m.i] : null;
      const c = v == null ? '' : (cellColor(m, p) || '#2a2f3c');
      return `<td class="c${v == null ? ' na' : ''}" data-i="${m.i}"${c ? ` style="background:${c}"` : ''}></td>`;
    }).join('');
    const lvl = r ? LEVEL_NAME[r.level] || '' : '';
    return `<tr data-dbn="${s.dbn}" class="${isPin ? 'pin' : ''}${s.dbn === selectedDbn ? ' sel' : ''}"><td class="nm">${isPin ? `<button class="unpin" data-dbn="${s.dbn}" title="Unpin">&times;</button>` : ''}<span class="mk-mini ${sectorClass(s)}"></span><span class="nm-t">${escapeHtml(s.name)}</span><span class="nm-l">${escapeHtml(lvl)}</span></td>${cells}</tr>`;
  }).join('');

  el.querySelector('.lu-count').innerHTML = total > LINEUP_CAP
    ? `${LINEUP_CAP} of ${total.toLocaleString()} public and charter schools in view. Zoom in to see the rest.`
    : `${shown.length.toLocaleString()} public and charter schools in view. Pan or zoom the map to change the list.`;
  el.querySelector('.lu-scroll').innerHTML = shown.length
    ? `<table><thead>${groupRow}${head}</thead><tbody>${body}</tbody></table>`
    : '<p class="lu-empty">No public or charter schools in view. Zoom out or loosen the filters.</p>';
}

map.on('moveend', () => { if (!document.getElementById('lineup').hidden) renderLineup(); });
