#!/usr/bin/env python3
"""Build data/metrics/class_size.json from two DOE class-size releases.

Raw files (unmodified downloads, in data/sources/):

  1. nyc_doe_class_size_school_2025-26_june.xlsx
     DOE Class Size Report (Local Law 522 / City Council), June 2025-26, "School Data".
     https://infohub.nyced.org/docs/default-source/default-document-library/june-2025-26-class-size---school.xlsx
     Sheets used: "K-5 Average", "MS HS Average", "PTR". Snapshot as of 6/15/26.

  2. nyc_doe_class_size_caps_211d_table_c_2025-26_asof_2025-10-31.xlsx
     Table C of DOE's Nov. 15, 2025 Annual Report on Implementation of New York
     State's Class Size Caps (Education Law 211-d). Linked from the report PDF
     (summary-report-11-15-25-final.pdf) on the class-size page; hosted on Google Drive:
     https://docs.google.com/spreadsheets/d/1dmTCm3nf07Gede2drkzqOLkY6tC8TsuI
     Sheets used: "25-26 K-5 by DBN & Grade", "25-26 6-12 by DBN & Course". Data as of 10/31/25.

How averages are computed (same formula DOE uses for every row of the file:
"dividing the number of students ... by the number of ... classes"):

    average = sum("Number of Students") / sum("Number of Classes")

over the rows in scope for that school. This is the size of the average class,
not the average of row averages. Applied to the whole file it reproduces DOE's
published citywide June 2025-26 numbers (overall 23.5; K-5 Gen Ed 20.0, ICT 20.4,
G&T 24.2; MS Gen Ed 23.8, ICT 24.2, Accelerated 26.2; HS Gen Ed 23.4, ICT 24.6),
which this script checks before writing.

Cap compliance follows Table C's own definition: "the total number of non-exempt
classes at or below the cap out of the total number of non-exempt classes",
summed across a school's K-5 grade rows and 6-12 course rows. Applied citywide
it reproduces DOE's 64% (checked below).
"""
import json
import math
import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC_JUNE = os.path.join(ROOT, "data", "sources", "nyc_doe_class_size_school_2025-26_june.xlsx")
SRC_CAPS = os.path.join(ROOT, "data", "sources", "nyc_doe_class_size_caps_211d_table_c_2025-26_asof_2025-10-31.xlsx")
OUT = os.path.join(ROOT, "data", "metrics", "class_size.json")

DBN_RE = re.compile(r"^[0-9]{2}[MXKQR][0-9]{3}$")
CORE_DEPTS = ["English", "Math", "Science", "Social Studies"]

# Program types as they appear in the June file.
K5_GENED = {"Gen Ed"}
K5_ICT = {"ICT", "ICT & G&T"}           # DOE: "Combined ICT and G&T/Accelerated classes are included as ICT classes."
K5_GT = {"G&T"}
K5_SC_PREFIX = "SC "                     # SC 12:1:1, SC 12:1, SC 8:1:1, SC 6:1:1, SC 15:1, SC 12:1:4
MS_GENED = {"Gen Ed"}
MS_ICT = {"ICT", "ICT & Acc"}
MS_ACC = {"Accelerated"}
MS_SC = {"SC"}

EXPECTED = {
    "k5_rows": 9000,      # 10,122 in June 2025-26
    "mshs_rows": 30000,   # 32,899
    "ptr_rows": 1400,     # 1,533
    "caps_k5_rows": 4000, # 4,808
    "caps_612_rows": 20000,  # 21,843
    "schools": 1400,      # 1,533 DBNs in the June file (districts 1-32 only)
    "cap_schools": 1400,  # 1,533 DBNs in Table C
}


def need_rows(df, key, what):
    if len(df) < EXPECTED[key]:
        raise SystemExit(f"{what}: parsed {len(df)} rows, expected at least {EXPECTED[key]}")


def check_cols(df, cols, what):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise SystemExit(f"{what}: missing columns {missing}; got {list(df.columns)}")


def avg(df):
    c = int(df["Number of Classes"].sum())
    if c == 0:
        return None
    return float(df["Number of Students"].sum()) / c


def r1(x):
    return None if x is None else round(x, 1)


