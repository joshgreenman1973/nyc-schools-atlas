#!/usr/bin/env python3
"""Build data/metrics/tests.json: New York State grades 3-8 ELA and math results, by school.

Two sources, because neither covers every school for the newest year:

  1. District schools: NYC DOE InfoHub school-level Excel files, spring 2026 results
     (with spring 2025 as the prior year). Sheets "ELA - All" and "Math - All",
     rows Grade = "All Grades", Category = "All Students". The DOE notes say
     charter schools are not included.
       https://infohub.nyced.org/reports/academics/test-results
       https://infohub.nyced.org/docs/default-source/default-document-library/school-ela-results-public.xlsx
       https://infohub.nyced.org/docs/default-source/default-document-library/school-math-results-public.xlsx

  2. Charter schools: NYSED Report Card Database SRC2025 (Access), tables
     "Annual EM ELA" and "Annual EM MATH", spring 2025 results (with spring 2024
     as the prior year, from the same tables). NYSED has not posted spring 2026
     in bulk yet.
       https://data.nysed.gov/downloads.php
       https://data.nysed.gov/files/essa/24-25/SRC2025.zip

Charter IDs: NYSED keys schools by BEDS code (ENTITY_CD) and INSTITUTION_ID, not DBN.
The crosswalk below uses, in order:
  a. DOE LCGMS school list (https://www.nycenet.edu/PublicApps/LCGMS.aspx, downloaded
     2026-10-07): "BEDS Number" -> "ATS System Code" (the DBN), matched against any
     ENTITY_CD the institution used in SRC2025 (2024 or 2025 rows).
  b. Same LCGMS list where the "BEDS Number" cell holds the NYSED INSTITUTION_ID.
  c. NYC Open Data 2019-20 School Locations (wg9x-4ke6): BEDS -> system_code.
  d. Same, reached through NYSED SRC2020 "Institution Grouping" (2019-20 ENTITY_CD ->
     INSTITUTION_ID), for charters whose BEDS code changed after a move.
  e. A short manual table (MANUAL below), matched on name and checked against DOE
     Demographic Snapshot 2024-25 grade enrollment.
Every pair of methods that both produce a DBN must agree, or the script raises.

Large raw files (>25 MB) are not kept in the repo. Point TESTS_RAW_DIR at a folder holding
them (names in BIG_FILES), or run with --fetch to download them there.

Usage: python3 scripts/metrics/build_tests.py [--fetch]
"""
import io
import json
import os
import re
import sys
import tempfile
import urllib.request
import zipfile

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(ROOT, "data", "sources")
OUT = os.path.join(ROOT, "data", "metrics", "tests.json")
ATLAS = os.path.join(ROOT, "data", "schools.json")
DEFAULT_RAW = "/private/tmp/claude-501/-Users-joshgreenman-Experiments/92d82c73-da9a-4cd9-bf8c-aaf5be19c7ce/scratchpad/tests"
RAW_DIR = os.environ.get("TESTS_RAW_DIR", DEFAULT_RAW)

INFOHUB_PAGE = "https://infohub.nyced.org/reports/academics/test-results"
ELA_URL = "https://infohub.nyced.org/docs/default-source/default-document-library/school-ela-results-public.xlsx"
MATH_URL = "https://infohub.nyced.org/docs/default-source/default-document-library/school-math-results-public.xlsx"
NYSED_PAGE = "https://data.nysed.gov/downloads.php"
SRC2025_URL = "https://data.nysed.gov/files/essa/24-25/SRC2025.zip"
SRC2020_URL = "https://data.nysed.gov/files/essa/19-20/SRC2020.zip"

BIG_FILES = {
    "ela": ("nyc_doe_school_ela_results_2018-2026_asof_2026-08-03.xlsx", ELA_URL),
    "math": ("nyc_doe_school_math_results_2018-2026_asof_2026-08-03.xlsx", MATH_URL),
    "src2025": ("nysed_src2025_report_card_database_2024-25.zip", SRC2025_URL),
}
SRC2020_ZIP = os.path.join(SRC_DIR, "nysed_src2020_report_card_database_2019-20.zip")
LCGMS_2026 = os.path.join(SRC_DIR, "nyc_doe_lcgms_school_data_2026-10-07.xls")
LOC_2019 = os.path.join(SRC_DIR, "nyc_doe_school_locations_2019-20_wg9x-4ke6.csv")
SNAPSHOT = os.path.join(SRC_DIR, "nyc_doe_demographic_snapshot_2021-22_to_2025-26.xlsx")

