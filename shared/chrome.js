/* Inject unified header + footer.
   Each page declares its section by setting <body data-section="map|enrollment|spending|special-ed|school-day|curriculum|about">.
   Header expects a host element <div id="site-header"></div> (or it auto-prepends to <body>). */

(function () {
  const NAV = [
    { id: 'map',         label: 'Map',          href: 'ROOT/' },
    { id: 'enrollment',  label: 'Enrollment',   href: 'ROOT/enrollment/' },
    { id: 'spending',    label: 'Spending',     href: 'ROOT/spending/' },
    { id: 'special-ed',  label: 'Special ed',   href: 'ROOT/special-ed/' },
    { id: 'school-day',  label: 'School day',   href: 'ROOT/school-day/' },
    { id: 'curriculum',  label: 'Curriculum',   href: 'ROOT/curriculum/' },
    { id: 'about',       label: 'About',        href: 'ROOT/about/' },
  ];
  const SECTION_ACCENT = {
    map:        '#ff7c53',
    enrollment: '#217ebe',
    spending:   '#57aa4a',
    'special-ed':'#e7466d',
    'school-day':'#dde44c',
    curriculum: '#9b9fbc',
    about:      '#9099ab',
  };

  function rootPath() {
    // Find the project root by counting how deep the current page is.
    // The script is /shared/chrome.js — we want pages at /, /enrollment/, etc.
    const here = location.pathname;
    // strip trailing index.html
    const norm = here.replace(/index\.html$/, '');
    // count directory segments after the GH-Pages repo prefix if present
    // simplest: figure depth from a known anchor — the chrome.js URL
    const scripts = document.querySelectorAll('script[src]');
    for (const s of scripts) {
      const m = s.getAttribute('src').match(/^(.*?)shared\/chrome\.js/);
      if (m) return m[1] || './';
    }
    return './';
  }

  function build() {
    const section = document.body.dataset.section || 'map';
    const root = rootPath();
    const accent = SECTION_ACCENT[section] || '#ff7c53';
    document.documentElement.style.setProperty('--section-accent', accent);

    const navHtml = NAV.map(n => {
      const href = n.href.replace('ROOT', root.replace(/\/$/, ''));
      const cls = n.id === section ? ' class="active"' : '';
      return `<a href="${href}"${cls}>${n.label}</a>`;
    }).join('');

    const homeHref = root.replace(/\/$/, '') + '/';
    const headerHtml = `
      <div class="site-header">
        <div class="site-header-inner">
          <a class="site-brand" href="${homeHref}">
            <span class="mark">NYC Schools <em>atlas</em></span>
            <span class="tag">Map &middot; data &middot; spending &middot; standards</span>
          </a>
          <nav class="site-nav" aria-label="Sections">${navHtml}</nav>
        </div>
        <div class="site-section-bar"></div>
      </div>`;

    const host = document.getElementById('site-header');
    if (host) host.outerHTML = headerHtml;
    else document.body.insertAdjacentHTML('afterbegin', headerHtml);

    // Footer (skip if author opted out with data-no-footer)
    if (document.body.dataset.noFooter !== 'true') {
      const footHost = document.getElementById('site-footer');
      const sources = `
        <div class="footer-line">Sources: NYC DOE InfoHub &middot; NYSED &middot; NYC Open Data &middot; US Census ACS &middot; NCES &middot; Mayor's Management Report &middot; NYC Comptroller. Every page links to its specific provenance.</div>
        <div class="footer-line">Built by Josh Greenman. <a href="${root.replace(/\/$/, '')}/about/">Methodology &amp; data sources</a> &middot; <a href="https://github.com/joshgreenman1973/nyc-schools-atlas">Source on GitHub</a></div>`;
      if (footHost) footHost.outerHTML = `<footer class="site-footer">${sources}</footer>`;
      else document.body.insertAdjacentHTML('beforeend', `<footer class="site-footer">${sources}</footer>`);
    }
  }

  // Inject Fraunces + Inter if not already present
  function ensureFonts() {
    if (!document.querySelector('link[href*="fonts.googleapis.com"][href*="Fraunces"]')) {
      const pc1 = document.createElement('link'); pc1.rel = 'preconnect'; pc1.href = 'https://fonts.googleapis.com';
      const pc2 = document.createElement('link'); pc2.rel = 'preconnect'; pc2.href = 'https://fonts.gstatic.com'; pc2.crossOrigin = '';
      const l = document.createElement('link');
      l.rel = 'stylesheet';
      l.href = 'https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700;9..144,800&family=Inter:wght@400;500;600;700&display=swap';
      document.head.appendChild(pc1); document.head.appendChild(pc2); document.head.appendChild(l);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { ensureFonts(); build(); });
  } else { ensureFonts(); build(); }
})();