def main():
    # ---------- June 2025-26 school file ----------
    k5 = pd.read_excel(SRC_JUNE, sheet_name="K-5 Average", dtype={"DBN": str, "Grade Level": str})
    ms = pd.read_excel(SRC_JUNE, sheet_name="MS HS Average", dtype={"DBN": str})
    ptr = pd.read_excel(SRC_JUNE, sheet_name="PTR", dtype={"DBN": str})
    check_cols(k5, ["DBN", "Grade Level", "Program Type", "Number of Students", "Number of Classes", "Average Class Size"], "K-5 Average")
    check_cols(ms, ["DBN", "Grade Band", "Program Type", "Department", "Subject", "Number of Students", "Number of Classes", "Average Class Size"], "MS HS Average")
    check_cols(ptr, ["DBN", "School Pupil-Teacher Ratio"], "PTR")
    need_rows(k5, "k5_rows", "K-5 Average")
    need_rows(ms, "mshs_rows", "MS HS Average")
    need_rows(ptr, "ptr_rows", "PTR")

    for name, df in (("K-5 Average", k5), ("MS HS Average", ms), ("PTR", ptr)):
        df["DBN"] = df["DBN"].str.strip().str.upper()
        bad = [d for d in df["DBN"].unique() if not DBN_RE.match(str(d))]
        if bad:
            raise SystemExit(f"{name}: unexpected DBN values {bad[:10]}")
    for name, df in (("K-5 Average", k5), ("MS HS Average", ms)):
        for c in ["Number of Students", "Number of Classes"]:
            if not pd.api.types.is_integer_dtype(df[c]):
                raise SystemExit(f"{name}: column {c} is not all integers (suppression?)")
        # The file's own row average must equal students/classes.
        diff = (df["Average Class Size"] - df["Number of Students"] / df["Number of Classes"]).abs().max()
        if diff > 1e-3:
            raise SystemExit(f"{name}: Average Class Size != students/classes (max diff {diff})")

    known = K5_GENED | K5_ICT | K5_GT
    odd = [p for p in k5["Program Type"].unique() if p not in known and not str(p).startswith(K5_SC_PREFIX)]
    if odd:
        raise SystemExit(f"K-5: unknown program types {odd}")
    odd = [p for p in ms["Program Type"].unique() if p not in (MS_GENED | MS_ICT | MS_ACC | MS_SC)]
    if odd:
        raise SystemExit(f"MS HS: unknown program types {odd}")

    k5_sc = k5["Program Type"].str.startswith(K5_SC_PREFIX)
    ms_sc = ms["Program Type"].isin(MS_SC)

    # ---- citywide reproduction check against DOE's June 2025-26 summary PDF ----
    def cw(df):
        return round(avg(df), 1)
    checks = [
        ("overall (non-SC)", cw(pd.concat([k5[~k5_sc], ms[~ms_sc]])), 23.5),
        ("K-5 Gen Ed", cw(k5[k5["Program Type"].isin(K5_GENED)]), 20.0),
        ("K-5 ICT", cw(k5[k5["Program Type"].isin(K5_ICT)]), 20.4),
        ("K-5 G&T", cw(k5[k5["Program Type"].isin(K5_GT)]), 24.2),
        ("MS Gen Ed", cw(ms[(ms["Grade Band"] == "MS") & ms["Program Type"].isin(MS_GENED)]), 23.8),
        ("MS ICT", cw(ms[(ms["Grade Band"] == "MS") & ms["Program Type"].isin(MS_ICT)]), 24.2),
        ("MS Accelerated", cw(ms[(ms["Grade Band"] == "MS") & ms["Program Type"].isin(MS_ACC)]), 26.2),
        ("HS Gen Ed", cw(ms[(ms["Grade Band"] == "HS") & ms["Program Type"].isin(MS_GENED)]), 23.4),
        ("HS ICT", cw(ms[(ms["Grade Band"] == "HS") & ms["Program Type"].isin(MS_ICT)]), 24.6),
        ("MS courses (non-SC)", cw(ms[(ms["Grade Band"] == "MS") & ~ms_sc]), 24.0),
        ("HS courses (non-SC)", cw(ms[(ms["Grade Band"] == "HS") & ~ms_sc]), 23.7),
    ]
    for label, got, want in checks:
        if abs(got - want) > 0.05:
            raise SystemExit(f"Citywide check failed for {label}: computed {got}, DOE summary says {want}")

    schools = {}
    dbns = sorted(set(k5["DBN"]) | set(ms["DBN"]) | set(ptr["DBN"]))
    if len(dbns) < EXPECTED["schools"]:
        raise SystemExit(f"Only {len(dbns)} schools in June file; expected >= {EXPECTED['schools']}")
    k5_by = dict(tuple(k5.groupby("DBN")))
    ms_by = dict(tuple(ms.groupby("DBN")))
    empty_k5 = k5.iloc[0:0]
    empty_ms = ms.iloc[0:0]
    ptr_map = {}
    for d, v in zip(ptr["DBN"], ptr["School Pupil-Teacher Ratio"]):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            ptr_map[d] = None
        elif isinstance(v, (int, float)):
            ptr_map[d] = round(float(v), 1)
        else:
            raise SystemExit(f"PTR: non-numeric value {v!r} for {d}")

    for d in dbns:
        a = k5_by.get(d, empty_k5)
        b = ms_by.get(d, empty_ms)
        a_sc = a["Program Type"].str.startswith(K5_SC_PREFIX)
        b_sc = b["Program Type"].isin(MS_SC)
        b_core = b["Department"].isin(CORE_DEPTS)
        rec = {
            "avg_class_size_overall": r1(avg(pd.concat([a[~a_sc], b[~b_sc]]))),
            "avg_class_size_k5": r1(avg(a[~a_sc])),
            "avg_class_size_mshs": r1(avg(b[~b_sc & b_core])),
            "avg_class_size_gened": r1(avg(pd.concat([a[a["Program Type"].isin(K5_GENED)], b[b["Program Type"].isin(MS_GENED)]]))),
            "avg_class_size_ict": r1(avg(pd.concat([a[a["Program Type"].isin(K5_ICT)], b[b["Program Type"].isin(MS_ICT)]]))),
            "avg_class_size_special": r1(avg(pd.concat([a[a_sc], b[b_sc]]))),
            "n_classes": int(a["Number of Classes"].sum() + b["Number of Classes"].sum()),
            "pupil_teacher_ratio": ptr_map.get(d),
        }
        schools[d] = rec

    # ---------- Table C: state cap compliance, as of 10/31/25 ----------
    ck5 = pd.read_excel(SRC_CAPS, sheet_name="25-26 K-5 by DBN & Grade", dtype={"DBN": str, "Grade Level": str})
    c612 = pd.read_excel(SRC_CAPS, sheet_name="25-26 6-12 by DBN & Course", dtype={"DBN": str})
    cap_cols = ["DBN", "Total # of classes", "Total # of exempted classes", "Total # of non-exempted classes",
                "Total # of non-exempted classes at or below cap", "Total # of non-exempted classes over cap",
                "Exemption Category, if eligible"]
    check_cols(ck5, cap_cols, "Table C K-5")
    check_cols(c612, cap_cols, "Table C 6-12")
    need_rows(ck5, "caps_k5_rows", "Table C K-5")
    need_rows(c612, "caps_612_rows", "Table C 6-12")
    caps = pd.concat([ck5[cap_cols], c612[cap_cols]], ignore_index=True)
    caps["DBN"] = caps["DBN"].str.strip().str.upper()
    bad = [d for d in caps["DBN"].unique() if not DBN_RE.match(str(d))]
    if bad:
        raise SystemExit(f"Table C: unexpected DBN values {bad[:10]}")
    numcols = cap_cols[1:6]
    for c in numcols:
        if not pd.api.types.is_integer_dtype(caps[c]):
            raise SystemExit(f"Table C: column {c} is not all integers")
    # Internal consistency: total = exempt + non-exempt; non-exempt = at/below + over.
    if not (caps["Total # of classes"] == caps["Total # of exempted classes"] + caps["Total # of non-exempted classes"]).all():
        raise SystemExit("Table C: total != exempt + non-exempt on some rows")
    if not (caps["Total # of non-exempted classes"] == caps["Total # of non-exempted classes at or below cap"] + caps["Total # of non-exempted classes over cap"]).all():
        raise SystemExit("Table C: non-exempt != at/below + over on some rows")
    city = caps["Total # of non-exempted classes at or below cap"].sum() / caps["Total # of non-exempted classes"].sum()
    if round(city * 100) != 64:
        raise SystemExit(f"Table C citywide compliance {city:.4f} does not reproduce DOE's 64%")

    g = caps.groupby("DBN")
    sums = g[numcols].sum()
    if len(sums) < EXPECTED["cap_schools"]:
        raise SystemExit(f"Table C: only {len(sums)} schools; expected >= {EXPECTED['cap_schools']}")
    exc = g["Exemption Category, if eligible"].agg(
        lambda s: "; ".join(sorted({str(x).strip() for x in s if isinstance(x, str) and x.strip()})) or None)
    for d, row in sums.iterrows():
        ne = int(row["Total # of non-exempted classes"])
        ok = int(row["Total # of non-exempted classes at or below cap"])
        rec = schools.setdefault(d, {
            "avg_class_size_overall": None, "avg_class_size_k5": None, "avg_class_size_mshs": None,
            "avg_class_size_gened": None, "avg_class_size_ict": None, "avg_class_size_special": None,
            "n_classes": None, "pupil_teacher_ratio": None,
        })
        rec["cap_pct_at_or_below"] = round(ok / ne, 4) if ne > 0 else None
        rec["cap_n_nonexempt_classes"] = ne
        rec["cap_n_over"] = int(row["Total # of non-exempted classes over cap"])
        rec["cap_n_exempt_classes"] = int(row["Total # of exempted classes"])
        rec["cap_exemption"] = exc.get(d)
    for d, rec in schools.items():
        for k in ("cap_pct_at_or_below", "cap_n_nonexempt_classes", "cap_n_over", "cap_n_exempt_classes", "cap_exemption"):
            rec.setdefault(k, None)

    fields = {
        "avg_class_size_overall": {
            "label": "Average class size",
            "definition": "Average number of students per class across the school's general education, ICT, G&T and accelerated classes (K-5 official classes plus every 6-12 course section, all subjects), as of 6/15/26. Self-contained special classes are left out, as in DOE's own 'overall' averages. Computed by this script as total students / total classes over those rows; the same formula on the whole file reproduces DOE's citywide 23.5.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheets 'K-5 Average' and 'MS HS Average', rows where 'Program Type' is not self-contained (K-5: not 'SC ...'; MS HS: not 'SC')",
            "unit": "number", "direction": "lower"},
        "avg_class_size_k5": {
            "label": "Avg. class size, K-5",
            "definition": "Average students per K-5 official class (general ed, ICT, G&T, and ICT & G&T), as of 6/15/26. DOE: K-5 average class size divides 'the number of students as of 6/15 by the number of classes as determined by each student's official class' in ATS. Self-contained classes excluded (see avg_class_size_special). Includes bridge classes and a handful of grade 6 official classes that DOE puts on the K-5 sheet. Computed as total students / total classes.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheet 'K-5 Average', 'Program Type' in {Gen Ed, ICT, G&T, ICT & G&T}",
            "unit": "number", "direction": "lower"},
        "avg_class_size_mshs": {
            "label": "Avg. class size, 6-12 core subjects",
            "definition": "Average students per class in grades 6-12 English, math, science and social studies course sections (general ed, ICT, accelerated, ICT & accelerated), spring 2026 term as of 6/15/26. DOE defines a class as 'students meeting at the same time ... in the same place.' Self-contained excluded. Computed as total students / total classes over those departments.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheet 'MS HS Average', 'Department' in {English, Math, Science, Social Studies}, 'Program Type' != 'SC'",
            "unit": "number", "direction": "lower"},
        "avg_class_size_gened": {
            "label": "Avg. general ed class",
            "definition": "Average students per general education class (program type 'Gen Ed'), K-5 official classes plus all 6-12 course sections, all subjects, as of 6/15/26. Computed as total students / total classes.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheets 'K-5 Average' and 'MS HS Average', 'Program Type' = 'Gen Ed'",
            "unit": "number", "direction": "lower"},
        "avg_class_size_ict": {
            "label": "Avg. ICT class",
            "definition": "Average students per Integrated Co-Teaching class (a general and a special education teacher together), K-5 official classes plus all 6-12 course sections, as of 6/15/26. Following DOE, combined ICT & G&T and ICT & accelerated classes count as ICT. Computed as total students / total classes.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheets 'K-5 Average' ('Program Type' in {ICT, ICT & G&T}) and 'MS HS Average' ('Program Type' in {ICT, ICT & Acc})",
            "unit": "number", "direction": "lower"},
        "avg_class_size_special": {
            "label": "Avg. self-contained special class",
            "definition": "Average students per self-contained special education class (K-5/K-8 settings 12:1:1, 12:1, 8:1:1, 6:1:1, 15:1, 12:1:4, plus 6-12 'SC' course sections), as of 6/15/26. These sizes are set by students' IEP settings and are not covered by the state caps. Null means the school reported no self-contained classes. Computed as total students / total classes.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheets 'K-5 Average' ('Program Type' starting 'SC ') and 'MS HS Average' ('Program Type' = 'SC')",
            "unit": "number", "direction": "neutral"},
        "n_classes": {
            "label": "Classes counted",
            "definition": "Number of classes in the June report for this school, all program types: K-5 official classes plus 6-12 course sections in every subject (a high school class is one section of one course, so this is far larger than the number of homerooms).",
            "source_field": "sum('Number of Classes'), sheets 'K-5 Average' and 'MS HS Average', all rows",
            "unit": "count", "direction": "neutral"},
        "pupil_teacher_ratio": {
            "label": "Pupil-teacher ratio",
            "definition": "DOE's school pupil-teacher ratio (students per teacher) from the June 2025-26 report, rounded to one decimal. DOE's June summary puts the all-schools figure at 11.6 (11.5 in the Nov. 2025 state report). Neither the file nor the methodology says which staff count as teachers or which enrollment date is used. It is not a class-size measure: citywide the June ratio is 11.6 while the average class is 23.5.",
            "source_field": "'School Pupil-Teacher Ratio', sheet 'PTR'",
            "unit": "ratio", "direction": "neutral"},
        "cap_pct_at_or_below": {
            "label": "Classes within state cap",
            "definition": "Share of the school's non-exempt classes at or below the state class-size caps (K-3: 20, grades 4-8: 23, grades 9-12: 25, 6-12 PE and performing groups: 40), as of 10/31/25. DOE's definition: 'the total number of non-exempt classes at or below the cap out of the total number of non-exempt classes.' Excludes self-contained classes, District 75/79/88 schools and charters. Computed by summing Table C's K-5 grade rows and 6-12 course rows for the school; the same sum citywide gives DOE's 64%.",
            "source_field": "sum('Total # of non-exempted classes at or below cap') / sum('Total # of non-exempted classes'), Table C sheets '25-26 K-5 by DBN & Grade' and '25-26 6-12 by DBN & Course'",
            "unit": "pct", "direction": "higher"},
        "cap_n_nonexempt_classes": {
            "label": "Classes subject to cap",
            "definition": "Number of non-exempt classes counted for the state cap, as of 10/31/25 (the denominator of cap_pct_at_or_below).",
            "source_field": "sum('Total # of non-exempted classes'), Table C 2025-26 sheets",
            "unit": "count", "direction": "neutral"},
        "cap_n_over": {
            "label": "Classes over cap",
            "definition": "Number of non-exempt classes above the state cap, as of 10/31/25.",
            "source_field": "sum('Total # of non-exempted classes over cap'), Table C 2025-26 sheets",
            "unit": "count", "direction": "lower"},
        "cap_n_exempt_classes": {
            "label": "Exempted classes",
            "definition": "Classes exempted from the cap for 2025-26. DOE: exemptions 'were determined in collaboration with the United Federation of Teachers (UFT) and the Council for School Supervisors and Administrators (CSA), in alignment with the law, and granted to schools meeting criteria outlined within the July 2025 Class Size Reduction Plan.'",
            "source_field": "sum('Total # of exempted classes'), Table C 2025-26 sheets",
            "unit": "count", "direction": "neutral"},
        "cap_exemption": {
            "label": "Exemption category",
            "definition": "Exemption category or categories DOE lists for the school's exempted classes ('Space - Capital Plan: 7', 'Space - Capital Plan: 8', 'Space - Capital Plan: 7,8', 'Overenrolled'), joined with '; ' when a school has more than one. Null if none.",
            "source_field": "'Exemption Category, if eligible', Table C 2025-26 sheets",
            "unit": "text", "direction": "neutral"},
    }

    cover = {k: sum(1 for r in schools.values() if r.get(k) is not None) for k in fields}

    out = {
        "key": "class_size",
        "title": "Class size, 2025-26",
        "source": "NYC Department of Education: Class Size Report (Local Law 522), June 2025-26, School Data; and Table C of the Nov. 15, 2025 Annual Report on Implementation of New York State's Class Size Caps (Education Law 211-d)",
        "source_url": "https://infohub.nyced.org/reports/government-reports/class-size-reports",
        "file_url": "https://infohub.nyced.org/docs/default-source/default-document-library/june-2025-26-class-size---school.xlsx",
        "other_file_urls": [
            "https://docs.google.com/spreadsheets/d/1dmTCm3nf07Gede2drkzqOLkY6tC8TsuI (Table C; linked from https://infohub.nyced.org/docs/default-source/default-document-library/summary-report-11-15-25-final.pdf)",
            "https://infohub.nyced.org/docs/default-source/default-document-library/june-class-size-reporting-methodology---web.pdf",
            "https://infohub.nyced.org/docs/default-source/default-document-library/2025-26-june-average-class-size-summary.pdf",
        ],
        "vintage": "2025-26 June report (data as of 6/15/26); cap_* fields from the Nov. 15, 2025 state report (data as of 10/31/25)",
        "fetched": "2026-10-07",
        "fields": fields,
        "notes": [
            "Two vintages. The average-size fields and n_classes come from DOE's June 2025-26 report, a 6/15/26 snapshot (K-5 from ATS; grades 6-12 from the last term in STARS). The cap_* fields come from the state-law report, which counts classes as of 10/31/25. DOE publishes school-level cap compliance only in that November report, not in the June file.",
            "DOE also posted November and February 2025-26 school files (both 10/31/25 snapshots). The June file is the newest; the next release is the November 2026 report on 2026-27.",
            "Averages are computed by this script as total students / total classes over the rows named in each field's source_field. That is DOE's own row formula ('dividing the number of students ... by the number of ... classes'), and run on the whole file it reproduces every citywide figure in DOE's June summary (overall 23.5; K-5 Gen Ed 20.0, ICT 20.4, G&T 24.2; MS Gen Ed 23.8, ICT 24.2, accelerated 26.2; HS Gen Ed 23.4, ICT 24.6). The build stops if any check fails.",
            "Self-contained classes are kept out of avg_class_size_overall, _k5 and _mshs, as in DOE's overall averages, because their size is set by IEP ratios (12:1:1 and so on). They are reported on their own in avg_class_size_special. n_classes counts every program type.",
            "G&T and accelerated classes count toward avg_class_size_overall, _k5 and _mshs but have no field of their own. Following DOE, combined ICT & G&T and ICT & accelerated classes count as ICT.",
            "Since 2023-24 DOE counts bridge classes, non-core 6-12 courses (arts, PE), labs, D75 inclusion students and shared-instruction classes, and defines a 6-12 class as students meeting at the same time in the same place. DOE says these changes 'resulted in higher average class sizes,' so figures before 2023-24 are not comparable.",
            "DOE drops outliers: general education and ICT classes with more than 100 or fewer than 5 students, and self-contained classes with fewer than 2.",
            "Suppression: none in the columns used. 'Number of Students', 'Number of Classes' and 'Average Class Size' are fully populated. Only 'Minimum Class Size' and 'Maximum Class Size' (and the 'Class Size' column on the Counts sheets) mask small values as '<15'; none of those are used.",
            "A null average means the school had no classes in that category (for example avg_class_size_mshs for an elementary school, or avg_class_size_special at a school with no self-contained classes). Nothing was suppressed.",
            "cap_pct_at_or_below sums Table C's grade rows (K-5) and course rows (6-12). Citywide that gives 89,749 of 140,209 non-exempt classes = 64.0%, matching DOE's reported 64%. Table C leaves out self-contained classes, so a school's cap counts cover only its general ed, ICT, G&T and accelerated classes. One school (15K107) had every class exempted, so its cap_pct_at_or_below is null with cap_n_nonexempt_classes = 0.",
            "Read cap_pct_at_or_below next to cap_n_exempt_classes. Exempted classes drop out of both numerator and denominator, so a heavily exempted school can show a perfect score. Stuyvesant (02M475) had 699 of its 806 classes exempted as 'Overenrolled'; its other 107 were all within the cap, so it shows 100% while its June average class was 32.7. 122 schools have at least one exempted class. One more, 27Q051, carries an exemption category ('Space - Capital Plan: 7,8') but zero exempted classes; the category is stored as listed.",
            "Caps: K-3 20, grades 4-8 23, grades 9-12 25, 6-12 PE and performing-group classes 40. The law required 60% of classes at or below the caps in 2025-26; DOE says it reached 64%.",
            "Coverage: 1,533 schools, all in community school districts 1-32. Both files hold the same 1,533 DBNs. Neither includes District 75 (citywide special education), District 79 (alternative) or District 88 schools, or charter schools, so those schools get no record here.",
            "pupil_teacher_ratio comes from the June file. Table C also carries a 10/31/25 ratio, which is not used.",
        ],
        "schools": dict(sorted(schools.items())),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {OUT}: {len(schools)} schools")
    for k, v in cover.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
