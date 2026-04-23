/* NYC schools atlas */
const GSV_KEY = "AIzaSyBPEjOGoN9DTFfr4BaLoHNIVM_FHNQNeFI";

const map = L.map('map', { preferCanvas: true, zoomControl: true, minZoom: 10, maxZoom: 18 })
  .setView([40.7128, -74.0060], 11);

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://carto.com/">CARTO</a> &middot; &copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a> &middot; Schools DOE/NCES &middot; Children ACS 2018&ndash;2022',
  subdomains: 'abcd', maxZoom: 20,
}).addTo(map);

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png', {
  subdomains: 'abcd', maxZoom: 20, pane: 'shadowPane',
}).addTo(map);

// -------------- State --------------
let allSchools = [];
let markerIndex = new Map();
let compareIds = [];
let activeHoverZoneLayer = null;
let activeAddressPin = null;
let zonesIndex = null;
let dotsLayer = null;

const filters = {
  q: '',
  sector: new Set(['public','charter','private']),
  band: new Set(['ES','MS','HS','PK']),
  programs: new Set(),
  admissions: new Set(),
  showZones: true,
};

const PROGRAM_FILTER_LIST = [
  'Specialized High School',
  'International Baccalaureate',
  'Career and Technical Education',
  'Gifted and Talented',
  'Dual language',
  'ASD Nest',
  'ASD Horizon',
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
const fmtPct = v => (v == null) ? '—' : `${Math.round(v * (v <= 1 ? 100 : 1))}%`;
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
  fetch('./data/schools.json').then(r => r.json()),
  fetch('./data/zones.geojson').then(r => r.json()),
]).then(([schools, zones]) => {
  allSchools = schools;
  zonesIndex = new Map();
  for (const f of zones.features) {
    const dbn = f.properties && f.properties.dbn;
    if (!dbn) continue;
    if (!zonesIndex.has(dbn)) zonesIndex.set(dbn, []);
    zonesIndex.get(dbn).push(f);
  }
  for (const s of schools) s._bands = detectBand(s);
  buildProgramFilters();
  buildAdmissionFilters();
  renderSchools();
  handleDeepLink();
}).catch(err => {
  console.error(err);
  document.getElementById('result-count').textContent = 'Failed to load data.';
});

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
document.getElementById('q').addEventListener('input', e => { filters.q = e.target.value.trim().toLowerCase(); renderSchools(); });
document.getElementById('lyr-zone').addEventListener('change', e => { filters.showZones = e.target.checked; });
document.getElementById('lyr-dots').addEventListener('change', e => toggleDots(e.target.checked));
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
    if (v.length < 3) { hideAddrSuggest(); return; }
    addrDebounce = setTimeout(() => fetchAddrSuggest(v), 250);
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
  const viewbox = '-74.2591,40.9176,-73.7004,40.4774';
  const url = `https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&limit=6&viewbox=${viewbox}&bounded=1&q=${encodeURIComponent(q)}`;
  fetch(url, { headers: { 'Accept-Language': 'en' } })
    .then(r => r.json())
    .then(arr => {
      addrSuggestions = (arr || []).filter(r => {
        const a = r.address || {};
        return (a.state === 'New York' || a.city === 'New York' || a['ISO3166-2-lvl4'] === 'US-NY');
      });
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
  const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(q + ', New York City')}&limit=1`;
  fetch(url, { headers: { 'Accept-Language': 'en' } }).then(r => r.json()).then(arr => {
    if (!arr || !arr.length) { flashAddr('Address not found'); return; }
    const { lat, lon } = arr[0];
    const latNum = parseFloat(lat), lonNum = parseFloat(lon);
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
  tray.innerHTML = hit.map(f => {
    const dbn = f.properties.dbn;
    const s = allSchools.find(x => x.dbn === dbn);
    const lvl = f.properties.zone_type || '';
    if (!s) return `<div class="zone-hit"><b>${escapeHtml(dbn)}</b> ${escapeHtml(lvl)}</div>`;
    return `<div class="zone-hit" data-dbn="${dbn}"><b>${escapeHtml(s.name)}</b><span class="muted"> &middot; ${escapeHtml(lvl)}</span></div>`;
  }).join('');
  tray.querySelectorAll('.zone-hit[data-dbn]').forEach(el => {
    el.addEventListener('click', () => {
      const dbn = el.dataset.dbn;
      const m = markerIndex.get(dbn);
      if (m) { m.openPopup(); map.setView(m.getLatLng(), 16); }
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
  if (filters.programs.size && s.sector !== 'private') {
    const ptags = new Set(s.programs);
    for (const p of filters.programs) if (!ptags.has(p)) return false;
  }
  if (filters.admissions.size && s.sector !== 'private') {
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
  let count = 0;
  for (const s of allSchools) {
    if (!passesFilters(s)) continue;
    count++;
    const cls = sectorClass(s);
    const icon = L.divIcon({
      html: `<div class="mk ${cls}" data-dbn="${s.dbn}"></div>`,
      className: 'mk-wrap',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
    const m = L.marker([s.lat, s.lon], { icon, keyboard: false });
    m.on('mouseover', () => { showZone(s); });
    m.on('mouseout', () => { hideZone(); });
    m.on('click', (e) => onSchoolClick(e, s));
    m.bindPopup(() => renderCard(s), { maxWidth: 380, autoPan: true, closeButton: true, offset: [0, -4] });
    m.on('popupopen', () => { window.location.hash = `school=${encodeURIComponent(s.dbn)}`; wireUpCardEvents(s); });
    m.addTo(markerLayer);
    markerIndex.set(s.dbn, m);
  }
  document.getElementById('result-count').textContent =
    `${count.toLocaleString()} of ${allSchools.length.toLocaleString()} schools shown`;
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

// ---------- Photo with fallback ----------
function photoUrls(s) {
  const gsv = `https://maps.googleapis.com/maps/api/streetview?size=380x170&location=${s.lat},${s.lon}&fov=75&pitch=5&key=${GSV_KEY}`;
  const mapillaryQ = `https://graph.mapillary.com/images?access_token=MLY|4142433049200173|72206abe5035850d6743b23a49c41333&fields=id&limit=1&bbox=${s.lon-0.001},${s.lat-0.001},${s.lon+0.001},${s.lat+0.001}`;
  return { gsv, mapillaryQ };
}

