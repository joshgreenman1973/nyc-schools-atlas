"""Merge the per-source files in data/metrics/*.json into data/metrics.json,
the one file the map reads for the school sheet, the lineup and "color dots by".

For every measure it records the source, vintage and definition; for every
school it stores the value and where it sits among the other schools of the
same level (elementary, middle, high, transfer high, District 75, early
childhood): a = % of the other schools with a strictly lower value, h = % with
a strictly higher value, both floored to whole percents. The map's colors use
the midpoint (a + 100 - h) / 2. If a level has fewer than MIN_PEERS schools
with the measure, the school is ranked against all schools that have it.

Measures derived here (not published as such by the source):
  impact / performance  DOE's EMS, HS or HST score, whichever matches the
                        school's level (the scores are standardized within
                        report type, so they are never mixed in one ranking).
  ela / math            % at Levels 3-4 from the newest state test file.
  suspensions_per_100   (principal's + superintendent's suspensions, 2024-25)
                        / 2024-25 enrollment from the DOE Demographic Snapshot
                        x 100. Only when DOE shows both counts; DOE redacts
                        counts of 1 to 5.
  enroll_change         (2025-26 enrollment - 2021-22 enrollment) / 2021-22,
                        DOE Demographic Snapshot; only when 2021-22 >= 20.
  eni, pct_swd, pct_ell DOE Demographic Snapshot 2025-26.

Run from the repo root after the per-source builds:  python3 scripts/build_metrics.py
"""
import json, math, re, sys
from html import unescape as html_unescape
from pathlib import Path
from bisect import bisect_left, bisect_right

ROOT = Path(__file__).resolve().parent.parent
MDIR = ROOT / 'data/metrics'
OUT = ROOT / 'data/metrics.json'
MIN_PEERS = 25
BINS = 24
STRICT = '--strict' in sys.argv

GROUPS = [
    {'id': 'quick', 'label': "The guide's quick checks", 'short': 'Quick checks',
     'note': 'The three numbers Chalkbeat and The City Reporter suggest looking at first.'},
    {'id': 'learning', 'label': 'Learning', 'short': 'Learning',
     'note': "Test proficiency tracks a school's demographics closely. DOE's impact score compares students with similar students elsewhere, which is the fairer read on what the school adds."},
    {'id': 'climate', 'label': 'Climate and safety', 'short': 'Climate'},
    {'id': 'staff', 'label': 'Teachers and resources', 'short': 'Resources',
     'note': "More money per student doesn't always mean more resources: small schools that are losing students can look flush under the city's hold-harmless budget rules."},
    {'id': 'students', 'label': 'Students and building', 'short': 'Students'},
    {'id': 'sped', 'label': 'Special education', 'short': 'Special ed',
     'note': 'DOE counts a student as served if the services started at some point in the year, which can hide delays.'},
]


def load(key):
    p = MDIR / f'{key}.json'
    if not p.exists():
        if STRICT:
            raise SystemExit(f'missing {p}')
        print(f'  (skipping {key}: no file yet)')
        return None
    return json.load(open(p))


SRC = {k: load(k) for k in ['survey', 'attendance', 'graduation', 'sqr', 'tests', 'class_size',
                            'counselors', 'spending', 'pta', 'capacity', 'suspensions',
                            'accessibility', 'charters', 'insideschools']}
schools = [s for s in json.load(open(ROOT / 'data/schools.json')) if s['sector'] != 'private']
by_dbn = {s['dbn']: s for s in schools}


def fld(key, name):
    d = SRC.get(key)
    return d['fields'].get(name) if d else None


def get(key, dbn, name):
    d = SRC.get(key)
    if not d:
        return None
    r = d['schools'].get(dbn)
    return None if r is None else r.get(name)


def src_name(key):
    return SRC[key]['source'] if SRC.get(key) else ''


# ---------- DOE's current school list (LCGMS, Oct. 7, 2026) ----------
def _lcgms():
    import pandas as pd
    t = pd.read_html(ROOT / 'data/sources/nyc_doe_lcgms_school_data_2026-10-07.xls')[0]
    t.columns = t.iloc[0]
    t = t[1:]
    return {r['ATS System Code'].strip(): {'building': str(r['Building Code']).strip().upper()}
            for _, r in t.iterrows() if isinstance(r['ATS System Code'], str)}


LCG = _lcgms()


def _access_list():
    """DOE's Building Accessibility Profile list, sheet 'Current Accessible
    School List': (DBN, building) pairs and each listed building's rating."""
    import openpyxl
    wb = openpyxl.load_workbook(ROOT / 'data/sources/nyc_doe_building_accessibility_profile_list_2026-08-14.xlsm', read_only=True, data_only=True)
    rows = list(wb['Current Accessible School List'].iter_rows(values_only=True))
    h = rows[2]
    ix = {c: i for i, c in enumerate(h) if c}
    pair, bldg, by_dbn = {}, {}, {}
    for r in rows[3:]:
        dbn = (r[ix['School DBN']] or '').strip().upper()
        b = (r[ix['Building Code']] or '').strip().upper()
        desc = r[ix['Accessibility Description']]
        if not b or not desc:
            continue
        pair[(dbn, b)] = desc
        bldg.setdefault(b, desc)
        by_dbn.setdefault(dbn, set()).add(b)
    return pair, bldg, by_dbn


