"""Refresh the school list, demographics and enrollment trend from DOE's
2021-22 to 2025-26 Demographic Snapshot (school tab).

What it does, in order:
  1. Drops public/charter records whose DBN is not on the snapshot's 2025-26
     school tab. DOE says that tab lists every school open in 2025-26 and
     leaves out closed schools, programs and NYC Early Education Centers, so a
     missing DBN means the school closed, merged, took a new DBN, or is a
     program site (evening high school, District 79 ALC, hospital/home
     instruction). Dropped records are written to data/removed_schools.json.
  2. Adds schools that are on the 2025-26 tab but not on the map, placing each
     at the point NYC Planning's Facilities Database (Socrata ji82-xba5,
     datasource doe_lcgms) gives for a school of the same name in the same
     borough. Schools with no unique name match are listed and left off.
  3. Rewrites every public/charter school's `demo` block and `trend` series
     from the snapshot.
  4. Replaces private schools with the NCES EDGE Private School Locations
     file for 2023-24 (the 2021-22 file before), the NYC rows of which are
     saved in data/sources. Names keep the old file's capitalization where
     the NCES PPIN matches; new schools get title case.
Also drops the old `quality` and `quality_meta` blocks. Their
`chronic_absent` field held the share of students NOT chronically absent (see
data/AUDIT.md); outcome measures now live in data/metrics.json.
Also collapses exact duplicate records (the 2019-20 location file listed 61
schools twice at the same point, which drew two pins).

Inputs:
  data/sources/nyc_doe_demographic_snapshot_2021-22_to_2025-26.xlsx
  data/sources/facdb_doe_lcgms_2026-07.json
Run from the repo root:  python3 scripts/build_refresh.py
"""
import json, re, sys
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / 'data/sources/nyc_doe_demographic_snapshot_2021-22_to_2025-26.xlsx'
FACDB = ROOT / 'data/sources/facdb_doe_lcgms_2026-07.json'
PSS = ROOT / 'data/sources/nces_edge_geocode_privatesch_2023-24_nyc_rows.csv'
PSS_URL = 'https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_2324.zip'
COUNTY_BORO = {'36005': 'Bronx', '36047': 'Brooklyn', '36061': 'Manhattan', '36081': 'Queens', '36085': 'Staten Island'}
SCHOOLS = ROOT / 'data/schools.json'
REMOVED = ROOT / 'data/removed_schools.json'
YEARS = ['2021-22', '2022-23', '2023-24', '2024-25', '2025-26']
LATEST = YEARS[-1]
# The snapshot truncates names at 50 characters. These two read as the
# original school's name ("...Charter School I", "...Charter Hig") but the
# original schools already hold other DBNs on the map (84K782, 84K733), so the
# new DBNs are the second campuses.
NAME_OVERRIDE = {
    '84K966': 'Bedford Stuyvesant New Beginnings Charter School II',
    '84K970': 'Math, Engineering, and Science Academy Charter High School 2',
}
# On the map despite being absent from the snapshot's school tab.
# 15K418 The Children's School shares 512 Carroll Street with District 75's
# 75K372; DOE reports the building's enrollment under 75K372, but 15K418 is an
# open school with its own 2026 NYC School Survey results.
KEEP_ANYWAY = {'15K418'}
BORO = {'M': 'Manhattan', 'X': 'Bronx', 'K': 'Brooklyn', 'Q': 'Queens', 'R': 'Staten Island'}
GRADE_COLS = ['Grade 3K', 'Grade PK (Half Day & Full Day)', 'Grade K'] + [f'Grade {i}' for i in range(1, 13)]
GRADE_LABEL = ['3K', 'PK', 'K'] + [str(i) for i in range(1, 13)]


def num(v):
    return None if v is None or v == '' else v


def capped(v):
    """Poverty and ENI are masked as 'Above 95%' / 'Below 5%'. Return (value 0-100, flag)."""
    if v is None:
        return None, None
    if isinstance(v, str):
        if v.startswith('Above'):
            return 95.0, 'above'
        if v.startswith('Below'):
            return 5.0, 'below'
        raise ValueError(f'unexpected masked value {v!r}')
    return round(float(v) * 100, 1), None


def grade_span(row, idx):
    present = [GRADE_LABEL[i] for i, c in enumerate(GRADE_COLS) if (row[idx[c]] or 0) > 0]
    if not present:
        return None
    return present[0] if len(present) == 1 else f'{present[0]}-{present[-1]}'