// ---------- Card ----------
function renderCard(s) {
  const div = document.createElement('div');
  div.className = 'card';
  const photo = `<div class="photo" data-photo data-lat="${s.lat}" data-lon="${s.lon}" style="display:none"></div>`;

  const sectorLabel = s.sector === 'public' ? 'Public' : s.sector === 'charter' ? 'Charter' : 'Private';
  const metaBits = [
    s.grades ? `Grades ${escapeHtml(s.grades)}` : '',
    s.boro ? escapeHtml(s.boro) : '',
    s.neighborhood ? escapeHtml(s.neighborhood) : '',
    s.dbn && !s.dbn.startsWith('PRIV-') ? `${s.dbn}` : '',
  ].filter(Boolean).join('<span class="sep">&middot;</span>');

  const tabs = [
    ['overview', 'Overview'],
    ['academics', 'Academics'],
    ['admissions', 'Admissions'],
    ['community', 'Community'],
  ];
  const tabBar = `<div class="tabs">${tabs.map(([k,l],i) =>
    `<button class="tab ${i===0?'active':''}" data-tab="${k}">${l}</button>`).join('')}</div>`;

  div.innerHTML = `
    ${photo}
    <div class="body">
      <div class="header-row">
        <h3>${escapeHtml(s.name || 'Unnamed school')}</h3>
        <span class="sector-badge ${s.sector}">${sectorLabel}</span>
      </div>
      <div class="meta">${metaBits}</div>
      ${tabBar}
      <div class="tab-panes">
        <div class="pane active" data-pane="overview">${renderOverviewPane(s)}</div>
        <div class="pane" data-pane="academics">${renderAcademicsPane(s)}</div>
        <div class="pane" data-pane="admissions">${renderAdmissionsPane(s)}</div>
        <div class="pane" data-pane="community">${renderCommunityPane(s)}</div>
      </div>
      ${renderLinks(s)}
      ${s.address ? `<div class="note">${escapeHtml(s.address)}${s.zip ? ', ' + escapeHtml(s.zip) : ''}</div>` : ''}
    </div>`;
  return div;
}