ACC_PAIR, ACC_BLDG, ACC_DBN = _access_list()


def _nysed_pages():
    import tarfile
    out = {}
    with tarfile.open(ROOT / 'data/sources/nysed_charter_school_pages_nyc_2026-10-07.tar.gz') as t:
        for mem in t.getmembers():
            if mem.isfile() and mem.name.endswith('.html'):
                out[Path(mem.name).stem] = t.extractfile(mem).read().decode('utf-8', 'ignore')
    return out


NYSED_PAGES = _nysed_pages()
# The charter directory missed this school's NYSED page.
NYSED_URL_ADD = {'84X638': 'https://www.nysed.gov/charter-schools/success-academy-charter-school-bronx-5-upper'}
# Authorizer links that don't reach the school's own page, checked Oct. 7,
# 2026: a logo image (84K737, 84M320), SUNY's generic school finder or list
# (84M704, 84M080, 84X345, 84X491, 84X637, 84X638), a 404 (84K970) or a
# malformed address on NYSED's page (84X597).
DEAD_AUTH = {'84K737', '84M320', '84M704', '84M080', '84X345', '84X491', '84X637', '84X638', '84K970', '84X597'}


# ---------- levels ----------
LEVEL_NAME_MD = {'ES': 'elementary, including K-8', 'MS': 'middle', 'HS': 'high, including 6-12', 'HST': 'transfer high',
                 'D75': 'District 75', 'EC': 'early childhood'}
GRADE_NUM = {'3K': -2, 'PK': -1, 'K': 0}


def gnum(t):
    t = t.strip().upper()
    return GRADE_NUM.get(t, int(t) if t.isdigit() else None)


def level_of(s):
    if s['dbn'][:2] == '75':
        return 'D75'
    rt = get('sqr', s['dbn'], 'report_type') or ''
    if 'HST' in rt:
        return 'HST'
    g = (s.get('grades') or '').replace(' to ', '-')
    parts = [gnum(x) for x in g.split('-') if x.strip()]
    parts = [p for p in parts if p is not None]
    if not parts:
        if 'HS' in rt:
            return 'HS'
        return 'ES' if rt in ('EMS', '') else 'EC'
    lo, hi = min(parts), max(parts)
    if hi <= -1:
        return 'EC'
    if hi >= 9:
        return 'HS'
    if lo >= 5:
        return 'MS'
    return 'ES'


LEVEL = {d: level_of(s) for d, s in by_dbn.items()}
SHARED_BLDG = {}
for _d in by_dbn:
    _b = get('capacity', _d, 'building_id')
    if _b:
        SHARED_BLDG[_b] = SHARED_BLDG.get(_b, 0) + 1


# ---------- measure definitions ----------
def from_src(key, name, **kw):
    def f(dbn):
        return get(key, dbn, name)
    f.key, f.name = key, name
    return f


def by_level(key, names):
    def f(dbn):
        lv = LEVEL[dbn]
        name = names.get(lv, names['other'])
        return get(key, dbn, name)
    f.key, f.name = key, names['other']
    return f


def test_year_group(dbn):
    """Charter test results are spring 2025 (NYSED's newest bulk file) while
    district results are spring 2026, and scores fell in 2026, so charters are
    ranked only against other charters."""
    y = get('tests', dbn, 'year')
    return '-c25' if y in (2025, '2025') else ''


def tests_or_sqr(test_field, sqr_field):
    use_tests = SRC.get('tests') and test_field in SRC['tests']['fields']
    def f(dbn):
        return get('tests', dbn, test_field) if use_tests else get('sqr', dbn, sqr_field)
    f.key, f.name = ('tests', test_field) if use_tests else ('sqr', sqr_field)
    f.source = 'New York State tests' + (' (DOE results; NYSED for charter schools)' if use_tests else ', via DOE School Quality Report')
    f.vintage = 'spring 2026; charter schools spring 2025' if use_tests else '2024-25'
    return f


def trend_of(dbn, year):
    for y, v in by_dbn[dbn].get('trend') or []:
        if y == year:
            return v
    return None


def _k12_2024_25():
    """2024-25 enrollment minus 3-K and pre-K (who can't be suspended), from
    the Demographic Snapshot's school tab."""
    import openpyxl
    wb = openpyxl.load_workbook(ROOT / 'data/sources/nyc_doe_demographic_snapshot_2021-22_to_2025-26.xlsx', read_only=True)
    rows = wb['School'].iter_rows(values_only=True)
    h = next(rows)
    ix = {c: i for i, c in enumerate(h)}
    out = {}
    for r in rows:
        if r[ix['Year']] == '2024-25' and r[0]:
            out[r[0].strip().upper()] = (r[ix['Total Enrollment']] or 0) - (r[ix['Grade 3K']] or 0) - (r[ix['Grade PK (Half Day & Full Day)']] or 0)
    return out


K12_2425 = _k12_2024_25()
SUSP_FILE = set(SRC['suspensions']['schools']) if SRC.get('suspensions') else set()


