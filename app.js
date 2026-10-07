/* NYC schools atlas */
// Bump with each data rebuild so browsers don't pair new code with cached data.
const DATA_V = '2026-10-07c';
const GSV_KEY = "AIzaSyBPEjOGoN9DTFfr4BaLoHNIVM_FHNQNeFI";

const map = L.map('map', { preferCanvas: true, zoomControl: true, minZoom: 10, maxZoom: 18 })
  .setView([40.7128, -74.0060], 11);

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png?key=cb1_2r82_1_ae4e70b6166057bc41b89638', {
  attribution: '&copy; <a href="https://carto.com/">CARTO</a> &middot; &copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a> &middot; Schools DOE/NCES &middot; Children ACS 2020&ndash;2024',
  subdomains: 'abcd', maxZoom: 20,
}).addTo(map);

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png?key=cb1_2r82_1_ae4e70b6166057bc41b89638', {
  subdomains: 'abcd', maxZoom: 20, pane: 'shadowPane',
}).addTo(map);

// Dots shrink when zoomed out so the city view doesn't turn into a pile.
const MARKER_PX = { 10: 4, 11: 5, 12: 6, 13: 8, 14: 10 };
function sizeMarkers() {
  const z = map.getZoom();
  const px = z >= 15 ? 12 : (MARKER_PX[z] || 4);
  const el = map.getContainer();
  el.style.setProperty('--mk', px + 'px');
  el.classList.toggle('mk-small', px <= 8);
  el.classList.toggle('mk-tiny', px <= 5);
}
map.on('zoomend', sizeMarkers);
sizeMarkers();

// -------------- State --------------
let allSchools = [];
let schoolByDbn = new Map();
let markerIndex = new Map();
let activeHoverZoneLayer = null;
let activeAddressPin = null;
let zonesIndex = null;
let choroLayer = null;

const filters = {
  q: '',
  sector: new Set(['public','charter','private']),
  band: new Set(['ES','MS','HS','PK']),
  programs: new Set(),
  admissions: new Set(),
  showZones: true,
  trajectory: 'all',
};

const TRAJECTORY_WINDOW = 3;
const LARGEST_N = 50;
let largestSet = new Set();

function latestEnrollment(s) {
  if (s.demo && s.demo.enrollment_latest != null) return s.demo.enrollment_latest;
  if (s.demo && s.demo.enrollment != null) return s.demo.enrollment;
  if (s.trend && s.trend.length) {
    for (let i = s.trend.length - 1; i >= 0; i--) if (s.trend[i][1] != null) return s.trend[i][1];
  }
  return null;
}

function trajectoryChange(s) {
  if (!s.trend || s.trend.length < 2) return null;
  const valid = s.trend.filter(r => r[1] != null);
  if (valid.length < 2) return null;
  const latest = valid[valid.length - 1][1];
  const idx = Math.max(0, valid.length - 1 - TRAJECTORY_WINDOW);
  const prior = valid[idx][1];
  if (!prior || prior < 10) return null;
  return { latest, prior, pct: (latest - prior) / prior };
}

function passesTrajectory(s) {
  const v = filters.trajectory;
  if (v === 'all') return true;
  if (v === 'tiny') {
    const e = latestEnrollment(s);
    return e != null && e < 100;
  }
  if (v === 'largest') return largestSet.has(s.dbn);
  const t = trajectoryChange(s);
  if (!t) return false;
  switch (v) {
    case 'rising':      return t.pct >= 0.10;
    case 'stable':      return Math.abs(t.pct) < 0.10;
    case 'falling':     return t.pct <= -0.10 && t.pct > -0.25;
    case 'collapsing':  return t.pct <= -0.25;
    case 'underenrolled': return t.latest < 300 && t.pct <= -0.10;
  }
  return false;
}