function wireUpCardEvents(s) {
  const root = document.querySelector('.leaflet-popup-content .card');
  if (!root) return;
  root.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      root.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
      root.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      root.querySelector(`.pane[data-pane="${btn.dataset.tab}"]`).classList.add('active');
    });
  });
  root.querySelectorAll('.nearby-chip').forEach(c => {
    c.addEventListener('click', () => {
      const dbn = c.dataset.dbn;
      const m = markerIndex.get(dbn);
      if (m) { m.openPopup(); map.panTo(m.getLatLng()); }
    });
  });
  const photo = root.querySelector('[data-photo]');
  if (photo) loadPhoto(s, photo);
}

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
      if (!title) return showEmpty(photoEl);
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

function renderOverviewPane(s) {
  const d = s.demo;
  let html = '';
  const latestEnroll = (d && d.enrollment_latest != null) ? d.enrollment_latest : (d && d.enrollment);
  const latestYear = (d && d.year_enrollment) ? d.year_enrollment : (d && d.year);
  if (latestEnroll != null) {
    const spark = sparklineSVG(s.trend);
    html += `<div class="section enrollment-row">
      <div>
        <div class="enrollment-num">${fmtNum(latestEnroll)}</div>
        <div class="enrollment-label">enrolled (${escapeHtml(latestYear || '')})</div>
      </div>
      <div class="spark-wrap">${spark}</div>
    </div>`;
  }
  if (d) {
    const rows = [
      ['Asian', d.pct_asian, 'var(--demo-asian)'],
      ['Black', d.pct_black, 'var(--demo-black)'],
      ['Hispanic', d.pct_hispanic, 'var(--demo-hisp)'],
      ['White', d.pct_white, 'var(--demo-white)'],
      ['Multi / other', d.pct_multi, 'var(--demo-multi)'],
    ].filter(r => r[1] != null && r[1] > 0).map(([l,v,c]) => barRow(l,v,c)).join('');
    html += `<div class="section"><h4>Race / ethnicity</h4><div class="bars">${rows || '<div class="note">Not reported</div>'}</div></div>`;
  } else if (s.sector === 'private') {
    html += `<div class="section note">Private schools do not report demographic data publicly. NCES provides only location and school name. Tuition is published on each school&rsquo;s own website.</div>`;
  }
  if (s.overview) html += `<div class="section note">${escapeHtml(truncate(s.overview, 320))}</div>`;
  html += renderNearby(s);
  return html;
}

function renderAcademicsPane(s) {
  let html = '';
  const q = s.quality;
  if (q) {
    const items = [];
    if (q.attendance != null) items.push(stat('Avg attendance', fmtPct(q.attendance)));
    if (q.chronic_absent != null) items.push(stat('Chronic absence', fmtPct(q.chronic_absent)));
    if (q.grad_4yr != null) items.push(stat('4-yr graduation', fmtPct(q.grad_4yr)));
    if (q.ccr_4yr != null) items.push(stat('College &amp; career ready', fmtPct(q.ccr_4yr / 100)));
    html += `<div class="section"><h4>Outcomes (2023&ndash;24)</h4><div class="stat-grid">${items.join('')}</div></div>`;
  } else {
    html += `<div class="section note">No 2023&ndash;24 quality metrics published for this school (common for charters, private schools, and very small programs).</div>`;
  }
  if (s.programs && s.programs.length) {
    const chips = s.programs.slice(0, 24).map(p => {
      let cls = 'tag';
      if (p === 'Specialized High School' || p === 'International Baccalaureate') cls += ' special';
      else if (p.startsWith('District 75')) cls += ' d75';
      else if (p === 'Fully accessible') cls += ' acc';
      return `<span class="${cls}">${escapeHtml(truncate(p, 60))}</span>`;
    }).join('');
    html += `<div class="section"><h4>Programs &amp; designations</h4><div class="tags">${chips}</div></div>`;
  }
  return html || '<div class="note">No academic data available.</div>';
}