def suspensions(dbn):
    if dbn.startswith('84') or not SRC.get('suspensions'):
        return None  # charter schools aren't in DOE's discipline report
    e = K12_2425.get(dbn)
    if not e:
        return None
    if dbn not in SUSP_FILE:
        return "Not listed in DOE's report"
    t = get('suspensions', dbn, 'total_suspensions')
    if t is None:
        return 'Redacted by DOE (it hides counts of 1 to 5)'
    return t / e * 100
suspensions.key, suspensions.name = 'suspensions', 'total_suspensions'


def enroll(dbn):
    d = by_dbn[dbn].get('demo') or {}
    return d.get('enrollment_latest')


def enroll_change(dbn):
    a, b = trend_of(dbn, '2021-22'), trend_of(dbn, '2025-26')
    if not a or a < 20 or b is None:
        return None
    return round((b - a) / a, 4)


def access(dbn):
    """DOE's accessibility list, read against the building DOE's current
    school list gives for the school. DOE leaves inaccessible buildings off
    the list."""
    b = LCG.get(dbn, {}).get('building')
    if b and b not in ('NAN', ''):
        if (dbn, b) in ACC_PAIR:
            return ACC_PAIR[(dbn, b)]
        if b in ACC_BLDG:
            return ACC_BLDG[b]  # listed under a school it shares the building with
        if ACC_DBN.get(dbn):
            return "Main building not on DOE's accessible list; another of its sites is"
        return "Not on DOE's accessible-buildings list"
    return get('accessibility', dbn, 'accessibility')  # not on DOE's current list; use the August roster match
access.key, access.name = 'accessibility', 'accessibility'


def demo(name, scale=1):
    def f(dbn):
        d = by_dbn[dbn].get('demo') or {}
        v = d.get(name)
        return None if v is None else round(v / scale, 4)
    return f


SNAP = 'DOE Demographic Snapshot'
M = []


def add(id, group, fn, label, short=None, unit='pct', dir=0, dp=None, definition=None, source=None,
        vintage=None, text=None, split=None):
    key = getattr(fn, 'key', None)
    if key and not SRC.get(key):
        return
    f = fld(key, fn.name) if key else None
    M.append({
        'id': id, 'group': group, 'label': label, 'short': short or label, 'unit': unit, 'dir': dir,
        **({'dp': dp} if dp is not None else {}),
        'def': definition or (f or {}).get('definition', ''),
        'source': source or getattr(fn, 'source', None) or (src_name(key) if key else ''),
        'source_url': SRC[key].get('source_url') if key else None,
        'vintage': vintage or getattr(fn, 'vintage', None) or (SRC[key]['vintage'] if key else ''),
        'fn': fn, 'text': text, 'split': split,
    })


add('teacher_trust', 'quick', from_src('survey', 'teacher_principal_effective'),
    'Teachers who say the principal runs the school well', 'Teachers: principal runs it well', dir=1,
    source='NYC School Survey', vintage='spring 2026')
add('teacher_rec', 'quick', from_src('survey', 'teacher_recommend'),
    'Teachers who would recommend the school to families', 'Teachers would recommend', dir=1,
    source='NYC School Survey', vintage='spring 2026')
add('chronic', 'quick', from_src('attendance', 'chronic_absent'),
    'Students chronically absent (missed 10% or more of days)', 'Chronically absent', dir=-1,
    source='DOE attendance data')

add('impact', 'learning', by_level('sqr', {'HS': 'hs_impact_score', 'HST': 'hst_impact_score', 'other': 'ems_impact_score'}),
    "DOE impact score: progress against similar students", 'Impact score (DOE)', unit='num', dp=2, dir=1,
    definition="DOE's value-added score: the school's results minus what the same students would be expected to achieve at an average city school, given incoming test scores, poverty, disability and English learner status. DOE scales it within each school type so a typical school is near 0.50; a few scores run above 1.0. High schools with only a middle-grades report have no high school score and are left blank rather than ranked against high schools.",
    source='DOE School Quality Report')
add('performance', 'learning', by_level('sqr', {'HS': 'hs_performance_score', 'HST': 'hst_performance_score', 'other': 'ems_performance_score'}),
    'DOE performance score: results against all schools of its type', 'Performance score (DOE)', unit='num', dp=2, dir=1,
    definition="DOE's score for raw results, without adjusting for who the students are. Elementary and middle schools: state English and math test scores. High schools: English and Algebra I Regents scores, the four-year graduation rate and college enrollment within six months, a quarter each. Transfer schools: English and Algebra I Regents (a quarter each) and the six-year graduation rate (half). DOE scales it within each school type so a typical school is near 0.50; a few scores run above 1.0.",
    source='DOE School Quality Report')
add('ela', 'learning', tests_or_sqr('ela_prof', 'ela_prof_pct'),
    'Students proficient in English (state test, grades 3-8)', 'Proficient in English', dir=1, split=test_year_group,
    definition='Share of students tested in grades 3-8 who scored at Level 3 or 4 on the state English test. District schools: spring 2026, from DOE. Charter schools: spring 2025, from NYSED, whose 2026 school file is not out yet.')