function trajectoryClass(s) {
  const v = filters.trajectory;
  if (v === 'all') return '';
  if (!passesTrajectory(s)) return '';
  if (v === 'tiny') return 'traj-hit traj-hit-tiny';
  if (v === 'largest') return 'traj-hit traj-hit-largest';
  if (v === 'rising') return 'traj-hit traj-hit-rising';
  if (v === 'stable') return 'traj-hit traj-hit-stable';
  if (v === 'falling') return 'traj-hit traj-hit-falling';
  if (v === 'collapsing') return 'traj-hit traj-hit-collapsing';
  if (v === 'underenrolled') return 'traj-hit traj-hit-under';
  return '';
}

const PROGRAM_FILTER_LIST = [
  'Specialized High School',
  'International Baccalaureate',
  'Career and Technical Education',
  'Gifted and Talented',
  'Dual language',
  'ASD Nest',
  'District 75 (special education)',
  'Fully accessible',
];

const ADMISSIONS_LIST = [
  'Zoned',
  'Open',
  'Screened',
  'Ed. Opt.',
  'Audition',
  'Limited Unscreened',
  'Test',
  'Non-Zoned',
];

// ---------- Utilities ----------
const fmtNum = v => (v == null) ? '—' : Math.round(v).toLocaleString();

function detectBand(s) {
  const bands = new Set();
  const g = (s.grades || '').toUpperCase();
  if (/PK|3-?K|PRE/.test(g)) bands.add('PK');
  if (/K|0K|KINDERGARTEN|1|2|3|4|5/.test(g) && !/HIGH/.test(g)) bands.add('ES');
  if (/6|7|8|MIDDLE/.test(g)) bands.add('MS');
  if (/9|10|11|12|HIGH|HS/.test(g)) bands.add('HS');
  if (!bands.size) {
    const name = (s.name || '').toUpperCase();
    if (/P\.S\.|PS\s|ELEMENTARY/.test(name)) bands.add('ES');
    if (/M\.S\.|MS\s|MIDDLE|JHS|I\.S\.|IS\s/.test(name)) bands.add('MS');
    if (/HIGH SCHOOL|H\.S\.|HS\s|ACADEMY|PREP/.test(name)) bands.add('HS');
    if (!bands.size) bands.add('ES');
  }
  return bands;
}

function sectorClass(s) {
  if (s.sector === 'charter') return 'charter';
  if (s.sector === 'private') return 'private';
  return s.has_zone ? 'public' : 'public unzoned';
}

// ---------- Load data ----------
Promise.all([
  fetch(`./data/schools.json?v=${DATA_V}`).then(r => r.json()),
  fetch('./data/zones.geojson').then(r => r.json()),
]).then(([schools, zones]) => {
  allSchools = schools;
  zonesIndex = new Map();
  for (const f of zones.features) {
    // A shared zone lists every school in it: "09X053,09X088".
    for (const dbn of String((f.properties && f.properties.dbn) || '').split(',').map(x => x.trim()).filter(Boolean)) {
      if (!zonesIndex.has(dbn)) zonesIndex.set(dbn, []);
      zonesIndex.get(dbn).push(f);
    }
  }
  for (const s of schools) { s._bands = detectBand(s); schoolByDbn.set(s.dbn, s); }
  computeLargest();
  wireTrajectory();
  buildProgramFilters();
  buildAdmissionFilters();
  renderSchools();
  return loadGlance().catch(err => console.error('metrics failed to load', err));
}).then(() => {
  renderSchools();
  handleDeepLink();
}).catch(err => {
  console.error(err);
  document.getElementById('result-count').textContent = 'Failed to load data.';
});

function computeLargest() {
  const ranked = allSchools
    .map(s => [s.dbn, latestEnrollment(s)])
    .filter(r => r[1] != null)
    .sort((a, b) => b[1] - a[1])
    .slice(0, LARGEST_N);
  largestSet = new Set(ranked.map(r => r[0]));
}

function wireTrajectory() {
  document.querySelectorAll('input[name="traj"]').forEach(el => {
    el.addEventListener('change', e => {
      if (!e.target.checked) return;
      filters.trajectory = e.target.value;
      renderSchools();
      updateTrajectorySummary();
    });
  });
  updateTrajectorySummary();
}

