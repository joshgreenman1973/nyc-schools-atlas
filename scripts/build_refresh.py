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
  5. Brings public and charter schools up to DOE's current school list
     (LCGMS, downloaded Oct. 7, 2026): current names; and where DOE's
     current address differs from the map's and NYC Planning's GeoSearch
     places that exact address more than 75 m from the map's dot, the dot
     and address move there. Lookups are cached in data/sources so the
     build is repeatable. P.S. Q256 (75Q256), a District 75 school in
     Syosset, is placed with the Census Bureau geocoder.
  6. has_zone counts shared zones, whose DBN field lists several schools.
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
LCGMS = ROOT / 'data/sources/nyc_doe_lcgms_school_data_2026-10-07.xls'
GEOCACHE = ROOT / 'data/sources/geosearch_cache_lcgms_2026-10.json'
# Outside the city, so NYC GeoSearch can't place it; Census Bureau geocoder,
# 525 CONVENT RD, SYOSSET, NY, 11791.
OUTSIDE_NYC = {'75Q256': (40.821547225671, -73.485224763559, '525 Convent Road, Syosset, NY')}
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


def street_key(a):
    a = (a or '').upper()
    for k, v in ((' STREET', ' ST'), (' AVENUE', ' AVE'), (' BOULEVARD', ' BLVD'), (' PLACE', ' PL'), (' ROAD', ' RD'),
                 (' PARKWAY', ' PKWY'), ('EAST ', 'E '), ('WEST ', 'W '), ('NORTH ', 'N '), ('SOUTH ', 'S '), ('SAINT ', 'ST ')):
        a = a.replace(k, v)
    a = re.sub(r'(\d+)(ST|ND|RD|TH)\b', r'\1', a)
    a = re.sub(r'(\d+)-\d+', r'\1', a)
    return re.sub(r'[^A-Z0-9]', '', a)


def meters(a, b, c, d):
    import math
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(x))


def geosearch(addr, zipc, boro, cache):
    """NYC Planning GeoSearch. Returns a point only when the matched address is
    the address asked for (same house number and street)."""
    import urllib.request, urllib.parse, time
    q = f'{addr}, {boro} {zipc}'
    if q not in cache:
        url = 'https://geosearch.planninglabs.nyc/v2/search?size=1&text=' + urllib.parse.quote(q)
        for i in range(3):
            try:
                d = json.load(urllib.request.urlopen(url, timeout=20))
                break
            except Exception:
                time.sleep(2)
        else:
            raise SystemExit(f'GeoSearch failed for {q}')
        f = (d.get('features') or [None])[0]
        cache[q] = None if not f else {'lat': f['geometry']['coordinates'][1], 'lon': f['geometry']['coordinates'][0],
                                       'label': f['properties'].get('label')}
        time.sleep(0.15)
    g = cache[q]
    if not g or street_key(g['label'].split(',')[0]) != street_key(addr):
        return None
    return g


# Long moves confirmed by hand against a second source.
CONFIRMED_MOVES = {'84K766': "Insideschools' page lists the same address, 272 Macon St."}


def confirmed(name, g, fac):
    """A move of more than 2 km needs a second source: NYC Planning's
    Facilities Database (DOE records, July 2026) must have a school of the
    same name within 250 m of the new point, or the move is listed in
    CONFIRMED_MOVES. Otherwise the dot stays where it was."""
    n = norm(name)
    for f in fac:
        fn = norm(f['facname'])
        if (fn == n or fn.startswith(n) or n.startswith(fn)) and meters(g['lat'], g['lon'], float(f['latitude']), float(f['longitude'])) < 250:
            return True
    return False


def place_from_lcgms(unplaced, latest, keep, zoned):
    """Schools the Facilities Database couldn't place: use DOE's current
    address if GeoSearch finds that exact address."""
    import pandas as pd
    t = pd.read_html(LCGMS)[0]
    t.columns = t.iloc[0]
    t = t[1:]
    L = {r['ATS System Code'].strip(): r for _, r in t.iterrows() if isinstance(r['ATS System Code'], str)}
    cache = json.load(open(GEOCACHE)) if GEOCACHE.exists() else {}
    done = []
    for u in unplaced:
        d, l = u['dbn'], L.get(u['dbn'])
        if l is None:
            continue
        addr, zipc = str(l['Primary Address']).strip(), str(l['Zip']).strip()[:5]
        g = geosearch(addr, zipc, BORO[d[2]], cache)
        if g is None:
            continue
        keep.append({'dbn': d, 'name': l['Location Name'], 'sector': 'charter' if d.startswith('84') else 'public',
                     'lat': g['lat'], 'lon': g['lon'], 'address': addr.upper(), 'zip': zipc, 'boro': BORO[d[2]],
                     'district': d[:2].lstrip('0'), 'neighborhood': None, 'grades': None, 'website': None, 'overview': None,
                     'admission': None, 'demo': None, 'trend': [], 'programs': [], 'admission_programs': [],
                     'has_zone': d in zoned,
                     'location_source': "DOE LCGMS address (Oct. 7, 2026), placed by NYC Planning GeoSearch"})
        done.append(d)
    json.dump(cache, open(GEOCACHE, 'w'), indent=0, sort_keys=True)
    return done