add('math', 'learning', tests_or_sqr('math_prof', 'math_prof_pct'),
    'Students proficient in math (state test, grades 3-8)', 'Proficient in math', dir=1, split=test_year_group,
    definition='Share of students tested in grades 3-8 who scored at Level 3 or 4 on the state math test. Eighth graders who took the Algebra I Regents instead are not counted, so at some middle schools this describes only part of the grade. District schools: spring 2026, from DOE. Charter schools: spring 2025, from NYSED.')
add('grad4', 'learning', from_src('graduation', 'grad_4yr'),
    'Four-year graduation rate', 'Graduate in 4 years', dir=1, source='DOE graduation results', vintage='Class of 2025',
    definition='Share of students who entered 9th grade in 2021-22 (Cohort 2021) who earned a Local or Regents diploma within four years, including August graduates. Transfer high schools are shown with this standard rate, not the separate rate DOE computes for them, and are ranked only against other transfer schools. Charter schools are not in DOE\'s school-level file.')
add('ccr', 'learning', from_src('graduation', 'ccr_4yr'),
    'College and career readiness score (0-100)', 'College readiness score', unit='num', dp=0, dir=1,
    source='DOE School Quality Report', vintage='2024-25, Class of 2025')
add('advanced', 'learning', from_src('sqr', 'adv_any_enrolled_pct'),
    'Students taking an advanced course (AP, IB, college credit, or Algebra II, calculus, chemistry or physics)', 'Take an advanced course', dir=1,
    source='DOE School Quality Report')
add('cte', 'learning', from_src('sqr', 'hs_industry_assessment_pct'),
    'Students who passed an industry-recognized technical (CTE) exam', 'Passed a CTE exam', dir=0,
    definition="Share of the Class of 2025 (students who entered 9th grade in 2021-22) who passed an industry-recognized technical assessment, the career and technical education certification exam. Mostly zero outside CTE schools. Transfer schools are left out because DOE measures them against a different cohort.",
    source='DOE School Quality Report', vintage='2024-25, Class of 2025')

add('safe', 'climate', from_src('survey', 'student_safe'),
    'Students who feel safe in the hallways and cafeteria', 'Students feel safe', dir=1,
    source='NYC School Survey', vintage='spring 2026')
add('supported', 'climate', from_src('survey', 'student_supported'),
    'Students who say most or all teachers support them when upset', 'Teachers support students', dir=1,
    source='NYC School Survey', vintage='spring 2026')
add('trusted_adult', 'climate', from_src('survey', 'student_trusted_adult'),
    'Students with a trusted adult at school', 'Have a trusted adult', dir=1,
    source='NYC School Survey', vintage='spring 2026')
add('vaping', 'climate', from_src('survey', 'student_vaping_often'),
    'Students who say classmates vape often', 'Say classmates vape often', dir=-1,
    definition='Share of responding students answering "Very often" or "Often" to "How often do students in this school vape?" DOE lists it under Additional Questions and does not score it.',
    source='NYC School Survey', vintage='spring 2026')
add('families', 'climate', from_src('survey', 'parent_satisfied'),
    "Families satisfied with their child's education", 'Families satisfied', dir=1,
    definition='Share of responding families answering "Satisfied" or "Very satisfied" to "How satisfied are you with ... the education my child has received this year?" Answers of "I don\'t know" are left out.',
    source='NYC School Survey', vintage='spring 2026')
add('attendance', 'climate', from_src('attendance', 'attendance_rate'),
    'Average daily attendance', 'Attendance rate', unit='pct1', dir=1, source='DOE attendance data')
add('suspensions', 'climate', suspensions,
    'Suspensions per 100 students', 'Suspensions per 100', unit='num', dp=1, dir=0,
    definition="Principal's and superintendent's suspensions in 2024-25 per 100 students in kindergarten through 12th grade (3-K and pre-K children, who can't be suspended, are left out of the count). DOE redacts counts of 1 to 5, so schools with few suspensions show \"redacted\" instead of a rate; some schools aren't in DOE's report at all. Neither high nor low is good on its own: a high rate can mean strict discipline, and a low one doesn't guarantee a calm school.",
    source='DOE Local Law 93 discipline report; enrollment from DOE Demographic Snapshot', vintage='2024-25')

add('experience', 'staff', from_src('sqr', 'pct_teachers_3plus_years'),
    'Teachers with three or more years of experience', 'Teachers with 3+ years', dir=1,
    source='DOE School Quality Report')
add('class_size', 'staff', from_src('class_size', 'avg_class_size_overall'),
    'Average class size', 'Average class size', unit='num', dp=1, dir=-1,
    source='DOE class size report', vintage='2025-26 (June)')
def class_cap(dbn):
    v = get('class_size', dbn, 'cap_pct_at_or_below')
    ex = get('class_size', dbn, 'cap_n_exempt_classes') or 0
    ne = get('class_size', dbn, 'cap_n_nonexempt_classes') or 0
    if ex and ex >= ne:
        return f'{ex:,} of {ex + ne:,} classes exempted from the cap'
    return v
class_cap.key, class_cap.name = 'class_size', 'cap_pct_at_or_below'


add('class_cap', 'staff', class_cap,
    "Classes within the state's class-size cap", 'Classes within state cap', dir=1,
    definition="Share of a school's non-exempt classes at or below the state cap (20 students in K-3, 23 in grades 4-8, 25 in high school). DOE exempts some classes, mostly for lack of space; exempt classes are left out of the share, so where half or more of a school's classes are exempt the map shows the exempt count instead of a share. Self-contained special education classes aren't covered.",
    source='DOE state class-size report', vintage='Oct. 31, 2025')