function updateTrajectorySummary() {
  const el = document.getElementById('traj-summary');
  if (!el) return;
  if (filters.trajectory === 'all') { el.textContent = ''; return; }
  const hits = allSchools.filter(passesTrajectory);
  if (!hits.length) { el.textContent = '0 schools match.'; return; }
  const changes = hits.map(trajectoryChange).filter(Boolean).map(t => t.pct);
  if (filters.trajectory === 'tiny' || filters.trajectory === 'largest') {
    el.textContent = `${hits.length.toLocaleString()} schools match.`;
    return;
  }
  changes.sort((a, b) => a - b);
  const median = changes.length ? changes[Math.floor(changes.length / 2)] : 0;
  const sign = median >= 0 ? '+' : '';
  el.textContent = `${hits.length.toLocaleString()} schools match · median change ${sign}${Math.round(median * 100)}%.`;
}

function buildProgramFilters() {
  const host = document.getElementById('program-filters');
  host.innerHTML = PROGRAM_FILTER_LIST.map(p => `
    <label class="chk"><input type="checkbox" data-filter="programs" value="${p}" />${p}</label>
  `).join('');
  host.querySelectorAll('input').forEach(i => i.addEventListener('change', onFilterChange));
}

function buildAdmissionFilters() {
  const host = document.getElementById('admission-filters');
  host.innerHTML = ADMISSIONS_LIST.map(a => `
    <label class="chk"><input type="checkbox" data-filter="admissions" value="${a}" />${a}</label>
  `).join('');
  host.querySelectorAll('input').forEach(i => i.addEventListener('change', onFilterChange));
}

function onFilterChange(e) {
  const kind = e.target.dataset.filter;
  const v = e.target.value;
  if (e.target.checked) filters[kind].add(v); else filters[kind].delete(v);
  renderSchools();
}

document.querySelectorAll('input[data-filter]').forEach(i => i.addEventListener('change', onFilterChange));
const qInput = document.getElementById('q');
const qSuggest = document.getElementById('q-suggest');
let qActiveIdx = -1;
let qMatches = [];
qInput.addEventListener('input', e => {
  const v = e.target.value.trim();
  filters.q = v.toLowerCase();
  renderSchools();
  renderQSuggest(v);
});
qInput.addEventListener('keydown', e => {
  if (qSuggest.hidden || !qMatches.length) return;
  if (e.key === 'ArrowDown') { e.preventDefault(); qActiveIdx = Math.min(qActiveIdx + 1, qMatches.length - 1); paintQSuggest(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); qActiveIdx = Math.max(qActiveIdx - 1, 0); paintQSuggest(); }
  else if (e.key === 'Enter') { e.preventDefault(); selectQ(qMatches[qActiveIdx >= 0 ? qActiveIdx : 0]); }
  else if (e.key === 'Escape') { hideQSuggest(); }
});
qInput.addEventListener('blur', () => setTimeout(hideQSuggest, 150));

