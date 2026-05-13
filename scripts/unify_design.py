#!/usr/bin/env python3
"""One-shot: replace satellite typefaces with the atlas system (Fraunces + Inter)
and remove the Typekit dependency. Idempotent."""
import re, pathlib

# Target font system
SANS = "'Inter', system-ui, -apple-system, sans-serif"
SERIF = "'Fraunces', Georgia, serif"

# Patterns → replacements
REPLACEMENTS = [
    # Typekit link (kill the line entirely)
    (re.compile(r'^\s*<link rel="stylesheet" href="https://use\.typekit\.net/[^"]+">\s*\n', re.M), ''),
    # Halyard family strings (case variations) → Inter
    (re.compile(r"'halyard-text',\s*'Inter',\s*sans-serif"), SANS),
    (re.compile(r"'Halyard',\s*'Helvetica Neue',\s*Arial,\s*sans-serif"), SANS),
    (re.compile(r"'Halyard,\s*Helvetica Neue,\s*Arial'"), "'Inter, system-ui, sans-serif'"),
    (re.compile(r"Halyard,\s*Helvetica Neue,\s*Arial"), "Inter, system-ui, sans-serif"),
    # Plain Helvetica Neue stacks → Inter
    (re.compile(r"'Helvetica Neue',\s*Arial,\s*sans-serif"), SANS),
    (re.compile(r"\"Helvetica Neue\",\s*Arial,\s*sans-serif"), SANS),
    # Georgia serif stacks → Fraunces
    (re.compile(r"Georgia,\s*'Times New Roman',\s*serif"), SERIF),
    (re.compile(r"Georgia,\s*\"Times New Roman\",\s*serif"), SERIF),
]

def fix(path: pathlib.Path):
    s = path.read_text()
    orig = s
    for pat, rep in REPLACEMENTS:
        s = pat.sub(rep, s)
    if s != orig:
        path.write_text(s)
        print(f'updated: {path.name}')
    else:
        print(f'no change: {path.name}')

if __name__ == '__main__':
    root = pathlib.Path(__file__).resolve().parent.parent
    for rel in ['spending/index.html', 'special-ed/index.html', 'enrollment/index.html', 'school-day/index.html']:
        fix(root / rel)