def counselor(dbn):
    v = get('counselors', dbn, 'students_per_counselor')
    n = get('counselors', dbn, 'n_counselors_total')
    e = get('counselors', dbn, 'enrollment_basis')
    if v is None and n and 0 < n < 1 and e:
        return e / n  # DOE's file shows enrollment / 1 here; this is enrollment / actual counselors
    if v is not None and n and e:
        return e / n  # same as DOE's ratio, unrounded, so the page rounds only once
    return v
counselor.key, counselor.name = 'counselors', 'students_per_counselor'


add('counselor', 'staff', counselor,
    'Students per guidance counselor', 'Students per counselor', unit='num', dp=0, dir=-1,
    definition="2024-25 enrollment divided by full- and part-time guidance counselors on staff in 2025-26 (social workers not counted). Part-time and shared counselors count as fractions. Where a school has less than one counselor, the map divides by the actual fraction; DOE's own file divides by one there. Schools with no counselor say so. The guide cites a recommended 250 students per counselor, fewer at high-need schools.",
    source='DOE guidance counselor report (Local Law 56)', vintage='2025-26')
add('per_pupil', 'staff', from_src('spending', 'per_pupil'),
    'Spending per student', 'Spending per student', unit='dollars', dir=0,
    definition="Total federal, state and local spending at the school in 2024-25 divided by its BEDS-day enrollment, as reported to the state (NYSED's ESSA financial transparency data). It includes a share of districtwide costs. Charter schools report their own spending and district schools are reported by DOE, so the two don't compare cleanly; small schools losing students can look flush under the city's hold-harmless budget rules.",
    source='NYSED school-level spending report', vintage='2024-25')
def pta(dbn):
    v = get('pta', dbn, 'pta_per_student')
    if v == 0 and not get('pta', dbn, 'pta_expenses') and not get('pta', dbn, 'pta_ending_balance'):
        return '$0 reported (every money column is zero)'
    return v
pta.key, pta.name = 'pta', 'pta_per_student'


add('pta', 'staff', pta,
    'PTA money raised per student', 'PTA money per student', unit='dollars', dir=0,
    definition="Total PTA or parent association income in 2024-25 divided by the school's 2024-25 enrollment. The figures are self-reported: parent groups file paper reports that principals or parent coordinators key in. Schools whose report has zeros in every money column are shown as such and not ranked, since that can mean an unfiled report as easily as nothing raised. Charter schools aren't covered.",
    source='DOE PTA financial report (Local Law 171)', vintage='2024-25')

add('enrollment', 'students', enroll, 'Students enrolled', 'Enrollment', unit='count', dir=0,
    definition='Students on the Oct. 31 audited register (BEDS day for charters).', source=SNAP, vintage='2025-26')
add('enroll_change', 'students', enroll_change, 'Enrollment change since 2021-22', 'Change since 2021-22',
    unit='change', dir=0, definition='Change in enrollment from 2021-22 to 2025-26. A drop can reflect a shrinking neighborhood, not the school.',
    source=SNAP, vintage='2021-22 to 2025-26')
if SRC.get('capacity'):
    add('utilization', 'students', from_src('capacity', 'utilization'),
        "Space use: the school's enrollment as a share of the capacity SCA assigns it", 'Space use', dir=0,
        definition="The School Construction Authority's 'target' utilization for the school: its Oct. 31, 2025 enrollment divided by the seats SCA counts for it. Many schools share a building; this is the school's own share, and the building as a whole can be more or less crowded (shown under \"Also on file\"). Over 100% means more students than seats.",
        source='School Construction Authority Blue Book', vintage='2025-26')
add('eni', 'students', demo('eni', 100), 'Economic need index', 'Economic need index', dir=0,
    definition="DOE's estimate of the share of students facing economic hardship (public assistance, temporary housing, recent immigration or a high-poverty census tract).",
    source=SNAP, vintage='2025-26')
add('swd', 'students', demo('pct_swd'), 'Students with disabilities', 'Students with disabilities', dir=0,
    definition='Students with an IEP as of June 2026.', source=SNAP, vintage='2025-26')
add('ell', 'students', demo('pct_ell'), 'English language learners', 'English learners', dir=0,
    definition='Students identified as English language learners.', source=SNAP, vintage='2025-26')

add('iep_programs', 'sped', from_src('sqr', 'iep_all_programs_pct'),
    'Students with IEPs fully receiving their special-ed programs', 'IEP programs fully delivered', dir=1,
    source='DOE School Quality Report')
add('iep_services', 'sped', from_src('sqr', 'iep_all_related_services_pct'),
    'Students with IEPs fully receiving related services (speech, OT, counseling)', 'IEP services fully delivered', dir=1,
    definition="Share of students with IEPs receiving all the related services (such as speech, occupational therapy or counseling) their IEP recommends, as of June 2025. Charter schools are not included in DOE's figures.",
    source='DOE School Quality Report')