function renderQSuggest(v) {
  if (v.length < 2 || !allSchools.length) { hideQSuggest(); return; }
  const q = v.toLowerCase();
  const ranked = [];
  for (const s of allSchools) {
    const name = (s.name || '').toLowerCase();
    const nb = (s.neighborhood || '').toLowerCase();
    const addr = (s.address || '').toLowerCase();
    let rank = -1;
    if (name.startsWith(q)) rank = 0;
    else if (name.includes(q)) rank = 1;
    else if (nb.includes(q)) rank = 2;
    else if (addr.includes(q)) rank = 3;
    if (rank >= 0) ranked.push([rank, s]);
  }
  ranked.sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name));
  qMatches = ranked.slice(0, 8).map(x => x[1]);
  qActiveIdx = qMatches.length ? 0 : -1;
  paintQSuggest();
}
function paintQSuggest() {
  if (!qMatches.length) { hideQSuggest(); return; }
  qSuggest.innerHTML = qMatches.map((s, i) => {
    const sub = [s.neighborhood, s.boro].filter(Boolean).join(' · ');
    return `<div class="addr-suggest-item${i === qActiveIdx ? ' active' : ''}" data-dbn="${s.dbn}"><div>${escapeHtml(s.name)}</div><div class="muted" style="font-size:10.5px">${escapeHtml(sub)}</div></div>`;
  }).join('');
  qSuggest.hidden = false;
  qSuggest.querySelectorAll('[data-dbn]').forEach(el => {
    el.addEventListener('mousedown', (e) => { e.preventDefault(); const s = allSchools.find(x => x.dbn === el.dataset.dbn); selectQ(s); });
  });
}
function hideQSuggest() { qSuggest.hidden = true; qMatches = []; qActiveIdx = -1; }
function selectQ(s) {
  if (!s) return;
  hideQSuggest();
  openSheet(s, { zoom: 15 });
}
document.getElementById('lyr-zone').addEventListener('change', e => { filters.showZones = e.target.checked; });
document.getElementById('lyr-choro').addEventListener('change', e => toggleChoropleth(e.target.checked));
document.getElementById('lyr-all-es').addEventListener('change', e => toggleAllZones('elementary', e.target.checked));
document.getElementById('lyr-all-ms').addEventListener('change', e => toggleAllZones('middle', e.target.checked));
document.getElementById('about-btn').addEventListener('click', () => document.getElementById('about').hidden = false);
document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => b.closest('.modal').hidden = true));

// Address search with autocomplete
const addr = document.getElementById('addr');
const addrSuggest = document.getElementById('addr-suggest');
let addrDebounce = null;
let addrSuggestions = [];
let addrActiveIdx = -1;

if (addr) {
  addr.addEventListener('input', () => {
    const v = addr.value.trim();
    clearTimeout(addrDebounce);
    if (v.length < 2) { hideAddrSuggest(); return; }
    addrDebounce = setTimeout(() => fetchAddrSuggest(v), 80);
  });
  addr.addEventListener('keydown', (e) => {
    if (!addrSuggest.hidden && addrSuggestions.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); addrActiveIdx = Math.min(addrActiveIdx + 1, addrSuggestions.length - 1); renderAddrSuggest(); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); addrActiveIdx = Math.max(addrActiveIdx - 1, 0); renderAddrSuggest(); return; }
      if (e.key === 'Enter') {
        e.preventDefault();
        const pick = addrSuggestions[addrActiveIdx >= 0 ? addrActiveIdx : 0];
        if (pick) selectAddrSuggest(pick);
        return;
      }
      if (e.key === 'Escape') { hideAddrSuggest(); return; }
    } else if (e.key === 'Enter') {
      e.preventDefault(); geocodeAddress(addr.value);
    }
  });
  addr.addEventListener('blur', () => setTimeout(hideAddrSuggest, 150));
  document.getElementById('addr-go').addEventListener('click', () => geocodeAddress(addr.value));
}

function fetchAddrSuggest(q) {
  const url = `https://geosearch.planninglabs.nyc/v2/autocomplete?size=6&text=${encodeURIComponent(q)}`;
  fetch(url)
    .then(r => r.json())
    .then(data => {
      addrSuggestions = (data.features || []).map(f => ({
        display_name: f.properties.label,
        lat: f.geometry.coordinates[1],
        lon: f.geometry.coordinates[0],
      }));
      addrActiveIdx = addrSuggestions.length ? 0 : -1;
      renderAddrSuggest();
    })
    .catch(() => hideAddrSuggest());
}

function renderAddrSuggest() {
  if (!addrSuggestions.length) { hideAddrSuggest(); return; }
  addrSuggest.innerHTML = addrSuggestions.map((r, i) =>
    `<div class="addr-suggest-item${i === addrActiveIdx ? ' active' : ''}" data-i="${i}">${escapeHtml(r.display_name)}</div>`
  ).join('');
  addrSuggest.hidden = false;
  addrSuggest.querySelectorAll('.addr-suggest-item').forEach(el => {
    el.addEventListener('mousedown', (e) => {
      e.preventDefault();
      selectAddrSuggest(addrSuggestions[+el.dataset.i]);
    });
  });
}