def current_names_and_places(keep, latest, idx):
    import pandas as pd
    t = pd.read_html(LCGMS)[0]
    t.columns = t.iloc[0]
    t = t[1:]
    L = {r['ATS System Code'].strip(): r for _, r in t.iterrows() if isinstance(r['ATS System Code'], str)}
    cache = json.load(open(GEOCACHE)) if GEOCACHE.exists() else {}
    fac = [f for f in json.load(open(FACDB)) if float(f.get('latitude') or 0)]
    moved, renamed, held = [], [], []
    for s in keep:
        if s['sector'] == 'private':
            continue
        d = s['dbn']
        if d in OUTSIDE_NYC:
            s['lat'], s['lon'], s['address'] = OUTSIDE_NYC[d]
            s['boro'] = 'Outside NYC'
        l = L.get(d)
        if l is None:
            if d in latest and norm(latest[d][1]) != norm(s['name']) and len(latest[d][1]) < 50:
                renamed.append({'dbn': d, 'from': s['name'], 'to': latest[d][1].strip(), 'source': 'snapshot 2025-26'})
                s['name'] = latest[d][1].strip()
            continue
        gd = str(l['Geographical District Code']).strip()
        if gd.isdigit() and int(gd) > 0:
            s['district'] = str(int(gd))
        if norm(l['Location Name']) != norm(s['name']):
            renamed.append({'dbn': d, 'from': s['name'], 'to': l['Location Name'], 'source': 'LCGMS'})
            s['name'] = l['Location Name']
        if d in OUTSIDE_NYC:
            continue
        addr, zipc = str(l['Primary Address']).strip(), str(l['Zip']).strip()[:5]
        if street_key(addr) == street_key(s.get('address')) and s.get('address'):
            continue
        g = geosearch(addr, zipc, BORO[d[2]], cache)
        if g is None:
            if not s.get('address'):
                s['address'] = addr.upper()
            continue
        dist = meters(s['lat'], s['lon'], g['lat'], g['lon'])
        if dist > 2000 and d not in CONFIRMED_MOVES and not confirmed(s['name'], g, fac):
            held.append({'dbn': d, 'name': s['name'], 'map_address': s.get('address'), 'doe_address': addr, 'meters': round(dist)})
            continue
        if dist > 75:
            moved.append({'dbn': d, 'name': s['name'], 'from': s.get('address'), 'to': addr, 'meters': round(dist)})
            s['lat'], s['lon'] = g['lat'], g['lon']
            s['location_source'] = "DOE LCGMS address (Oct. 7, 2026), placed by NYC Planning GeoSearch"
        s['address'], s['zip'] = addr.upper(), zipc
    json.dump(cache, open(GEOCACHE, 'w'), indent=0, sort_keys=True)
    print(f'{len(renamed)} renamed to current DOE names, {len(moved)} moved to current DOE addresses, '
          f'{len(held)} long moves held back for lack of a second source')
    for h in held:
        print('  held', h)
    return moved + [dict(h, held=True) for h in held], renamed


def smart_title(t):
    t = t.title()
    t = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), t)
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
    seen, deduped, dupes = set(), [], []
    for s in schools:
        if s['sector'] != 'private' and s['dbn'] in seen:
            dupes.append({'dbn': s['dbn'], 'name': s['name']})
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

    # A shared zone lists every school in it, comma-separated ("09X053,09X088").
    zoned = {d.strip() for f in json.load(open(ROOT / 'data/zones.geojson'))['features']
             for d in (f['properties'].get('dbn') or '').split(',') if d.strip()}
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
    placed_late = place_from_lcgms(unplaced, latest, keep, zoned)
    added += [{'dbn': d, 'name': next(k['name'] for k in keep if k['dbn'] == d)} for d in placed_late]
    unplaced = [u for u in unplaced if u['dbn'] not in placed_late]

    for s in keep:
        s.pop('quality', None)
        s.pop('quality_meta', None)
        if s['sector'] != 'private':
            s['has_zone'] = s['dbn'] in zoned

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
        # Keep the old file's capitalization only when it is the same name.
        name = o['name'] if o and norm(o['name']) == norm(r['NAME']) else smart_title(r['NAME'])
        new_priv.append({
            'dbn': dbn, 'name': name, 'sector': 'private', 'lat': float(r['LAT']), 'lon': float(r['LON']),
            'address': smart_title(r['STREET']), 'zip': r['ZIP'],
            'boro': COUNTY_BORO[r['CNTY']], 'district': None, 'neighborhood': None, 'grades': None,
            'website': o.get('website') if o else None, 'overview': None, 'admission': None, 'demo': None,
            'trend': [], 'programs': [], 'admission_programs': [], 'has_zone': False,
            'location_source': f'NCES EDGE Private School Locations 2023-24 ({PSS_URL})',
        })
    priv_added = len({p['dbn'] for p in new_priv} - set(old_priv))
    priv_dropped = len(set(old_priv) - {p['dbn'] for p in new_priv})
    keep = [s for s in keep if s['sector'] != 'private'] + new_priv
    print(f'private schools: {len(new_priv)} (2023-24), {priv_added} new, {priv_dropped} no longer listed')

    moved, renamed = current_names_and_places(keep, latest, idx)

    json.dump(keep, open(SCHOOLS, 'w'), separators=(',', ':'))
    json.dump({'source': f'DOE Demographic Snapshot {LATEST} school tab', 'removed': removed,
               'added': [{'dbn': a['dbn'], 'name': a['name']} for a in added],
               'unplaced': unplaced, 'duplicates_collapsed': dupes,
               'moved_to_current_doe_address': moved, 'renamed_to_current_doe_name': renamed},
              open(REMOVED, 'w'), indent=1)
    print(f'kept {len(keep) - len(added)}, removed {len(removed)}, added {len(added)}, unplaced {len(unplaced)}')
    for u in unplaced:
        print('  unplaced', u)


if __name__ == '__main__':
    main()