add('ict_size', 'sped', from_src('class_size', 'avg_class_size_ict'),
    'Average co-taught (ICT) class', 'Co-taught (ICT) class size', unit='num', dp=1, dir=0,
    source='DOE class size report', vintage='2025-26 (June)')
add('special_size', 'sped', from_src('class_size', 'avg_class_size_special'),
    'Average self-contained special class', 'Special class size', unit='num', dp=1, dir=0,
    source='DOE class size report', vintage='2025-26 (June)')
add('access', 'sped', access,
    'Building accessibility', 'Building accessibility', unit='text', dir=0,
    source='DOE Building Accessibility Profile list', vintage='Aug. 2026')


COL = {'teacher_trust': 'Principal trust', 'teacher_rec': 'Teachers recommend', 'chronic': 'Chronic absence', 'impact': 'Impact score', 'performance': 'Performance score', 'ela': 'English proficient', 'math': 'Math proficient', 'grad4': '4-year graduation', 'ccr': 'College readiness', 'advanced': 'Advanced courses', 'cte': 'CTE exam', 'safe': 'Feel safe', 'supported': 'Teacher support', 'trusted_adult': 'Trusted adult', 'vaping': 'Vaping', 'families': 'Families satisfied', 'attendance': 'Attendance', 'suspensions': 'Suspensions', 'experience': 'Teacher experience', 'class_size': 'Class size', 'class_cap': 'Within class cap', 'counselor': 'Per counselor', 'per_pupil': 'Spending', 'pta': 'PTA money', 'enrollment': 'Enrollment', 'enroll_change': 'Enrollment change', 'utilization': 'Building use', 'eni': 'Economic need', 'swd': 'Disabilities', 'ell': 'English learners', 'iep_programs': 'IEP programs', 'iep_services': 'IEP services', 'ict_size': 'ICT class size', 'special_size': 'Special class size', 'access': 'Accessibility'}
for m in M:
    m['col'] = COL[m['id']]


# ---------- extras shown as plain facts ----------
EXTRAS = {
    'ip_rating': 'DOE rating, 2024-25: instruction and performance',
    'ssc_rating': 'DOE rating, 2024-25: safety and school climate',
    'rwf_rating': 'DOE rating, 2024-25: relationships with families',
    'impact_note': 'DOE impact and performance scores',
    'pta_total': 'PTA money raised, 2024-25',
    'counselors': 'Guidance counselors, 2025-26',
    'social_workers': 'Social workers, 2025-26',
    'teacher_responses': 'Teachers who answered the 2026 survey',
    'authorizer': 'Charter authorizer',
    'year_opened': 'Charter school opened',
    'insideschools': 'Insideschools review',
    'building_use': 'Whole building, all schools in it',
    'current_list': "On DOE's current school list",
    'spending_note': 'About the spending figure',
}


def extras(dbn):
    x = {}
    lv = LEVEL[dbn]
    pre = 'hs' if lv == 'HS' else 'hst' if lv == 'HST' else 'ems'
    rt = get('sqr', dbn, 'report_type') or ''
    for k in ('ip', 'ssc', 'rwf'):
        v = get('sqr', dbn, f'{pre}_{k}_rating')
        if v:
            # 6-12 and K-12 schools get a separate middle-grades rating; say which one this is.
            x[f'{k}_rating'] = v + (' (high school grades)' if rt == 'EMS+HS' else '')
        elif lv == 'HS' and get('sqr', dbn, f'ems_{k}_rating'):
            x[f'{k}_rating'] = get('sqr', dbn, f'ems_{k}_rating') + ' (middle grades; no high school report)'
    if lv == 'HS' and get('sqr', dbn, 'hs_impact_score') is None and get('sqr', dbn, 'ems_impact_score') is not None:
        x['impact_note'] = "Not shown: DOE's 2024-25 report covered only this school's middle grades, so its scores can't be ranked against high schools"

    v = get('pta', dbn, 'pta_revenue')
    if v is not None:
        x['pta_total'] = f'${hu(v):,}'
    v = get('counselors', dbn, 'n_counselors_total')
    if v is not None:
        x['counselors'] = f'{v:g}'
    v = get('counselors', dbn, 'n_social_workers')
    if v is not None:
        x['social_workers'] = f'{v:g}'
    v = get('survey', dbn, 'teacher_responses')
    if v is not None:
        rr = get('survey', dbn, 'teacher_response_rate')
        x['teacher_responses'] = f'{v}' + (f' ({hu(rr * 100)}%)' if rr is not None else '')
    for k in ('authorizer', 'year_opened'):
        v = get('charters', dbn, k)
        if v:
            x[k] = str(v)
    if get('insideschools', dbn, 'review'):
        first = get('insideschools', dbn, 'review_date')
        last = get('insideschools', dbn, 'review_latest_year')
        former = get('insideschools', dbn, 'former_name')
        x['insideschools'] = ((first or 'undated') + (f', updated {last}' if last and first and str(last) not in first else '')
                              + (f'; written when the school was called {former}' if former else ''))
    bu, bid = get('capacity', dbn, 'building_utilization'), get('capacity', dbn, 'building_id')
    if bu is not None and bid and SHARED_BLDG.get(bid, 0) > 1:
        x['building_use'] = f'{hu(bu * 100)}% of capacity (building {bid}, shared by {SHARED_BLDG[bid]} schools)'
    if dbn not in LCG:
        x['current_list'] = 'No. It is missing from DOE\'s list of open schools as of Oct. 7, 2026, so it may have closed, merged or taken a new number after 2025-26.'
    if dbn == '84K964':
        x['spending_note'] = "NYSED's $4,470 for this first-year school is about a third of the next-lowest school's; treat it with caution."
    return x


