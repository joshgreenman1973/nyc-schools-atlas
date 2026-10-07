"""Which schools have an Insideschools review, with a link to it.

Insideschools (insideschools.org, a project of Advocates for Children of New
York) publishes a page for most public and charter schools at
https://insideschools.org/school/<DBN>. Some pages carry a staff-written
review, which opens with "What's Special" (usually followed by "The
Downside") or, on older reviews, ends with a dated staff byline such as
"(Lydie Raschka, web reports and interviews January 2018)". Other pages carry
only boilerplate ("This is a zoned, neighborhood school..."), a generic
summary built from DOE data, or a message the school wrote itself. Only the
first kind counts as a review here.

Matching. A page is fetched by DBN, but DOE reuses DBNs, so a review is
accepted if the page's school name matches the map's name for that DBN.
Otherwise the page's name must match DOE's current name for the DBN (DOE's
LCGMS school list, i.e. the school was renamed), or match the name the DBN
had on the map before it was renamed (the review then says so), or have
been checked by hand
(NAME_CHECKED), AND the page's street address must match DOE's current
address, AND no review date may fall before the date DOE gives for the
school's opening. Pairs that fail are listed in the notes.

Nothing from the review itself is stored: only whether it exists, its URL,
and the dates in its byline. Insideschools' terms bar copying its content.

Pages are read from INSIDESCHOOLS_DIR (default: the session scratchpad),
filled by fetching each DBN's page at a polite rate; they are not committed.
Run from the repo root:  python3 scripts/metrics/build_insideschools.py
"""
import html, json, os, re, sys, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = Path(os.environ.get('INSIDESCHOOLS_DIR', '/private/tmp/claude-501/-Users-joshgreenman-Experiments/92d82c73-da9a-4cd9-bf8c-aaf5be19c7ce/scratchpad/insideschools/pages'))
OUT = ROOT / 'data/metrics/insideschools.json'
MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December'

# DBNs whose page name differs from DOE's but which were checked by hand and
# are the same school (address, grades and history agree). Filled after review.
NAME_CHECKED = {
    '08X014': 'Insideschools writes "P.S. 14", DOE "P.S. X014"; same name and address',
    '13K915': 'I.S./M.S. 915 is DOE\'s "Bridges: A School for Exploration and Equity"; same address',
    '02M131': 'M.S. 131 is Sun Yat Sen Middle School; same address',
    '02M289': 'I.S. 289 is Hudson River Middle School; same address',
    '02M126': 'P.S. 126 Jacob August Riis is also called Manhattan Academy of Technology; same address',
}
# DBNs whose page is a different, older school that used the same DBN.
NAME_REJECTED = {}


def text(h):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h))).strip()