function renderAdmissionsPane(s) {
  let html = '';
  if (s.admission) {
    html += `<div class="section"><h4>Admissions method</h4><div class="tags"><span class="tag">${escapeHtml(s.admission)}</span></div></div>`;
  }
  if (s.admission_programs && s.admission_programs.length) {
    const rows = s.admission_programs.slice(0, 8).map(p => {
      const head = `<div class="adm-head"><b>${escapeHtml(p.name || p.code || 'Program')}</b>${p.method ? ` <span class="muted">&middot; ${escapeHtml(p.method)}</span>` : ''}</div>`;
      const stats = [];
      if (p.seats) stats.push(`<span>${escapeHtml(String(p.seats))} seats</span>`);
      if (p.applicants) stats.push(`<span>${escapeHtml(String(p.applicants))} applicants</span>`);
      if (p.apps_per_seat) stats.push(`<span>${escapeHtml(String(p.apps_per_seat))}:1</span>`);
      if (p.offer_rate) stats.push(`<span>${escapeHtml(String(p.offer_rate))}</span>`);
      const priorities = [p.priority1, p.priority2].filter(Boolean).map(t => `<div class="pri">${escapeHtml(truncate(t, 140))}</div>`).join('');
      return `<div class="adm-row">${head}<div class="adm-stats">${stats.join('')}</div>${priorities}</div>`;
    }).join('');
    html += `<div class="section"><h4>Programs offered</h4>${rows}</div>`;
  }
  if (!html) html = `<div class="note">Admissions information not published for this school.</div>`;
  return html;
}

function renderCommunityPane(s) {
  let html = '';
  const d = s.demo;
  if (d) {
    const svcRows = [
      ['Students w/ disabilities', d.pct_swd, '#e06c75'],
      ['English learners', d.pct_ell, '#56b6c2'],
      ['Poverty', d.poverty, '#d19a66'],
      ['Economic Need Index', d.eni, '#c678dd'],
    ].filter(r => r[1] != null).map(([l,v,c]) => barRow(l,v,c)).join('');
    html += `<div class="section"><h4>Student body</h4><div class="bars">${svcRows || '<div class="note">Not reported</div>'}</div></div>`;
  }
  if (s.sector === 'public' && s.has_zone) {
    html += `<div class="section note">This school has an attendance zone &mdash; hover the marker to see it. Students who live inside the zone have priority.</div>`;
  } else if (s.sector === 'public' && !s.has_zone) {
    html += `<div class="section note">This school is unzoned or screened &mdash; students apply from across the district or citywide.</div>`;
  } else if (s.sector === 'charter') {
    html += `<div class="section note">Charter schools admit by lottery across their district or citywide, not by residential zone.</div>`;
  } else if (s.sector === 'private') {
    html += `<div class="section note">Private school &mdash; tuition, admissions and enrollment details are set by the school. Visit the school&rsquo;s website for specifics.</div>`;
  }
  return html || '<div class="note">No community data available.</div>';
}