def links(dbn):
    u = {}
    for k, f in (('authorizer', 'authorizer_url'), ('nysed', 'nysed_url')):
        v = get('charters', dbn, f)
        if v:
            u[k] = v
    if dbn in NYSED_URL_ADD:
        u['nysed'] = NYSED_URL_ADD[dbn]
    if 'authorizer' not in u and u.get('nysed'):
        page = NYSED_PAGES.get(u['nysed'].rstrip('/').split('/')[-1], '')
        m = re.search(r'<a href="([^"]+)">\s*(?:School\s+)?(?:Information|Profile)?[^<]{0,40}[Mm]aintained\s+[Bb]y', page)
        if m and 'nysed.gov' not in m.group(1) and re.match(r'https?://[^\s]+$', m.group(1)):
            u['authorizer'] = html_unescape(m.group(1))
    if dbn in DEAD_AUTH:
        u.pop('authorizer', None)
    v = get('insideschools', dbn, 'review_url')
    if v:
        u['insideschools'] = v
    return u


def hu(x):
    """Round half up, as the browser's Math.round and toFixed do, so a sentence
    never shows a different whole number from the row beside it."""
    return math.floor(x + 0.5)


def benchmarks(dbn, vals):
    b = []
    spc = vals.get('counselor')
    n_gc = get('counselors', dbn, 'n_counselors_total')
    if n_gc == 0:
        b.append('No guidance counselor on staff in 2025-26 (social workers are counted separately).')
    elif spc is not None and spc > 250:
        b.append(f'About {hu(spc):,} students per guidance counselor. The guide cites a recommended 250.')
    tr = vals.get('teacher_rec')
    if tr is not None and tr <= 0.5:
        b.append(f'Only {hu(tr * 100)}% of teachers would recommend the school. The guide flags schools where half or more would not.')
    u = vals.get('utilization')
    if u is not None and u > 1.0:
        bu, bid = get('capacity', dbn, 'building_utilization'), get('capacity', dbn, 'building_id')
        shared = bu is not None and SHARED_BLDG.get(bid, 0) > 1
        b.append(f"The school's enrollment is {hu(u * 100)}% of the capacity the School Construction Authority assigns it"
                 + (f' (its shared building is at {hu(bu * 100)}%).' if shared else '.'))
    return b


# ---------- compute ----------
def shares(sorted_vals, v):
    """Share of the OTHER peer schools with a strictly lower value, and with a
    strictly higher value, each floored to a whole percent. A school tied at
    the top gets higher-share 0, so the sheet can say "tied for highest"."""
    lo, hi = bisect_left(sorted_vals, v), bisect_right(sorted_vals, v)
    others = len(sorted_vals) - 1
    if others < 1:
        return None, None
    return 100 * lo // others, 100 * (len(sorted_vals) - hi) // others


def store_round(v):
    """The precision written to metrics.json: enough digits that the browser
    rounds the true value once for display (no double rounding). Ranks are
    computed on these same stored values."""
    if isinstance(v, float):
        return round(v, 5) if abs(v) < 10 else round(v, 3)
    return v


values = {d: {} for d in by_dbn}
for m in M:
    for d in by_dbn:
        v = store_round(m['fn'](d))
        if v is not None:
            values[d][m['id']] = v