function hideAddrSuggest() {
  addrSuggest.hidden = true;
  addrSuggestions = [];
  addrActiveIdx = -1;
}

function selectAddrSuggest(r) {
  if (!r) return;
  addr.value = r.display_name;
  hideAddrSuggest();
  const latNum = parseFloat(r.lat), lonNum = parseFloat(r.lon);
  map.setView([latNum, lonNum], 15);
  if (activeAddressPin) map.removeLayer(activeAddressPin);
  activeAddressPin = L.circleMarker([latNum, lonNum], {
    radius: 10, color: '#ff7a45', weight: 3, fillColor: '#ff7a45', fillOpacity: 0.25,
  }).addTo(map);
  showZonedForPoint(latNum, lonNum);
}

function geocodeAddress(q) {
  q = (q || '').trim();
  if (!q) return;
  const url = `https://geosearch.planninglabs.nyc/v2/search?size=1&text=${encodeURIComponent(q)}`;
  fetch(url).then(r => r.json()).then(data => {
    const f = (data.features || [])[0];
    if (!f) { flashAddr('Address not found'); return; }
    const latNum = f.geometry.coordinates[1], lonNum = f.geometry.coordinates[0];
    map.setView([latNum, lonNum], 15);
    if (activeAddressPin) map.removeLayer(activeAddressPin);
    activeAddressPin = L.circleMarker([latNum, lonNum], {
      radius: 10, color: '#ff7a45', weight: 3, fillColor: '#ff7a45', fillOpacity: 0.25,
    }).addTo(map);
    showZonedForPoint(latNum, lonNum);
  }).catch(() => flashAddr('Address lookup failed'));
}
function flashAddr(msg) {
  const el = document.getElementById('addr-msg');
  if (!el) return;
  el.textContent = msg;
  el.style.opacity = 1;
  setTimeout(() => { el.style.opacity = 0; }, 2500);
}

function showZonedForPoint(lat, lon) {
  // Check which ES/MS zone (polygon) contains this point
  if (!zonesIndex) return;
  const allFeatures = [];
  for (const fs of zonesIndex.values()) for (const f of fs) allFeatures.push(f);
  const hit = allFeatures.filter(f => pointInFeature(lat, lon, f));
  if (!hit.length) return;
  if (activeHoverZoneLayer) map.removeLayer(activeHoverZoneLayer);
  activeHoverZoneLayer = L.geoJSON({ type:'FeatureCollection', features: hit }, {
    style: { color: '#ff7a45', weight: 2, fillColor: '#ff7a45', fillOpacity: 0.12, opacity: 0.9 },
    interactive: false,
  }).addTo(map);
  // list zoned schools in address-result tray
  const tray = document.getElementById('addr-result');
  if (!tray) return;
  tray.innerHTML = hit.flatMap(f => String(f.properties.dbn || '').split(',').map(x => x.trim()).filter(Boolean).map(dbn => {
    const s = schoolByDbn.get(dbn);
    const lvl = f.properties.zone_type || '';
    if (!s) return '';  // a zone polygon for a school that has since closed
    return `<div class="zone-hit" data-dbn="${dbn}"><b>${escapeHtml(s.name)}</b><span class="muted"> &middot; ${escapeHtml(lvl)}</span></div>`;
  })).join('');
  tray.querySelectorAll('.zone-hit[data-dbn]').forEach(el => {
    el.addEventListener('click', () => {
      const s = schoolByDbn.get(el.dataset.dbn);
      if (s) openSheet(s);
    });
  });
}

function pointInFeature(lat, lon, f) {
  const polys = [];
  const g = f.geometry;
  if (g.type === 'Polygon') polys.push(g.coordinates);
  else if (g.type === 'MultiPolygon') for (const p of g.coordinates) polys.push(p);
  for (const poly of polys) {
    const ring = poly[0];
    if (pointInRing(lon, lat, ring)) {
      let inHole = false;
      for (let i = 1; i < poly.length; i++) if (pointInRing(lon, lat, poly[i])) { inHole = true; break; }
      if (!inHole) return true;
    }
  }
  return false;
}
function pointInRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
    const hit = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-12) + xi);
    if (hit) inside = !inside;
  }
  return inside;
}