def norm(name):
    s = html.unescape(name or '').lower().replace('&', ' and ')
    s = re.sub(r'\b(p|i|m|j\.?h)\.?\s?s\.?(?=\s|\d)', lambda m: m.group(0).replace('.', '').replace(' ', ''), s)
    s = re.sub(r"[^a-z0-9 ]", ' ', s)
    s = re.sub(r'\b0+(\d)', r'\1', s)          # 015 -> 15
    s = re.sub(r'\b(the|school|of|for|and|at|a|an)\b', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def numbers(name):
    return {str(int(n)) for n in re.findall(r'\d+', norm(name))}


def names_match(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    ta, tb = set(na.split()), set(nb.split())
    num_a, num_b = numbers(a), numbers(b)
    if num_a and num_b and not (num_a & num_b):
        return False
    if na in nb or nb in na:
        return True
    inter = len(ta & tb)
    return inter / min(len(ta), len(tb)) >= 0.6


def parse(path):
    t = path.read_text(encoding='utf-8', errors='ignore')
    title = re.search(r'<title>(.*?)</title>', t, re.S)
    title = html.unescape(title.group(1)).strip() if title else ''
    name = re.sub(r'\s+-\s+(District|Charter|Citywide|InsideSchools).*$', '', title).strip()
    i = t.find('Our Insights</h2>')
    block = ''
    if i >= 0:
        j = min([k for k in [t.find("<div class='school-anchor'", i + 20), t.find('<h2', i + 20)] if k > 0] or [i + 20000])
        block = t[i + len('Our Insights</h2>'):j]
    body = text(block)
    bylines = re.findall(r'\(([^()]{2,120}?(?:%s)\s+\d{4}[^()]*)\)' % MONTHS, body)
    # A staff review opens with "What's Special" or carries a dated staff byline.
    # Text a school submits itself ("Message from the ... Faculty and Staff")
    # and Insideschools' generic data blurbs have neither.
    school_written = bool(re.search(r'Message from the .{0,80}(Faculty|Staff)', body[:200]))
    is_review = not school_written and (bool(re.search(r'What.s Special', block)) or (bool(bylines) and len(body) > 400))
    dates = re.findall(r'((?:%s)\s+\d{4})' % MONTHS, ' '.join(bylines))
    years = sorted({int(y) for y in re.findall(r'\b(20\d\d|19\d\d)\b', ' '.join(bylines))} |
                   {int(y) for y in re.findall(r'\b(20\d\d) REVIEW\b', body)})
    addr = re.search(r"itemprop=.streetAddress.[^>]*>([^<]+)", t)
    return {'name': name, 'is_review': is_review, 'dates': dates, 'years': years, 'len': len(body),
            'address': html.unescape(addr.group(1)).strip() if addr else ''}


def street(a):
    a = (a or '').upper()
    for k, v in ((' STREET', ' ST'), (' AVENUE', ' AVE'), (' BOULEVARD', ' BLVD'), (' PLACE', ' PL'), (' ROAD', ' RD'),
                 ('EAST ', 'E '), ('WEST ', 'W '), ('NORTH ', 'N '), ('SOUTH ', 'S ')):
        a = a.replace(k, v)
    a = re.sub(r'(\d+)(ST|ND|RD|TH)\b', r'\1', a)
    return re.sub(r'[^A-Z0-9]', '', a)


def lcgms():
    import pandas as pd
    t = pd.read_html(ROOT / 'data/sources/nyc_doe_lcgms_school_data_2026-10-07.xls')[0]
    t.columns = t.iloc[0]
    t = t[1:]
    out = {}
    for _, r in t.iterrows():
        if isinstance(r['ATS System Code'], str):
            yr = re.search(r'(\d{4})$', str(r['Open Date']))
            out[r['ATS System Code'].strip()] = {'name': r['Location Name'], 'address': r['Primary Address'],
                                                 'open_year': int(yr.group(1)) if yr else None}
    return out


def former_names():
    """Names each DBN had on the map before scripts/build_refresh.py brought it
    up to DOE's current list (recorded in data/removed_schools.json)."""
    r = json.load(open(ROOT / 'data/removed_schools.json'))
    out = {}
    for x in r.get('renamed_to_current_doe_name', []):
        out.setdefault(x['dbn'], []).append(x['from'])
    return out


def main():
    schools = [s for s in json.load(open(ROOT / 'data/schools.json')) if s['sector'] != 'private']
    L = lcgms()
    F = former_names()
    out, missing, mismatched = {}, [], []
    for s in schools:
        p = PAGES / f"{s['dbn']}.html"
        if not p.exists():
            missing.append(s['dbn'])
            continue
        r = parse(p)
        if not r['is_review']:
            continue
        cur = L.get(s['dbn'], {})
        # Same name as on the map: same school, even if it has since moved.
        # Renamed or hand-checked pairs must also share DOE's current address,
        # and the review can't predate the DBN's opening.
        direct = names_match(s['name'], r['name'])
        # Reviewed under a name this same DBN carried on the map before DOE renamed it.
        former = next((n for n in F.get(s['dbn'], []) if names_match(n, r['name'])), None)
        direct = direct or bool(former)
        name_ok = direct or names_match(cur.get('name'), r['name']) or s['dbn'] in NAME_CHECKED
        addr_ok = direct or not cur.get('address') or street(cur['address']) == street(r['address'])
        date_ok = direct or not (cur.get('open_year') and r['years'] and min(r['years']) < cur['open_year'])
        if s['dbn'] in NAME_REJECTED or not (name_ok and addr_ok and date_ok):
            mismatched.append({'dbn': s['dbn'], 'doe_name': s['name'], 'insideschools_name': r['name'], 'years': r['years'],
                               'why': ', '.join(w for w, ok in (('name', name_ok), ('address', addr_ok), ('review predates opening', date_ok)) if not ok)})
            continue
        first = r['dates'][0] if r['dates'] else (str(r['years'][0]) if r['years'] else None)
        last = r['years'][-1] if r['years'] else None
        out[s['dbn']] = {
            'review': True,
            'review_url': f"https://insideschools.org/school/{s['dbn']}#SchoolInsights",
            'review_date': first,
            'review_latest_year': last,
            'insideschools_name': r['name'],
            **({'former_name': former} if former and not names_match(s['name'], r['name']) else {}),
        }
    fetched = len(schools) - len(missing)
    if fetched < 1800:
        raise SystemExit(f'only {fetched} pages on disk in {PAGES}; fetch first')
    if len(out) < 300:
        raise SystemExit(f'only {len(out)} reviews found; the page layout may have changed')
    doc = {
        'key': 'insideschools', 'title': 'Insideschools reviews',
        'source': 'Insideschools (Advocates for Children of New York), school pages',
        'source_url': 'https://insideschools.org/', 'file_url': 'https://insideschools.org/school/<DBN>',
        'vintage': f'pages fetched {datetime.date.today().isoformat()}', 'fetched': datetime.date.today().isoformat(),
        'fields': {
            'review': {'label': 'Has an Insideschools review', 'definition': "The school's Insideschools page has a staff-written review (it opens with \"What's Special\" or carries a dated staff byline).", 'source_field': 'page section "Our Insights"', 'unit': 'text', 'direction': 'neutral'},
            'review_url': {'label': 'Review link', 'definition': 'Link to the review on the school page.', 'source_field': 'URL', 'unit': 'text', 'direction': 'neutral'},
            'review_date': {'label': 'Review date', 'definition': "Month and year from the review's byline, the first date if it was later updated.", 'source_field': 'byline', 'unit': 'text', 'direction': 'neutral'},
            'review_latest_year': {'label': 'Latest update year', 'definition': 'Latest year named in the byline (original visit or later update).', 'source_field': 'byline', 'unit': 'number', 'direction': 'neutral'},
        },
        'notes': [
            f'{fetched} of {len(schools)} public and charter school pages fetched; {len(missing)} returned no page.',
            f'{len(out)} schools have a staff-written review whose page name matches the DOE name for the DBN.',
            f'{len(mismatched)} pages had a review under a name that does not match the DOE school now using that DBN; those are not linked: ' +
            '; '.join(f"{m['dbn']} (DOE: {m['doe_name']}; Insideschools: {m['insideschools_name']})" for m in mismatched),
            'Pages with only boilerplate ("This is a zoned, neighborhood school..."), a generic data summary, or a message written by the school are not counted as reviews.',
            "Review text is not stored or reproduced; Insideschools' terms bar copying its content.",
        ],
        'schools': out,
    }
    json.dump(doc, open(OUT, 'w'), indent=1, ensure_ascii=False)
    print(f'{fetched} pages, {len(out)} reviews linked, {len(mismatched)} name mismatches, {len(missing)} missing')
    for m in mismatched:
        print('  MISMATCH', m)


if __name__ == '__main__':
    main()