function renderNearby(s) {
  // 4 nearest same-sector + same-band schools (excluding this one)
  const myBand = [...s._bands || []][0] || 'ES';
  const near = allSchools
    .filter(x => x.dbn !== s.dbn && x._bands && x._bands.has(myBand))
    .map(x => ({ s: x, d: haversine(s.lat, s.lon, x.lat, x.lon) }))
    .sort((a, b) => a.d - b.d)
    .slice(0, 4);
  if (!near.length) return '';
  const chips = near.map(n => `<span class="nearby-chip" data-dbn="${n.s.dbn}"><span class="mk-mini ${sectorClass(n.s)}"></span>${escapeHtml(truncate(n.s.name, 26))}<span class="muted"> ${n.d.toFixed(1)}mi</span></span>`).join('');
  return `<div class="section"><h4>Nearby schools (${myBand})</h4><div class="nearby">${chips}</div></div>`;
}

function renderLinks(s) {
  return `<div class="links">
    ${s.website ? `<a href="${ensureHttp(s.website)}" target="_blank" rel="noopener">Official site</a>` : ''}
    <a href="https://www.google.com/maps/search/?api=1&query=${s.lat},${s.lon}" target="_blank" rel="noopener">Map</a>
  </div>`;
}

function stat(label, value) {
  return `<div class="stat"><div class="stat-label">${label}</div><div class="stat-val">${value}</div></div>`;
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

function sparklineSVG(trend) {
  const pts = (trend || []).filter(r => r[1] != null);
  if (pts.length < 2) return '';
  const w = 180, h = 38, pad = 2, labelBand = 12;
  const plotH = h - labelBand;
  const vals = pts.map(p => p[1]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const range = Math.max(1, max - min);
  const dx = (w - pad * 2) / (pts.length - 1);
  const yAt = v => pad + (plotH - pad * 2) * (1 - (v - min) / range);
  const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${(pad + i * dx).toFixed(1)},${yAt(p[1]).toFixed(1)}`).join(' ');
  const lastX = pad + (pts.length - 1) * dx;
  const lastY = yAt(pts[pts.length - 1][1]);
  const dir = pts[pts.length - 1][1] >= pts[0][1] ? '#5ca57a' : '#c0604e';
  const firstYr = pts[0][0], lastYr = pts[pts.length - 1][0];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <path d="${path}" fill="none" stroke="${dir}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${lastX}" cy="${lastY}" r="2.4" fill="${dir}"/>
    <text x="${pad}" y="${h-2}" font-size="9" fill="#676d7e">${firstYr}</text>
    <text x="${w-2}" y="${h-2}" font-size="9" fill="#676d7e" text-anchor="end">${lastYr}</text>
  </svg>`;
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

// ---------- Compare (shift-click) ----------
function onSchoolClick(e, s) {
  if (e.originalEvent && e.originalEvent.shiftKey) {
    e.originalEvent.preventDefault();
    toggleCompare(s);
    return false;
  }
}
function toggleCompare(s) {
  const i = compareIds.findIndex(x => x.dbn === s.dbn);
  if (i >= 0) compareIds.splice(i, 1);
  else if (compareIds.length < 2) compareIds.push(s);
  else compareIds = [compareIds[1], s];
  renderCompareTray();
  renderComparePanel();
}
function renderCompareTray() {
  const empty = document.getElementById('compare-empty');
  const tray = document.getElementById('compare-tray');
  if (!compareIds.length) { empty.style.display = ''; tray.hidden = true; return; }
  empty.style.display = 'none'; tray.hidden = false;
  tray.innerHTML = compareIds.map(s => `
    <div class="cmp-pill"><span>${escapeHtml(s.name)}</span><span class="x" data-dbn="${s.dbn}">&times;</span></div>
  `).join('');
  tray.querySelectorAll('.x').forEach(x => x.addEventListener('click', () => {
    compareIds = compareIds.filter(s => s.dbn !== x.dataset.dbn);
    renderCompareTray(); renderComparePanel();
  }));
}
function renderComparePanel() {
  let panel = document.getElementById('cmp-panel');
  if (!panel) { panel = document.createElement('div'); panel.id = 'cmp-panel'; document.body.appendChild(panel); }
  if (compareIds.length < 2) { panel.classList.remove('active'); panel.innerHTML=''; return; }
  const [a, b] = compareIds;
  const metrics = [
    ['Enrollment', s => s.demo ? fmtNum(s.demo.enrollment) : '—'],
    ['% Asian', s => s.demo ? fmtPct(s.demo.pct_asian) : '—'],
    ['% Black', s => s.demo ? fmtPct(s.demo.pct_black) : '—'],
    ['% Hispanic', s => s.demo ? fmtPct(s.demo.pct_hispanic) : '—'],
    ['% White', s => s.demo ? fmtPct(s.demo.pct_white) : '—'],
    ['% SWD', s => s.demo ? fmtPct(s.demo.pct_swd) : '—'],
    ['% ELL', s => s.demo ? fmtPct(s.demo.pct_ell) : '—'],
    ['Poverty', s => s.demo ? fmtPct(s.demo.poverty) : '—'],
    ['Attendance', s => s.quality && s.quality.attendance != null ? fmtPct(s.quality.attendance) : '—'],
    ['Graduation', s => s.quality && s.quality.grad_4yr != null ? fmtPct(s.quality.grad_4yr) : '—'],
    ['Grade span', s => s.grades || '—'],
    ['Admission', s => s.admission || '—'],
  ];
  const rows = metrics.map(([label, fn]) => `<tr><td style="color:#676d7e">${label}</td><td>${fn(a)}</td><td>${fn(b)}</td></tr>`).join('');
  panel.innerHTML = `
    <button class="close" onclick="document.getElementById('cmp-panel').classList.remove('active')">&times;</button>
    <div class="cmp-grid">
      <div><div class="col-head">Comparing</div><h4>${escapeHtml(a.name)}</h4><div style="color:#676d7e;font-size:11px">${escapeHtml(a.boro||'')}</div></div>
      <div><div class="col-head">vs.</div><h4>${escapeHtml(b.name)}</h4><div style="color:#676d7e;font-size:11px">${escapeHtml(b.boro||'')}</div></div>
      <div>
        <div class="col-head">Metrics</div>
        <table style="width:100%;font-size:12px;border-collapse:collapse">
          <thead><tr><th></th><th style="text-align:left">A</th><th style="text-align:left">B</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
  panel.classList.add('active');
}

// ---------- Dot density ----------
function toggleDots(on) {
  document.getElementById('dot-legend').hidden = !on;
  if (on) {
    if (dotsLayer) { dotsLayer.addTo(map); return; }
    fetch('./data/dots.json').then(r => r.json()).then(dots => {
      const renderer = L.canvas({ padding: 0.5 });
      const fg = L.layerGroup();
      const COLOR = { a: '#ff9a9e', b: '#fad0c4', c: '#a1c4fd' };
      for (const [lat, lon, cat] of dots) {
        L.circleMarker([lat, lon], {
          renderer, radius: 1.4, color: COLOR[cat], fillColor: COLOR[cat],
          weight: 0, fillOpacity: 0.75, interactive: false,
        }).addTo(fg);
      }
      dotsLayer = fg;
      dotsLayer.addTo(map);
    });
  } else {
    if (dotsLayer) map.removeLayer(dotsLayer);
  }
}

// ---------- Deep link ----------
function handleDeepLink() {
  const m = (window.location.hash || '').match(/school=([^&]+)/);
  if (!m) return;
  const dbn = decodeURIComponent(m[1]);
  const marker = markerIndex.get(dbn);
  if (marker) { map.setView(marker.getLatLng(), 15); marker.openPopup(); }
}
window.addEventListener('hashchange', handleDeepLink);

// close modal on backdrop click
document.getElementById('about').addEventListener('click', e => {
  if (e.target.id === 'about') e.target.hidden = true;
});