// ---------- Rendering ----------
const markerLayer = L.layerGroup().addTo(map);

function passesFilters(s) {
  if (!filters.sector.has(s.sector)) return false;
  let bandOk = false;
  for (const b of s._bands) if (filters.band.has(b)) { bandOk = true; break; }
  if (!bandOk) return false;
  if (filters.programs.size) {
    const ptags = new Set(s.programs || []);
    for (const p of filters.programs) if (!ptags.has(p)) return false;
  }
  if (filters.admissions.size) {
    const a = (s.admission || '').toLowerCase();
    let ok = false;
    for (const want of filters.admissions) if (a.includes(want.toLowerCase())) { ok = true; break; }
    if (!ok) return false;
  }
  if (filters.q) {
    const hay = `${s.name} ${s.neighborhood || ''} ${s.address || ''} ${s.boro || ''} ${s.dbn || ''}`.toLowerCase();
    if (!hay.includes(filters.q)) return false;
  }
  return true;
}

function renderSchools() {
  markerLayer.clearLayers();
  markerIndex.clear();
  let count = 0, hitCount = 0;
  const trajActive = filters.trajectory !== 'all';
  for (const s of allSchools) {
    if (!passesFilters(s)) continue;
    count++;
    const isHit = !trajActive || passesTrajectory(s);
    if (isHit) hitCount++;
    const cls = sectorClass(s);
    const tcls = trajectoryClass(s);
    const fadeCls = trajActive && !isHit ? ' faded' : '';
    let fill = '';
    if (colorBy) {
      const c = markerFill(s);
      fill = c ? ` cb" style="${s.sector === 'private' ? 'border-bottom-color' : 'background'}:${c}` : ' cb nodata';
    }
    const icon = L.divIcon({
      html: `<div class="mk ${cls}${fadeCls} ${tcls}${fill}" data-dbn="${s.dbn}"></div>`,
      className: 'mk-wrap',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
    const m = L.marker([s.lat, s.lon], { icon, keyboard: false });
    m.on('mouseover', () => { showZone(s); });
    m.on('mouseout', () => { hideZone(); });
    m.on('click', (e) => onSchoolClick(e, s));
    m.addTo(markerLayer);
    markerIndex.set(s.dbn, m);
  }
  const base = `${count.toLocaleString()} of ${allSchools.length.toLocaleString()} schools shown`;
  document.getElementById('result-count').textContent =
    filters.trajectory === 'all' ? base : `${base} · ${hitCount.toLocaleString()} highlighted`;
  if (typeof markSelected === 'function') markSelected();
  if (typeof renderLineup === 'function' && !document.getElementById('lineup').hidden) renderLineup();
}

// ---------- Zone hover ----------
function showZone(s) {
  if (!filters.showZones) return;
  if (!s.has_zone) return;
  const features = zonesIndex.get(s.dbn);
  if (!features) return;
  hideZone();
  activeHoverZoneLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
    style: { color: '#ff7a45', weight: 2, fillColor: '#ff7a45', fillOpacity: 0.15, opacity: 0.8 },
    interactive: false,
  }).addTo(map);
}
function hideZone() {
  if (activeHoverZoneLayer) { map.removeLayer(activeHoverZoneLayer); activeHoverZoneLayer = null; }
}

// ---------- All-zones overlays (elementary / middle) ----------
const ALL_ZONE_STYLES = {
  elementary: { color: '#e6c547', weight: 1, fillColor: '#e6c547', fillOpacity: 0.06, opacity: 0.55 },
  middle:     { color: '#5bb8e6', weight: 1, fillColor: '#5bb8e6', fillOpacity: 0.06, opacity: 0.55 },
};
const allZoneLayers = { elementary: null, middle: null };
let allZonesRaw = null;