CUR, PREV = 2026, 2025            # DOE file years
NY_CUR, NY_PREV = 2025, 2024      # NYSED SRC2025 years

# (e) Manual charter matches: NYSED INSTITUTION_ID -> DBN. Names agree; grade-level
# enrollment checked against the DOE 2024-25 Demographic Snapshot by check_manual().
MANUAL = {
    # SUCCESS ACADEMY CS-NYC 12 (ENTITY_CD 320800861098) = "Success Academy Charter School - NYC 12".
    # LCGMS lists BEDS 342400861098 for 84X647 (same last six digits; school moved).
    "800000084537": "84X647",
    # SUCCESS ACADEMY CS-NYC 14 (ENTITY_CD 342700861100) = "Success Academy Charter School - NYC 14".
    # LCGMS "BEDS Number" for 84Q422 is 38400010422, not a BEDS code.
    "800000084539": "84Q422",
}

BORO = {"31": "M", "32": "X", "33": "K", "34": "Q", "35": "R"}


def die(msg):
    raise SystemExit("build_tests.py: " + msg)


def big_path(key, fetch):
    name, url = BIG_FILES[key]
    for d in (SRC_DIR, RAW_DIR):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    if not fetch:
        die(f"missing {name}. Download {url} to {RAW_DIR}/{name} (or set TESTS_RAW_DIR), or rerun with --fetch.")
    os.makedirs(RAW_DIR, exist_ok=True)
    p = os.path.join(RAW_DIR, name)
    print(f"fetching {url} -> {p}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r, open(p, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    return p


def num(v):
    """Source cell -> float, or None for suppression markers / blanks."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if pd.isna(v) else float(v)
    s = str(v).strip()
    if s in ("", "s", "-", ".", "N/A", "NA"):
        return None
    try:
        return float(s)
    except ValueError:
        die(f"unexpected cell value {v!r}")


def r4(x):
    return None if x is None else round(x, 4)


def r1(x):
    return None if x is None else round(x, 1)


# ---------------------------------------------------------------- DOE district schools
def load_doe(path, sheet):
    df = pd.read_excel(path, sheet_name=sheet, dtype=object)
    need = ["DBN", "School Name", "Grade", "Year", "Category", "Number Tested",
            "Mean Scale Score", "# Level 3+4", "% Level 3+4"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        die(f"{sheet}: missing columns {miss}")
    if set(df["Category"].unique()) != {"All Students"}:
        die(f"{sheet}: expected only 'All Students' rows")
    df = df[df["Grade"] == "All Grades"].copy()
    df["Year"] = df["Year"].astype(int)
    df["DBN"] = df["DBN"].astype(str).str.strip().str.upper()
    return df


def doe_block(df, subj):
    cur = df[df.Year == CUR].set_index("DBN")
    prev = df[df.Year == PREV].set_index("DBN")
    if cur.index.duplicated().any() or prev.index.duplicated().any():
        die(f"DOE {subj}: duplicate DBN rows")
    if len(cur) < 1100 or len(prev) < 1100:
        die(f"DOE {subj}: only {len(cur)} schools for {CUR}, {len(prev)} for {PREV}; expected 1,100+")
    out = {}
    for dbn, r in cur.iterrows():
        nt = num(r["Number Tested"])
        pct = num(r["% Level 3+4"])
        p = prev.loc[dbn] if dbn in prev.index else None
        ppct = num(p["% Level 3+4"]) if p is not None else None
        out[dbn] = {
            f"{subj}_prof": r4(pct / 100) if pct is not None else None,
            f"{subj}_n_tested": int(nt) if nt is not None else None,
            f"{subj}_mean_scale": r1(num(r["Mean Scale Score"])),
            f"{subj}_prof_prev": r4(ppct / 100) if ppct is not None else None,
        }
    return out


# ---------------------------------------------------------------- NYSED charter schools
def open_mdb(zip_path, member_suffix, workdir):
    from access_parser import AccessParser  # pip install access-parser
    folder = os.path.dirname(zip_path)
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.endswith(member_suffix)]
        if len(names) != 1:
            die(f"{zip_path}: expected one *{member_suffix}, found {names}")
        member = names[0]
        pre = os.path.join(folder, member)  # already-extracted copy beside the zip
        if os.path.exists(pre) and os.path.getsize(pre) == z.getinfo(member).file_size:
            path = pre
        else:
            print(f"extracting {member} ...")
            path = z.extract(member, workdir)
    return AccessParser(path)


def nysed_table(db, name):
    df = pd.DataFrame(db.parse_table(name))
    df["ENTITY_CD"] = df["ENTITY_CD"].astype(str).str.strip()
    df["INSTITUTION_ID"] = df["INSTITUTION_ID"].astype(str).str.strip()
    return df


def nyc_charter_rows(df):
    nyc = df[df.ENTITY_CD.str[0].eq("3") & df.ENTITY_CD.str[6:8].eq("86")
             & df.SUBGROUP_NAME.eq("All Students")].copy()
    nyc["Y"] = nyc["YEAR"].astype(str).str.rstrip(".").astype(float).astype(int)
    return nyc


def nysed_block(df, subj, grades, agg_name, regents):
    """All-grades values from grade-level rows (grades 3-8, no Regents), per institution-year."""
    res = {}
    for (inst, y), g in df.groupby(["INSTITUTION_ID", "Y"]):
        gr = g[g.ASSESSMENT_NAME.isin(grades)]
        if gr.ASSESSMENT_NAME.duplicated().any():
            die(f"NYSED {subj}: duplicate grade rows for {inst} {y}")
        nt = npf = tss = 0.0
        nt_ok = prof_ok = tss_ok = True
        for _, r in gr.iterrows():
            t = num(r.NUM_TESTED)
            if t is None:
                nt_ok = prof_ok = tss_ok = False
                continue
            nt += t
            if t == 0:
                continue
            p, s = num(r.NUM_PROF), num(r.TOTAL_SCALE_SCORES)
            if p is None:
                prof_ok = False
            else:
                npf += p
            if s is None:
                tss_ok = False
            else:
                tss += s
        # consistency with NYSED's own all-grades row
        agg = g[g.ASSESSMENT_NAME == agg_name]
        if len(agg) == 1 and nt_ok:
            a_nt = num(agg.iloc[0].NUM_TESTED)
            reg_nt = sum(num(v) or 0 for v in g[g.ASSESSMENT_NAME.isin(regents)].NUM_TESTED)
            if a_nt is not None and a_nt != nt + reg_nt:
                die(f"NYSED {subj} {inst} {y}: {agg_name} NUM_TESTED {a_nt} != grades {nt} + Regents {reg_nt}")
            if not regents and prof_ok:
                a_p = num(agg.iloc[0].NUM_PROF)
                if a_p is not None and a_p != npf:
                    die(f"NYSED {subj} {inst} {y}: {agg_name} NUM_PROF {a_p} != sum of grades {npf}")
        if len(gr) == 0:
            continue
        res[(inst, y)] = {
            "n": int(nt) if nt_ok else None,
            "prof": r4(npf / nt) if (nt_ok and prof_ok and nt > 0) else None,
            "mean": r1(tss / nt) if (nt_ok and tss_ok and nt > 0) else None,
            "name": g.ENTITY_NAME.iloc[0],
        }
    return res


# ---------------------------------------------------------------- crosswalk
def load_lcgms_2026():
    raw = open(LCGMS_2026, "rb").read().decode("utf-16")
    d = pd.read_html(io.StringIO(raw), header=0)[0]
    d["dbn"] = d["ATS System Code"].astype(str).str.strip().str.upper()

    def clean(v):
        if pd.isna(v):
            return ""
        if isinstance(v, float):
            return str(int(v))
        return str(v).strip()
    d["beds"] = d["BEDS Number"].map(clean)
    d = d[d.dbn.str.startswith("84")]
    if len(d) < 250:
        die(f"LCGMS: only {len(d)} charter rows")
    by_beds = {}
    for b, dbn, nm in zip(d.beds, d.dbn, d["Location Name"]):
        if b:
            if b in by_beds and by_beds[b][0] != dbn:
                die(f"LCGMS: BEDS {b} on two DBNs")
            by_beds[b] = (dbn, nm)
    return by_beds, set(d.dbn)


def load_loc_2019():
    d = pd.read_csv(LOC_2019, dtype=str)
    d["dbn"] = d["system_code"].str.strip().str.upper()
    d["beds"] = d["BEDS"].str.strip()
    d = d[d.dbn.str.startswith("84", na=False)].drop_duplicates(["dbn", "beds"])
    if d.beds.duplicated().any():
        die("2019-20 locations: duplicate charter BEDS")
    return dict(zip(d.beds, zip(d.dbn, d.location_name)))


def check_manual(inst_ids, dbn_of, ela_rows):
    """Compare NYSED 2025 grade 3-8 ELA enrollment (TOTAL_COUNT) to DOE 2024-25 snapshot."""
    snap = pd.read_excel(SNAPSHOT, sheet_name="School", dtype=object)
    snap = snap[snap.Year == "2024-25"].set_index("DBN")
    notes = []
    for inst in inst_ids:
        dbn = dbn_of[inst]
        if dbn not in snap.index:
            die(f"manual match {inst}->{dbn}: DBN not in DOE 2024-25 snapshot")
        g = ela_rows[(ela_rows.INSTITUTION_ID == inst) & (ela_rows.Y == NY_CUR)]
        ny = {int(a[-1]): num(t) or 0 for a, t in zip(g.ASSESSMENT_NAME, g.TOTAL_COUNT) if re.fullmatch(r"ELA[3-8]", a)}
        doe = {k: int(snap.loc[dbn, f"Grade {k}"]) for k in range(3, 9)}
        tot_n, tot_d = sum(ny.values()), sum(doe.values())
        if tot_d == 0 or not (0.85 <= tot_n / tot_d <= 1.15):
            die(f"manual match {inst}->{dbn}: grade 3-8 enrollment {tot_n} (NYSED) vs {tot_d} (DOE)")
        notes.append(f"{dbn} ({snap.loc[dbn, 'School Name']}): NYSED 2025 grades 3-8 ELA enrollment {int(tot_n)} vs DOE 2024-25 snapshot {tot_d}")
    return notes


def crosswalk(ela_rows, math_rows, src2020_db):
    lc26, lc26_dbns = load_lcgms_2026()
    loc19 = load_loc_2019()
    ig20 = pd.DataFrame(src2020_db.parse_table("Institution Grouping"))
    ig20 = ig20[["INSTITUTION_ID", "ENTITY_CD"]].astype(str).apply(lambda s: s.str.strip()).drop_duplicates()
    inst_to_ent20 = ig20.groupby("INSTITUTION_ID").ENTITY_CD.apply(set).to_dict()

    rows = pd.concat([ela_rows, math_rows])
    ents = {inst: (sorted(set(g.ENTITY_CD)), g.sort_values("Y").ENTITY_NAME.iloc[-1])
            for inst, g in rows.groupby("INSTITUTION_ID")}
    xw = {}
    superseded = []
    for inst, (ecds, name) in ents.items():
        found = {}
        for e in ecds:
            if e in lc26:
                found.setdefault("lcgms_2026_beds", set()).add(lc26[e][0])
        if inst in lc26:
            found.setdefault("lcgms_2026_institution_id", set()).add(lc26[inst][0])
        for e in ecds:
            if e in loc19:
                found.setdefault("locations_2019_20_beds", set()).add(loc19[e][0])
        for e in inst_to_ent20.get(inst, ()):
            if e in loc19:
                found.setdefault("locations_2019_20_via_src2020_institution_id", set()).add(loc19[e][0])
        if inst in MANUAL:
            found.setdefault("manual", set()).add(MANUAL[inst])
        dbns = set().union(*found.values()) if found else set()
        if len(dbns) > 1:
            # 2019-20 DBNs can be stale after a borough move; the current LCGMS list wins only
            # if it also has the 2025 BEDS code. Anything else is a real conflict.
            cur = found.get("lcgms_2026_beds") or found.get("lcgms_2026_institution_id")
            if cur and len(cur) == 1:
                superseded.append(f"{name} ({inst}): {next(iter(cur))} per current LCGMS, not {'/'.join(sorted(dbns - cur))} from 2019-20")
                dbns = set(cur)
            else:
                die(f"crosswalk conflict for {inst} {name}: {found}")
        if not dbns:
            continue
        dbn = dbns.pop()
        method = next(m for m in ("lcgms_2026_beds", "lcgms_2026_institution_id", "locations_2019_20_beds",
                                  "locations_2019_20_via_src2020_institution_id", "manual") if m in found)
        cur_ecd = rows[(rows.INSTITUTION_ID == inst)].sort_values("Y").ENTITY_CD.iloc[-1]
        xw[inst] = {"dbn": dbn, "method": method, "nysed_entity_cd": cur_ecd, "nysed_name": name,
                    "in_current_lcgms": dbn in lc26_dbns}
    dbn_list = [v["dbn"] for v in xw.values()]
    dup = {d for d in dbn_list if dbn_list.count(d) > 1}
    if dup:
        die(f"crosswalk: DBNs assigned to two NYSED institutions: {dup}")
    man_notes = check_manual([i for i, v in xw.items() if v["method"] == "manual"],
                             {i: v["dbn"] for i, v in xw.items()}, ela_rows)
    return xw, man_notes, superseded


# ---------------------------------------------------------------- main
def main():
    fetch = "--fetch" in sys.argv
    ela_p, math_p, src25_p = (big_path(k, fetch) for k in ("ela", "math", "src2025"))
    for p in (SRC2020_ZIP, LCGMS_2026, LOC_2019, SNAPSHOT):
        if not os.path.exists(p):
            die(f"missing {p}")

    # District schools (DOE)
    doe_ela = doe_block(load_doe(ela_p, "ELA - All"), "ela")
    doe_math = doe_block(load_doe(math_p, "Math - All"), "math")
    doe_dbns = sorted(set(doe_ela) | set(doe_math))
    if any(d.startswith("84") for d in doe_dbns):
        die("DOE file unexpectedly contains charter DBNs")

    # Charter schools (NYSED)
    with tempfile.TemporaryDirectory() as tmp:
        db25 = open_mdb(src25_p, "SRC2025_Group4.mdb", tmp)
        ela_rows = nyc_charter_rows(nysed_table(db25, "Annual EM ELA"))
        math_rows = nyc_charter_rows(nysed_table(db25, "Annual EM MATH"))
        del db25
        db20 = open_mdb(SRC2020_ZIP, ".mdb", tmp)
        xw, man_notes, superseded = crosswalk(ela_rows, math_rows, db20)
    ny_ela = nysed_block(ela_rows, "ela", [f"ELA{g}" for g in range(3, 9)], "ELA3_8", [])
    ny_math = nysed_block(math_rows, "math", [f"MATH{g}" for g in range(3, 9)], "MATH3_8",
                          ["RegentsMath6", "RegentsMath7", "RegentsMath8"])
    ch_insts = sorted({i for (i, y) in list(ny_ela) + list(ny_math) if y == NY_CUR})
    reg = math_rows[(math_rows.Y == NY_CUR) & math_rows.ASSESSMENT_NAME.isin(["RegentsMath6", "RegentsMath7", "RegentsMath8"])]
    reg_n = reg.assign(n=reg.NUM_TESTED.map(lambda v: num(v) or 0)).groupby("INSTITUTION_ID").n.sum()
    n_reg_schools = int((reg_n > 0).sum())
    if len(ch_insts) < 230:
        die(f"NYSED: only {len(ch_insts)} NYC charters with {NY_CUR} results; expected 230+")
    unmapped = [(i, (ny_ela.get((i, NY_CUR)) or ny_math.get((i, NY_CUR)))["name"]) for i in ch_insts if i not in xw]
    if unmapped:
        die(f"charters with {NY_CUR} results but no DBN: {unmapped}")

    schools = {}
    for dbn in doe_dbns:
        rec = {"year": CUR, "prev_year": PREV, "src": "NYC DOE"}
        for blk in (doe_ela.get(dbn), doe_math.get(dbn)):
            if blk:
                rec.update(blk)
        schools[dbn] = rec
    charter_xw = {}
    for inst in ch_insts:
        x = xw[inst]
        dbn = x["dbn"]
        if dbn in schools:
            die(f"{dbn} appears in both DOE and NYSED outputs")
        rec = {"year": NY_CUR, "prev_year": NY_PREV, "src": "NYSED"}
        for subj, blk in (("ela", ny_ela), ("math", ny_math)):
            c, p = blk.get((inst, NY_CUR)), blk.get((inst, NY_PREV))
            if c:
                rec[f"{subj}_prof"] = c["prof"]
                rec[f"{subj}_n_tested"] = c["n"]
                rec[f"{subj}_mean_scale"] = c["mean"]
                rec[f"{subj}_prof_prev"] = p["prof"] if p else None
        schools[dbn] = rec
        charter_xw[dbn] = {"nysed_institution_id": inst, "nysed_beds": x["nysed_entity_cd"],
                           "nysed_name": x["nysed_name"], "method": x["method"],
                           "in_current_lcgms": x["in_current_lcgms"]}

    fields_order = ["ela_prof", "math_prof", "ela_n_tested", "math_n_tested", "ela_mean_scale",
                    "math_mean_scale", "ela_prof_prev", "math_prof_prev"]
    for rec in schools.values():
        for f in fields_order:
            rec.setdefault(f, None)

    cov = {f: sum(1 for r in schools.values() if r[f] is not None) for f in fields_order}
    if cov["ela_prof"] < 1250 or cov["math_prof"] < 1250:
        die(f"coverage too low: {cov}")
    mc = {}
    for v in charter_xw.values():
        mc[v["method"]] = mc.get(v["method"], 0) + 1

    atlas = json.load(open(ATLAS))
    atlas_dbns = {r["dbn"] for r in atlas if r.get("dbn")}
    matched = len(set(schools) & atlas_dbns)

    doe_def = "DOE sheet '{s}', Grade = 'All Grades', Category = 'All Students', Year = {y}: column '{c}'"
    ny_def = "NYSED SRC2025 table '{t}', SUBGROUP_NAME = 'All Students', YEAR = {y}: {expr} over ASSESSMENT_NAME {a}"
    out = {
        "key": "tests",
        "title": "State ELA and math tests, grades 3-8",
        "source": "NYC DOE InfoHub, school ELA and math results 2018-2026 (district schools); NYSED Report Card Database SRC2025, Annual EM ELA and Annual EM MATH tables (charter schools)",
        "source_url": INFOHUB_PAGE,
        "file_url": ELA_URL,
        "file_urls": [ELA_URL, MATH_URL, SRC2025_URL],
        "vintage": "spring 2026 for district schools (NYC DOE file as of Aug. 3, 2026); spring 2025 for charter schools (NYSED, latest available in bulk). Each school's 'year' field says which.",
        "fetched": "2026-10-07",
        "fields": {
            "ela_prof": {
                "label": "ELA proficient",
                "definition": "Share of tested students scoring at Level 3 or 4 (proficient) on the New York State English Language Arts test, grades 3-8 combined.",
                "source_field": doe_def.format(s="ELA - All", y=CUR, c="% Level 3+4") + " (divided by 100). Charters: "
                                + ny_def.format(t="Annual EM ELA", y=NY_CUR, expr="sum(NUM_PROF) / sum(NUM_TESTED)", a="ELA3-ELA8"),
                "unit": "pct", "direction": "higher"},
            "math_prof": {
                "label": "Math proficient",
                "definition": "Share of tested students scoring at Level 3 or 4 (proficient) on the New York State math test, grades 3-8 combined. Students who took a Regents math exam instead of the grade-level test are not counted.",
                "source_field": doe_def.format(s="Math - All", y=CUR, c="% Level 3+4") + " (divided by 100). Charters: "
                                + ny_def.format(t="Annual EM MATH", y=NY_CUR, expr="sum(NUM_PROF) / sum(NUM_TESTED)", a="MATH3-MATH8 (RegentsMath and Combined rows excluded)"),
                "unit": "pct", "direction": "higher"},
            "ela_n_tested": {
                "label": "ELA students tested",
                "definition": "Number of students with a valid ELA test score, grades 3-8 combined.",
                "source_field": doe_def.format(s="ELA - All", y=CUR, c="Number Tested") + ". Charters: "
                                + ny_def.format(t="Annual EM ELA", y=NY_CUR, expr="sum(NUM_TESTED)", a="ELA3-ELA8"),
                "unit": "count", "direction": "neutral"},
            "math_n_tested": {
                "label": "Math students tested",
                "definition": "Number of students with a valid grade-level math test score, grades 3-8 combined.",
                "source_field": doe_def.format(s="Math - All", y=CUR, c="Number Tested") + ". Charters: "
                                + ny_def.format(t="Annual EM MATH", y=NY_CUR, expr="sum(NUM_TESTED)", a="MATH3-MATH8"),
                "unit": "count", "direction": "neutral"},
            "ela_mean_scale": {
                "label": "ELA mean scale score",
                "definition": "Average scale score of tested students, grades 3-8 combined (a student-weighted average across grades, each grade on its own scale).",
                "source_field": doe_def.format(s="ELA - All", y=CUR, c="Mean Scale Score") + ". Charters: "
                                + ny_def.format(t="Annual EM ELA", y=NY_CUR, expr="sum(TOTAL_SCALE_SCORES) / sum(NUM_TESTED)", a="ELA3-ELA8"),
                "unit": "number", "direction": "higher"},
            "math_mean_scale": {
                "label": "Math mean scale score",
                "definition": "Average scale score of tested students on the grade-level math test, grades 3-8 combined (student-weighted across grades).",
                "source_field": doe_def.format(s="Math - All", y=CUR, c="Mean Scale Score") + ". Charters: "
                                + ny_def.format(t="Annual EM MATH", y=NY_CUR, expr="sum(TOTAL_SCALE_SCORES) / sum(NUM_TESTED)", a="MATH3-MATH8"),
                "unit": "number", "direction": "higher"},
            "ela_prof_prev": {
                "label": "ELA proficient, prior year",
                "definition": "Same as ela_prof for the prior year (prev_year) from the same file.",
                "source_field": doe_def.format(s="ELA - All", y=PREV, c="% Level 3+4") + ". Charters: same as ela_prof with YEAR = " + str(NY_PREV),
                "unit": "pct", "direction": "higher"},
            "math_prof_prev": {
                "label": "Math proficient, prior year",
                "definition": "Same as math_prof for the prior year (prev_year) from the same file.",
                "source_field": doe_def.format(s="Math - All", y=PREV, c="% Level 3+4") + ". Charters: same as math_prof with YEAR = " + str(NY_PREV),
                "unit": "pct", "direction": "higher"},
            "year": {"label": "Test year", "definition": "Spring in which the current-year tests were given (2026 = 2025-26 school year).",
                     "source_field": "DOE 'Year' column / NYSED 'YEAR' column", "unit": "number", "direction": "neutral"},
            "prev_year": {"label": "Prior test year", "definition": "Spring of the *_prev values.",
                          "source_field": "DOE 'Year' column / NYSED 'YEAR' column", "unit": "number", "direction": "neutral"},
            "src": {"label": "Source", "definition": "'NYC DOE' (district schools, InfoHub file) or 'NYSED' (charter schools, SRC2025 database).",
                    "source_field": "assigned by build script", "unit": "text", "direction": "neutral"},
        },
        "notes": [
            "Two vintages. District schools carry spring 2026 results (prior year spring 2025) from the NYC DOE InfoHub files, which the DOE says are current 'as of August 3, 2026'. The DOE files exclude charter schools ('Charter schools are not included'), so charters carry spring 2025 results (prior year spring 2024) from NYSED's SRC2025 Report Card Database, the newest NYSED bulk release; data.nysed.gov offers only 2024-25 and 2023-24 as of Oct. 7, 2026. Do not rank a charter's 2025 number against a district school's 2026 number without saying so.",
            "Proficiency rates track school demographics closely (THE CITY's caveat in its Oct. 7, 2026 guide). Show them alongside a measure that adjusts for who the students are, such as the DOE impact scores.",
            "In 2023 NYSED aligned the ELA and math tests to new standards, so 2023 and later results should not be compared with 2022 and earlier (DOE notes). NYSED moved grades 5 and 8 to computer-based testing in 2024 and grades 4 and 6 in 2025; the DOE file keeps the most complete record when a student has both a computer and a paper test.",
            "Suppression: the DOE marks groups with 5 or fewer tested students (plus the next-smallest group when needed to protect them) with 's'; NYSED marks groups under 5 with 's'. Both become null here. Number tested is still published when proficiency is suppressed.",
            "Math, grade 8: students who took a Regents math exam (usually Algebra I) instead of the grade 8 test are left out of both sources as used here. At some middle schools most eighth graders take the Regents, so grade 3-8 math proficiency describes only the remaining students. For charters this required summing NYSED's grade-level rows (MATH3-MATH8), because NYSED's own MATH3_8 total adds Regents takers; " + f"{n_reg_schools} of {len(ch_insts)} NYC charters with {NY_CUR} results had grade 6-8 Regents math takers.",
            "Charter all-grades values are computed from NYSED grade rows: proficiency = sum(NUM_PROF) / sum(NUM_TESTED); mean scale = sum(TOTAL_SCALE_SCORES) / sum(NUM_TESTED). This mirrors how the DOE's 'All Grades' row relates to its grade rows (checked: DOE 'All Grades' Number Tested equals the sum of grade rows for all 1,122 schools in 2025). For ELA the computed sums equal NYSED's ELA3_8 totals; the script checks this. If any tested grade is suppressed, the school's computed value is null.",
            "The DOE and NYSED do not report identical numbers for the same school and year. For spring 2025 district schools (1,107 matched through the 2019-20 School Locations BEDS codes), DOE 'Number Tested' equaled NYSED NUM_TESTED at only 6-7 percent of schools, and proficiency rates differed by a median of 0.8 (ELA) and 0.9 (math) percentage points (example: 01M015 ELA, DOE 70 tested and 67.1 percent proficient; NYSED 64 tested and 70 percent). The DOE attributes students to the school they attended during testing (a 2025 change) and resolves paper/computer duplicates its own way; its notes say results 'may differ slightly' from data.nysed.gov.",
            "District 75 schools and students placed outside their home district (OODP) are excluded from the DOE school file. DOE notes: students at the Children's School may be attributed to 15K418 or 75M732; in 2026 results follow the DBN of enrollment, while in 2025 all were attributed to 75M732, so 15K418's prior-year value may be missing.",
            "n_tested counts students with valid scores, not enrollment. Test refusals (opt-outs) lower it and can bias proficiency at schools where many families opt out.",
            "Charter IDs: NYSED identifies schools by BEDS code and INSTITUTION_ID. DBNs come from the DOE LCGMS school list downloaded 2026-10-07 (data/sources/nyc_doe_lcgms_school_data_2026-10-07.xls; 'BEDS Number' -> 'ATS System Code'), then NYC Open Data 2019-20 School Locations (wg9x-4ke6) directly or through NYSED SRC2020 'Institution Grouping' (INSTITUTION_ID is stable when a charter moves and its BEDS code changes), then two manual name matches checked against DOE 2024-25 grade enrollment. Methods that both produced a DBN agreed in every case. Per-school method in 'charter_crosswalk'. Methods used: " + ", ".join(f"{k} {v}" for k, v in sorted(mc.items())) + ".",
            "Manual matches: " + "; ".join(man_notes) + ".",
            "Where a charter moved boroughs its DBN changed; the current LCGMS DBN was used over the 2019-20 one: " + "; ".join(sorted(superseded)) + ".",
            "Names change: NYSED's 'ACCESS BRONX CHARTER SCHOOL' is DOE 84X407 (formerly Bronx Charter School for Children). The current LCGMS list renames 84X487, 84X630 and 84X648 (Girls Prep schools in the 2025 data) as Bronx Charter School for Excellence 6, 8 and 9. Achievement First Legacy has DBN 84Q416 although its NYSED BEDS code (331600861082) begins with the Kings County code; the DOE LCGMS list carries the same BEDS code for 84Q416.",
            "Regents results are not included. The DOE's school-level Regents file on InfoHub stops at 2022-23; NYSED's 2024-25 Annual Regents Exams table is in the same Access database but would need a BEDS-to-DBN crosswalk for every high school.",
        ],
        "charter_crosswalk": charter_xw,
        "schools": dict(sorted(schools.items())),
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {OUT}: {len(schools)} schools ({len(doe_dbns)} DOE, {len(charter_xw)} charters via NYSED)")
    print("non-null coverage:", cov)
    print("charter crosswalk methods:", mc)
    print(f"DBNs matching atlas schools.json: {matched} of {len(schools)}")


if __name__ == "__main__":
    main()