def full_name(snap_name, fac_name):
    """The snapshot cuts names at 50 characters; FacDB has the whole name in
    capitals. Keep the snapshot's casing when it isn't cut off."""
    snap_name = snap_name.replace('\ufffd', '–').strip()
    if len(snap_name) < 50:
        return snap_name
    t = fac_name.title()
    t = re.sub(r"\b(Ii|Iii|Iv)\b", lambda m: m.group(0).upper(), t)
    t = re.sub(r"(?<=\s)(Of|And|The|For|In|At)\b", lambda m: m.group(0).lower(), t)
    return re.sub(r"'S\b", "'s", t)


def smart_title(t):
    t = t.title()
    t = re.sub(r"\b(Ii|Iii|Iv)\b", lambda m: m.group(0).upper(), t)
    t = re.sub(r"(?<=\s)(Of|And|The|For|In|At)\b", lambda m: m.group(0).lower(), t)
    return re.sub(r"'S\b", "'s", t)


def norm(name):
    s = (name or '').upper().replace('�', ' ')
    s = re.sub(r'[–—\-–—]', ' ', s)
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def main():
    wb = openpyxl.load_workbook(SNAP, read_only=True)
    rows = list(wb['School'].iter_rows(values_only=True))
    hdr = rows[0]
    idx = {h: i for i, h in enumerate(hdr)}
    by = {}
    for r in rows[1:]:
        if r[0] and r[2] in YEARS:
            by.setdefault(r[0].strip().upper(), {})[r[2]] = r
    latest = {d: y[LATEST] for d, y in by.items() if LATEST in y}
    if len(latest) < 1800:
        raise SystemExit(f'only {len(latest)} schools on the {LATEST} tab; expected ~1,900')

    schools = json.load(open(SCHOOLS))
    seen, deduped = set(), []
    for s in schools:
        if s['sector'] != 'private' and s['dbn'] in seen:
            continue
        seen.add(s['dbn'])
        deduped.append(s)
    print(f'collapsed {len(schools) - len(deduped)} duplicate records')
    schools = deduped
    keep, removed = [], []
    for s in schools:
        if s['sector'] == 'private' or s['dbn'] in latest or s['dbn'] in KEEP_ANYWAY:
            keep.append(s)
        else:
            removed.append({'dbn': s['dbn'], 'name': s['name'], 'sector': s['sector'],
                            'last_trend_year': (s.get('trend') or [[None]])[-1][0] if s.get('trend') else None,
                            'reason': f'Not on the DOE {LATEST} Demographic Snapshot school tab'})
    have = {s['dbn'] for s in keep}

    fac = json.load(open(FACDB))
    fac_by_boro = {}
    for f in fac:
        if not f.get('boro') or float(f.get('latitude') or 0) == 0:
            continue  # two records sit outside the city with no coordinates
        fac_by_boro.setdefault(f['boro'].title(), []).append(f)

    zoned = {f['properties'].get('dbn') for f in json.load(open(ROOT / 'data/zones.geojson'))['features']}
    added, unplaced = [], []
    for dbn in sorted(set(latest) - have):
        r = latest[dbn]
        boro = BORO[dbn[2]]
        n = norm(NAME_OVERRIDE.get(dbn, r[1]))
        cands = [f for f in fac_by_boro.get(boro, []) if norm(f['facname']).startswith(n) or n.startswith(norm(f['facname']))]
        if len(cands) > 1 and not dbn.startswith('84'):
            cands = [f for f in cands if str(f.get('schooldist', '')).zfill(2) == dbn[:2]] or cands
        if len(cands) > 1:
            exact = [f for f in cands if norm(f['facname']) == n]
            cands = exact or cands
        if len(cands) != 1:
            unplaced.append({'dbn': dbn, 'name': r[1], 'candidates': [f['facname'] for f in cands]})
            continue
        f = cands[0]
        added.append({
            'dbn': dbn, 'name': NAME_OVERRIDE.get(dbn) or full_name(r[1], f['facname']),
            'sector': 'charter' if dbn.startswith('84') else 'public',
            'lat': float(f['latitude']), 'lon': float(f['longitude']),
            'address': f.get('address') or ' '.join(filter(None, [f.get('addressnum'), f.get('streetname')])) or None, 'zip': f.get('zipcode'), 'boro': boro,
            'district': dbn[:2], 'neighborhood': None, 'grades': None, 'website': None,
            'overview': None, 'admission': None, 'demo': None, 'trend': [], 'programs': [],
            'admission_programs': [], 'has_zone': dbn in zoned,
            'location_source': 'NYC Planning Facilities Database (ji82-xba5), doe_lcgms, matched by name + borough',
        })
    keep.extend(added)

    for s in keep:
        s.pop('quality', None)
        s.pop('quality_meta', None)

    # Demographics + trend for every public/charter school
    for s in keep:
        if s['sector'] == 'private':
            continue
        if s['dbn'] not in latest:
            continue
        yrs = by[s['dbn']]
        r = yrs[LATEST]
        pov, pov_flag = capped(r[idx['% Poverty']])
        eni, eni_flag = capped(r[idx['Economic Need Index']])
        s['demo'] = {
            'year': LATEST,
            'enrollment': r[idx['Total Enrollment']],
            'pct_asian': num(r[idx['% Asian and Pacific Islander']]),
            'pct_black': num(r[idx['% Black']]),
            'pct_hispanic': num(r[idx['% Hispanic']]),
            'pct_white': num(r[idx['% White']]),
            'pct_multi': num(r[idx['% Multi-Racial']]),
            'pct_native': num(r[idx['% Native American']]),
            'pct_female': num(r[idx['% Female']]),
            'pct_male': num(r[idx['% Male']]),
            'pct_swd': num(r[idx['% Students with Disabilities']]),
            'pct_ell': num(r[idx['% English Language Learners']]),
            'poverty': pov, 'poverty_mask': pov_flag,
            'eni': eni, 'eni_mask': eni_flag,
            'year_enrollment': LATEST,
            'enrollment_latest': r[idx['Total Enrollment']],
        }
        for k in list(s['demo']):
            if isinstance(s['demo'][k], float):
                s['demo'][k] = round(s['demo'][k], 4)
        s['trend'] = [[y, yrs[y][idx['Total Enrollment']]] for y in YEARS if y in yrs]
        span = grade_span(r, idx)
        if span:
            s['grades'] = span

    # Private schools: NCES 2023-24
    import csv
    old_priv = {s['dbn']: s for s in keep if s['sector'] == 'private'}
    pss = list(csv.DictReader(open(PSS)))
    if len(pss) < 450:
        raise SystemExit(f'only {len(pss)} NYC private schools in {PSS}')
    new_priv = []
    for r in pss:
        dbn = f"PRIV-{r['PPIN']}"
        o = old_priv.get(dbn)
        name = o['name'] if o else full_name(r['NAME'], r['NAME']) if len(r['NAME']) >= 50 else smart_title(r['NAME'])
        new_priv.append({
            'dbn': dbn, 'name': name, 'sector': 'private', 'lat': float(r['LAT']), 'lon': float(r['LON']),
            'address': o['address'] if o and o['address'] else smart_title(r['STREET']), 'zip': r['ZIP'],
            'boro': COUNTY_BORO[r['CNTY']], 'district': None, 'neighborhood': None, 'grades': None,
            'website': o.get('website') if o else None, 'overview': None, 'admission': None, 'demo': None,
            'trend': [], 'programs': [], 'admission_programs': [], 'has_zone': False,
            'location_source': f'NCES EDGE Private School Locations 2023-24 ({PSS_URL})',
        })
    priv_added = len({p['dbn'] for p in new_priv} - set(old_priv))
    priv_dropped = len(set(old_priv) - {p['dbn'] for p in new_priv})
    keep = [s for s in keep if s['sector'] != 'private'] + new_priv
    print(f'private schools: {len(new_priv)} (2023-24), {priv_added} new, {priv_dropped} no longer listed')

    json.dump(keep, open(SCHOOLS, 'w'), separators=(',', ':'))
    json.dump({'source': f'DOE Demographic Snapshot {LATEST} school tab', 'removed': removed,
               'added': [{'dbn': a['dbn'], 'name': a['name']} for a in added],
               'unplaced': unplaced}, open(REMOVED, 'w'), indent=1)
    print(f'kept {len(keep) - len(added)}, removed {len(removed)}, added {len(added)}, unplaced {len(unplaced)}')
    for u in unplaced:
        print('  unplaced', u)


if __name__ == '__main__':
    main()