function toggleAllZones(level, on) {
  if (!on) {
    if (allZoneLayers[level]) { map.removeLayer(allZoneLayers[level]); allZoneLayers[level] = null; }
    return;
  }
  const build = (zones) => {
    const feats = zones.features.filter(f => (f.properties.zone_type || '') === level);
    const layer = L.geoJSON({ type: 'FeatureCollection', features: feats }, {
      style: ALL_ZONE_STYLES[level],
      interactive: false,
    });
    layer.addTo(map);
    if (layer.bringToBack) layer.bringToBack();
    if (choroLayer && choroLayer.bringToBack) choroLayer.bringToBack();
    allZoneLayers[level] = layer;
  };
  if (allZonesRaw) { build(allZonesRaw); return; }
  fetch('./data/zones.geojson').then(r => r.json()).then(z => { allZonesRaw = z; build(z); });
}

// ---------- Photo: Street View, else a Wikipedia article about the school ----------
function loadPhoto(s, photoEl) {
  const lat = photoEl.dataset.lat, lon = photoEl.dataset.lon;
  const metaUrl = `https://maps.googleapis.com/maps/api/streetview/metadata?location=${lat},${lon}&key=${GSV_KEY}`;
  fetch(metaUrl)
    .then(r => r.json())
    .then(meta => {
      if (meta && meta.status === 'OK') {
        const img = new Image();
        const src = `https://maps.googleapis.com/maps/api/streetview?size=380x170&location=${lat},${lon}&fov=75&pitch=5&key=${GSV_KEY}`;
        img.onload = () => { photoEl.style.backgroundImage = `url('${src}')`; photoEl.style.display = ''; photoEl.innerHTML = ''; };
        img.onerror = () => tryWikipediaPhoto(s, photoEl);
        img.src = src;
      } else {
        tryWikipediaPhoto(s, photoEl);
      }
    })
    .catch(() => tryWikipediaPhoto(s, photoEl));
}

