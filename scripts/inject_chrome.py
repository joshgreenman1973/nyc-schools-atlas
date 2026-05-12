#!/usr/bin/env python3
"""Inject the shared chrome (CSS link + body attrs + header host + script) into a satellite page.
Idempotent: re-running won't duplicate."""
import re, sys, pathlib

CHROME_CSS = '<link rel="stylesheet" href="../shared/chrome.css?v=13" />'
CHROME_JS  = '<script src="../shared/chrome.js?v=13"></script>'
HEADER_HOST = '<div id="site-header"></div>'

def inject(path: pathlib.Path, section: str):
    s = path.read_text()
    if 'shared/chrome.css' not in s:
        # insert chrome.css just before </head>
        s = re.sub(r'</head>', f'  {CHROME_CSS}\n</head>', s, count=1, flags=re.IGNORECASE)
    if 'data-section=' not in s:
        # add data-section to body tag
        s = re.sub(r'<body([^>]*)>', lambda m: f'<body{m.group(1)} data-section="{section}">', s, count=1, flags=re.IGNORECASE)
    if 'id="site-header"' not in s:
        # insert header host immediately after <body...>
        s = re.sub(r'(<body[^>]*>)', r'\1\n' + HEADER_HOST, s, count=1, flags=re.IGNORECASE)
    if 'shared/chrome.js' not in s:
        # add chrome.js script just before </body>
        s = re.sub(r'</body>', f'  {CHROME_JS}\n</body>', s, count=1, flags=re.IGNORECASE)
    path.write_text(s)
    print(f'injected: {path}  section={section}')

if __name__ == '__main__':
    root = pathlib.Path(__file__).resolve().parent.parent
    targets = [
        ('enrollment/index.html', 'enrollment'),
        ('spending/index.html', 'spending'),
        ('special-ed/index.html', 'special-ed'),
        ('school-day/index.html', 'school-day'),
    ]
    for rel, sec in targets:
        inject(root / rel, sec)