dist, out_metrics = {}, []
for m in M:
    vals = {d: values[d][m['id']] for d in by_dbn if m['id'] in values[d]}
    if m['unit'] == 'text':
        out_metrics.append({k: v for k, v in m.items() if k not in ('fn', 'text', 'split')})
        continue
    # Text values (redacted, exempt, all-zero reports) are shown but never ranked.
    vals = {k: v for k, v in vals.items() if not isinstance(v, str)}
    allv = sorted(vals.values())
    if len(allv) < 30:
        print(f'  dropping {m["id"]}: only {len(allv)} schools')
        continue
    lo_d = allv[int(0.01 * (len(allv) - 1))]
    hi_d = allv[int(0.99 * (len(allv) - 1))]
    if m['unit'] in ('pct', 'pct1') and allv[0] >= 0 and allv[-1] <= 1:
        lo_d, hi_d = (0.0 if lo_d < 0.15 else lo_d), (1.0 if hi_d > 0.85 else hi_d)
    sp = m.get('split') or (lambda d: '')
    sfx = {d: sp(d) for d in vals}
    groups = {'ALL': sorted(v for d, v in vals.items() if not sfx[d])} if any(sfx.values()) else {'ALL': allv}
    for suf in sorted(set(sfx.values()) - {''}):
        g = sorted(v for d, v in vals.items() if sfx[d] == suf)
        if len(g) >= MIN_PEERS:
            groups['ALL' + suf] = g
    for lv in set(LEVEL.values()):
        for suf in set(sfx.values()):
            g = sorted(v for d, v in vals.items() if LEVEL[d] == lv and sfx[d] == suf)
            if len(g) >= MIN_PEERS:
                groups[lv + suf] = g
    m['_sfx'] = sfx
    dm = {'domain': [lo_d, hi_d]}
    for lv, g in groups.items():
        hist = [0] * BINS
        for v in g:
            i = int((min(max(v, lo_d), hi_d) - lo_d) / ((hi_d - lo_d) or 1) * BINS)
            hist[min(i, BINS - 1)] += 1
        dm[lv] = {'n': len(g), 'median': g[len(g) // 2] if len(g) % 2 else (g[len(g) // 2 - 1] + g[len(g) // 2]) / 2,
                  'hist': hist}
    m['_groups'] = groups
    dist[m['id']] = dm
    out_metrics.append({k: v for k, v in m.items() if k not in ('fn', 'text', '_groups', 'split', '_sfx')})

ids = [m['id'] for m in out_metrics]
mobj = {m['id']: m for m in M}
out_schools = {}
for d in by_dbn:
    vals = values[d]
    if not vals:
        continue
    v_arr, a_arr, h_arr, pk = [], [], [], {}
    for mid in ids:
        v = vals.get(mid)
        v_arr.append(v)
        g = mobj[mid].get('_groups')
        if v is None or g is None or isinstance(v, str):
            a_arr.append(None)
            h_arr.append(None)
            continue
        suf = mobj[mid]['_sfx'].get(d, '')
        key = next(k for k in (LEVEL[d] + suf, 'ALL' + suf, 'ALL') if k in g)
        if key != (LEVEL[d] if LEVEL[d] in g else 'ALL'):  # the page's default peer group
            pk[ids.index(mid)] = key
        a, h = shares(g[key], vals[mid])
        a_arr.append(a)
        h_arr.append(h)
    rec = {'level': LEVEL[d], 'v': v_arr, 'a': a_arr, 'h': h_arr}
    if pk:
        rec['pk'] = pk
    x = extras(d)
    if x:
        rec['x'] = x
    b = benchmarks(d, vals)
    if b:
        rec['b'] = b
    u = links(d)
    if u:
        rec['u'] = u
    # DOE's snapshot URL needs the report type: tools.nycenet.edu/snapshot/2025/<DBN>/<EMS|HS|HST|EC|D75>/
    rt = get('sqr', d, 'report_type')
    if rt:
        rec['st'] = ('HS' if LEVEL[d] == 'HS' else 'EMS') if rt == 'EMS+HS' else rt
    t = {}
    dm = by_dbn[d].get('demo') or {}
    if dm.get('eni_mask') == 'above' and 'eni' in ids:
        t[ids.index('eni')] = 'over 95%'
    if dm.get('eni_mask') == 'below' and 'eni' in ids:
        t[ids.index('eni')] = 'under 5%'
    if get('counselors', d, 'n_counselors_total') == 0 and 'counselor' in ids:
        t[ids.index('counselor')] = 'no counselor'
    if t:
        rec['t'] = t
    out_schools[d] = rec

out = {
    'built': __import__('datetime').date.today().isoformat(),
    'groups': GROUPS, 'metrics': out_metrics, 'dist': dist, 'extras': EXTRAS,
    'levels': {lv: sum(1 for d in out_schools if LEVEL[d] == lv) for lv in sorted(set(LEVEL.values()))},
    'schools': out_schools,
}
json.dump(out, open(OUT, 'w'), separators=(',', ':'), allow_nan=False)
print(f'{len(out_metrics)} measures, {len(out_schools)} schools, {OUT.stat().st_size / 1024:.0f} KB')
for m in out_metrics:
    n = sum(1 for r in out_schools.values() if r['v'][ids.index(m['id'])] is not None)
    print(f'  {m["id"]:<15} {n:>5}  {m["vintage"]}')
print('levels', out['levels'])

# ---------- data/MEASURES.md: generated, so it can't drift from the data ----------
DIRW = {1: 'higher is more favorable', -1: 'lower is more favorable', 0: 'no better or worse'}
lines = ['# Measures on the school sheet', '',
         f'Generated by `scripts/build_metrics.py` on {out["built"]} from `data/metrics/*.json`. Do not edit by hand.', '',
         'Schools with each measure are ranked against schools of the same level: ' +
         ', '.join(f'{LEVEL_NAME_MD[k]} ({v:,})' for k, v in out['levels'].items()) + '.', '']
for g in GROUPS:
    ms = [m for m in out_metrics if m['group'] == g['id']]
    if not ms:
        continue
    lines += [f'## {g["label"]}', '', '| Measure | Schools | Source | Vintage | Reading | Definition |', '|---|---|---|---|---|---|']
    for m in ms:
        n = sum(1 for r in out_schools.values() if r['v'][ids.index(m['id'])] is not None)
        d = (m['def'] or '').replace('|', '/').replace('\n', ' ')
        lines.append(f'| {m["label"]} | {n:,} | {m["source"]} | {m["vintage"]} | {DIRW[m["dir"]] if m["unit"] != "text" else "text"} | {d} |')
    lines.append('')
(ROOT / 'data/MEASURES.md').write_text('\n'.join(lines))