function tryWikipediaPhoto(s, photoEl) {
  const q = encodeURIComponent(s.name);
  fetch(`https://en.wikipedia.org/w/api.php?origin=*&action=query&format=json&generator=search&gsrsearch=${q}&gsrlimit=1`)
    .then(r => r.json())
    .then(data => {
      const pages = data && data.query && data.query.pages;
      if (!pages) return showEmpty(photoEl);
      const title = Object.values(pages)[0]?.title;
      // Only use an article about a school. Searching "P.S. 307 Daniel Hale
      // Williams" otherwise returns a portrait of the school's namesake.
      if (!title || !/school|academy|high|campus|institute|college|lyc[eé]e/i.test(title)) return showEmpty(photoEl);
      return fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}`)
        .then(r => r.json())
        .then(summary => {
          const img = summary.originalimage && summary.originalimage.source;
          if (img) {
            photoEl.style.backgroundImage = `url('${img}')`;
            photoEl.style.display = '';
            photoEl.innerHTML = '';
          } else {
            showEmpty(photoEl);
          }
        })
        .catch(() => showEmpty(photoEl));
    })
    .catch(() => showEmpty(photoEl));
}

function showEmpty(photoEl) {
  photoEl.style.display = 'none';
}

function renderNearby(s) {
  // 4 nearest same-sector + same-band schools (excluding this one)
  const myBand = ['ES', 'MS', 'HS', 'PK'].find(b => s._bands && s._bands.has(b)) || 'ES';
  const near = allSchools
    .filter(x => x.dbn !== s.dbn && x._bands && x._bands.has(myBand))
    .map(x => ({ s: x, d: haversine(s.lat, s.lon, x.lat, x.lon) }))
    .sort((a, b) => a.d - b.d)
    .slice(0, 4);
  if (!near.length) return '';
  const chips = near.map(n => `<span class="nearby-chip" data-dbn="${n.s.dbn}"><span class="mk-mini ${sectorClass(n.s)}"></span>${escapeHtml(truncate(n.s.name, 26))}<span class="muted"> ${n.d.toFixed(1)}mi</span></span>`).join('');
  return `<div class="section"><h4>Nearby schools (${myBand})</h4><div class="nearby">${chips}</div></div>`;
}

function barRow(label, value, color) {
  const pct = value == null ? 0 : (value > 1 ? value : value * 100);
  const w = Math.min(100, Math.max(0, pct));
  return `<div class="bar-row">
    <div class="bar-label">${escapeHtml(label)}</div>
    <div class="bar-wrap"><div class="bar-fill" style="width:${w.toFixed(1)}%;background:${color}"></div></div>
    <div class="bar-val">${w < 1 && w > 0 ? '<1%' : Math.round(w) + '%'}</div>
  </div>`;
}

function haversine(lat1, lon1, lat2, lon2) {
  const R = 3959; const toR = Math.PI / 180;
  const dLat = (lat2 - lat1) * toR;
  const dLon = (lon2 - lon1) * toR;
  const a = Math.sin(dLat/2)**2 + Math.cos(lat1*toR)*Math.cos(lat2*toR)*Math.sin(dLon/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function ensureHttp(u) { return /^https?:/.test(u) ? u : 'https://' + u; }
function truncate(s, n) { s = String(s||''); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; }

// ---------- Click: open the sheet; shift-click pins to the lineup ----------
function onSchoolClick(e, s) {
  if (e.originalEvent && e.originalEvent.shiftKey) {
    e.originalEvent.preventDefault();
    togglePin(s);
    return false;
  }
  openSheet(s, { noPan: true });
}

// ---------- Choropleth: children per tract ----------
const CHORO_COLORS = ['#d4f1ef', '#84d5d0', '#3aa99f', '#1c6e6a', '#0d3c3a'];
function toggleChoropleth(on) {
  document.getElementById('choro-legend').hidden = !on;
  if (on) {
    if (choroLayer) { choroLayer.addTo(map); return; }
    fetch('./data/tracts.geojson').then(r => r.json()).then(gj => {
      const counts = gj.features.map(f => (f.properties.children || {}).total || 0).filter(v => v > 0).sort((a, b) => a - b);
      const q = p => counts[Math.floor(counts.length * p)] || 0;
      const breaks = [q(0.2), q(0.4), q(0.6), q(0.8)];
      const colorFor = v => {
        if (v <= 0) return null;
        for (let i = 0; i < breaks.length; i++) if (v <= breaks[i]) return CHORO_COLORS[i];
        return CHORO_COLORS[4];
      };
      choroLayer = L.geoJSON(gj, {
        style: f => {
          const v = (f.properties.children || {}).total || 0;
          const c = colorFor(v);
          return c
            ? { color: c, weight: 0.3, fillColor: c, fillOpacity: 0.55, opacity: 0.8 }
            : { weight: 0, fillOpacity: 0 };
        },
        interactive: false,
      });
      // Legend numbers: show the four break thresholds
      const lbl = document.getElementById('choro-labels');
      if (lbl) {
        const fmt = n => n >= 1000 ? `${(n/1000).toFixed(n>=10000?0:1)}k` : String(Math.round(n));
        lbl.innerHTML = `<span>0</span><span>${fmt(breaks[0])}</span><span>${fmt(breaks[1])}</span><span>${fmt(breaks[2])}</span><span>${fmt(breaks[3])}</span><span>${fmt(breaks[3])}+</span>`;
      }
      // Insert choropleth UNDER markers by adding to map then re-ordering.
      choroLayer.addTo(map);
      if (choroLayer.bringToBack) choroLayer.bringToBack();
    });
  } else {
    if (choroLayer) map.removeLayer(choroLayer);
  }
}

// ---------- Deep link ----------
function handleDeepLink() {
  const m = (window.location.hash || '').match(/school=([^&]+)/);
  if (!m) return;
  const s = schoolByDbn.get(decodeURIComponent(m[1]));
  if (s && s.dbn !== selectedDbn) openSheet(s, { zoom: 15 });
}
window.addEventListener('hashchange', handleDeepLink);

// close modal on backdrop click
document.getElementById('about').addEventListener('click', e => {
  if (e.target.id === 'about') e.target.hidden = true;
});
