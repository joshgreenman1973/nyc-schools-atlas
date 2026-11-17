#!/usr/bin/env python3
"""Build data/metrics/class_size.json from two DOE class-size releases, both
for 2026-27 and both counting classes as of Oct. 31, 2026.

Raw files (unmodified downloads, in data/sources/):

  1. nyc_doe_class_size_school_2026-27_november.xlsx
     DOE Class Size Report (City Council), November 2026-27, "School Data".
     https://infohub.nyced.org/docs/default-source/default-document-library/november-2026-27-class-size---school.xlsx
     Sheets used: "K-5 Average", "MS HS Average". Snapshot as of 10/31/26.
     Companion files: nyc_doe_class_size_summary_2026-27_november.pdf
     (2026-27-average-class-size-summary---november.pdf) and
     nyc_doe_class_size_methodology_2026-27.pdf
     (2026-27-class-size-reporting-methodology---web.pdf).

  2. nyc_doe_class_size_caps_211d_table_c_2026-27_asof_2026-10-31.xlsx
     Table C of DOE's Nov. 15, 2026 Annual Report on Implementation of New York
     State's Class Size Caps (Education Law 211-d).
     https://infohub.nyced.org/docs/default-source/default-document-library/fy27---table-c---2026-27-class-size-compliance-by-school.xlsx
     Report: nyc_doe_class_size_caps_211d_annual_report_2026-11-15.pdf
     (https://infohub.nyced.org/docs/default-source/default-document-library/annual-report-on-implementation.pdf)
     Sheets used: "26-27 K-5 by DBN & Grade", "26-27 6-12 by DBN & Course",
     "26-27 Pupil-to-Teacher Ratio". Data as of 10/31/26.

How averages are computed (same formula DOE uses for every row of the file:
"dividing the number of students ... by the number of ... classes"):

    average = sum("Number of Students") / sum("Number of Classes")

over the rows in scope for that school. This is the size of the average class,
not the average of row averages. Applied to the whole file it reproduces DOE's
published citywide November 2026-27 numbers (all schools 21.4, including K-5
cluster classes; K-5 Gen Ed 19.1, ICT 19.5, G&T 23.9, cluster 19.0; MS Gen Ed
22.2, ICT 23.3, accelerated 25.3; HS Gen Ed 22.9, ICT 24.1), which this script
checks before writing.

Cap compliance follows Table C: classes at or below the cap out of all classes
counted, summed across a school's K-5 grade/subject rows and 6-12 course rows.
DOE granted no exemptions for 2026-27 ("NYCPS did not utilize exemptions in
2026-27", Table C notes), so every counted class is in the share. Applied
citywide it reproduces DOE's 73.4% (checked below).
"""
import json
import math
import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC_NOV = os.path.join(ROOT, "data", "sources", "nyc_doe_class_size_school_2026-27_november.xlsx")
SRC_CAPS = os.path.join(ROOT, "data", "sources", "nyc_doe_class_size_caps_211d_table_c_2026-27_asof_2026-10-31.xlsx")
OUT = os.path.join(ROOT, "data", "metrics", "class_size.json")

DBN_RE = re.compile(r"^[0-9]{2}[MXKQR][0-9]{3}$")
CORE_DEPTS = ["English", "Math", "Science", "Social Studies"]

# Program types as they appear in the November 2026-27 file.
K5_GENED = {"Gen Ed"}
K5_ICT = {"ICT", "ICT & G&T"}           # DOE: "Combined ICT and G&T/Accelerated classes are included as ICT classes."
K5_GT = {"G&T"}
K5_SC_PREFIX = "SC "                     # SC 12:1:1, SC 12:1, SC 8:1:1, SC 6:1:1, SC 15:1, SC 12:1:4
K5_CLUSTER = "K-5 Cluster"               # new in 2026-27: gym, art, music and other cluster subjects
K5_CLUSTER_SC = "K-5 Cluster - SC"       # cluster classes for self-contained students
MS_GENED = {"Gen Ed"}
MS_ICT = {"ICT", "ICT & Acc"}
MS_ACC = {"Accelerated"}
MS_SC = {"SC"}

EXPECTED = {
    "k5_rows": 30000,     # 37,856 in November 2026-27 (official classes plus cluster subjects)
    "mshs_rows": 30000,   # 33,368
    "caps_k5_rows": 25000,   # 30,706
    "caps_612_rows": 20000,  # 22,597
    "ptr_rows": 1400,     # 1,531
    "schools": 1400,      # 1,531 DBNs in the November file (districts 1-32 only)
    "cap_schools": 1400,  # 1,531 DBNs in Table C
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
    # ---------- November 2026-27 school file ----------
    k5 = pd.read_excel(SRC_NOV, sheet_name="K-5 Average", dtype={"DBN": str, "Grade Level": str})
    ms = pd.read_excel(SRC_NOV, sheet_name="MS HS Average", dtype={"DBN": str})
    check_cols(k5, ["DBN", "Grade Level", "Program Type", "Subject", "Number of Students", "Number of Classes", "Average Class Size"], "K-5 Average")
    check_cols(ms, ["DBN", "Grade Band", "Program Type", "Department", "Subject", "Number of Students", "Number of Classes", "Average Class Size"], "MS HS Average")
    need_rows(k5, "k5_rows", "K-5 Average")
    need_rows(ms, "mshs_rows", "MS HS Average")

    for name, df in (("K-5 Average", k5), ("MS HS Average", ms)):
        df["DBN"] = df["DBN"].str.strip().str.upper()
        bad = [d for d in df["DBN"].unique() if not DBN_RE.match(str(d))]
        if bad:
            raise SystemExit(f"{name}: unexpected DBN values {bad[:10]}")
        for c in ["Number of Students", "Number of Classes"]:
            if not pd.api.types.is_integer_dtype(df[c]):
                raise SystemExit(f"{name}: column {c} is not all integers (suppression?)")
        # The file's own row average must equal students/classes.
        diff = (df["Average Class Size"] - df["Number of Students"] / df["Number of Classes"]).abs().max()
        if diff > 1e-3:
            raise SystemExit(f"{name}: Average Class Size != students/classes (max diff {diff})")

    known = K5_GENED | K5_ICT | K5_GT | {K5_CLUSTER, K5_CLUSTER_SC}
    odd = [p for p in k5["Program Type"].unique() if p not in known and not str(p).startswith(K5_SC_PREFIX)]
    if odd:
        raise SystemExit(f"K-5: unknown program types {odd}")
    odd = [p for p in ms["Program Type"].unique() if p not in (MS_GENED | MS_ICT | MS_ACC | MS_SC)]
    if odd:
        raise SystemExit(f"MS HS: unknown program types {odd}")

    k5_cluster = k5["Program Type"] == K5_CLUSTER
    k5_cluster_sc = k5["Program Type"] == K5_CLUSTER_SC
    k5_official = ~(k5_cluster | k5_cluster_sc)
    if not (k5.loc[k5_official, "Subject"] == "Official Class").all():
        raise SystemExit("K-5: a non-cluster row is not an official class")
    if (k5.loc[~k5_official, "Subject"] == "Official Class").any():
        raise SystemExit("K-5: a cluster row is labeled as an official class")
    k5_sc = k5_official & k5["Program Type"].str.startswith(K5_SC_PREFIX)
    k5_reg = k5_official & ~k5_sc          # general ed, ICT, G&T official classes
    ms_sc = ms["Program Type"].isin(MS_SC)

    # ---- citywide reproduction check against DOE's November 2026-27 summary PDF ----
    def cw(df):
        return round(avg(df), 1)
    k5o = k5[k5_official]
    checks = [
        ("all schools (incl. K-5 cluster, no SC)", cw(pd.concat([k5[k5_reg | k5_cluster], ms[~ms_sc]])), 21.4),
        ("K-5 Gen Ed", cw(k5o[k5o["Program Type"].isin(K5_GENED)]), 19.1),
        ("K-5 ICT", cw(k5o[k5o["Program Type"].isin(K5_ICT)]), 19.5),
        ("K-5 G&T", cw(k5o[k5o["Program Type"].isin(K5_GT)]), 23.9),
        ("K-5 cluster", cw(k5[k5_cluster]), 19.0),
        ("MS Gen Ed", cw(ms[(ms["Grade Band"] == "MS") & ms["Program Type"].isin(MS_GENED)]), 22.2),
        ("MS ICT", cw(ms[(ms["Grade Band"] == "MS") & ms["Program Type"].isin(MS_ICT)]), 23.3),
        ("MS Accelerated", cw(ms[(ms["Grade Band"] == "MS") & ms["Program Type"].isin(MS_ACC)]), 25.3),
        ("HS Gen Ed", cw(ms[(ms["Grade Band"] == "HS") & ms["Program Type"].isin(MS_GENED)]), 22.9),
        ("HS ICT", cw(ms[(ms["Grade Band"] == "HS") & ms["Program Type"].isin(MS_ICT)]), 24.1),
    ]
    for label, got, want in checks:
        if abs(got - want) > 0.05:
            raise SystemExit(f"Citywide check failed for {label}: computed {got}, DOE summary says {want}")

    # ---------- Table C: state cap compliance, as of 10/31/26 ----------
    ck5 = pd.read_excel(SRC_CAPS, sheet_name="26-27 K-5 by DBN & Grade", dtype={"DBN": str, "Grade Level": str})
    c612 = pd.read_excel(SRC_CAPS, sheet_name="26-27 6-12 by DBN & Course", dtype={"DBN": str})
    ptr = pd.read_excel(SRC_CAPS, sheet_name="26-27 Pupil-to-Teacher Ratio", dtype={"DBN": str})
    cap_cols = ["DBN", "Total # of classes", "Total # of classes at or below cap", "Total # of classes over cap"]
    check_cols(ck5, cap_cols, "Table C K-5")
    check_cols(c612, cap_cols, "Table C 6-12")
    check_cols(ptr, ["DBN", "School Pupil-Teacher Ratio"], "Table C PTR")
    for c in ("Total # of exempted classes", "Exemption Category, if eligible"):
        if c in ck5.columns or c in c612.columns:
            raise SystemExit(f"Table C 2026-27 now has {c!r}; DOE said it used no exemptions. Revisit the cap logic.")
    need_rows(ck5, "caps_k5_rows", "Table C K-5")
    need_rows(c612, "caps_612_rows", "Table C 6-12")
    need_rows(ptr, "ptr_rows", "Table C PTR")
    caps = pd.concat([ck5[cap_cols], c612[cap_cols]], ignore_index=True)
    caps["DBN"] = caps["DBN"].str.strip().str.upper()
    bad = [d for d in caps["DBN"].unique() if not DBN_RE.match(str(d))]
    if bad:
        raise SystemExit(f"Table C: unexpected DBN values {bad[:10]}")
    numcols = cap_cols[1:]
    for c in numcols:
        if not pd.api.types.is_integer_dtype(caps[c]):
            raise SystemExit(f"Table C: column {c} is not all integers")
    if not (caps["Total # of classes"] == caps["Total # of classes at or below cap"] + caps["Total # of classes over cap"]).all():
        raise SystemExit("Table C: total != at/below + over on some rows")
    city = caps["Total # of classes at or below cap"].sum() / caps["Total # of classes"].sum()
    if round(city * 100, 1) != 73.4:
        raise SystemExit(f"Table C citywide compliance {city:.4f} does not reproduce DOE's 73.4%")

    ptr["DBN"] = ptr["DBN"].str.strip().str.upper()
    ptr_map = {}
    for d, v in zip(ptr["DBN"], ptr["School Pupil-Teacher Ratio"]):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            ptr_map[d] = None
        elif isinstance(v, (int, float)):
            ptr_map[d] = round(float(v), 1)
        else:
            raise SystemExit(f"PTR: non-numeric value {v!r} for {d}")

    schools = {}
    dbns = sorted(set(k5["DBN"]) | set(ms["DBN"]))
    if len(dbns) < EXPECTED["schools"]:
        raise SystemExit(f"Only {len(dbns)} schools in November file; expected >= {EXPECTED['schools']}")
    k5_by = dict(tuple(k5.groupby("DBN")))
    ms_by = dict(tuple(ms.groupby("DBN")))
    empty_k5 = k5.iloc[0:0]
    empty_ms = ms.iloc[0:0]

    for d in dbns:
        a = k5_by.get(d, empty_k5)
        b = ms_by.get(d, empty_ms)
        a_clu = a["Program Type"] == K5_CLUSTER
        a_clu_sc = a["Program Type"] == K5_CLUSTER_SC
        a_off = ~(a_clu | a_clu_sc)
        a_sc = a_off & a["Program Type"].str.startswith(K5_SC_PREFIX)
        a_reg = a_off & ~a_sc
        b_sc = b["Program Type"].isin(MS_SC)
        b_core = b["Department"].isin(CORE_DEPTS)
        rec = {
            "avg_class_size_overall": r1(avg(pd.concat([a[a_reg | a_clu], b[~b_sc]]))),
            "avg_class_size_k5": r1(avg(a[a_reg])),
            "avg_class_size_k5_cluster": r1(avg(a[a_clu])),
            "avg_class_size_mshs": r1(avg(b[~b_sc & b_core])),
            "avg_class_size_gened": r1(avg(pd.concat([a[a["Program Type"].isin(K5_GENED)], b[b["Program Type"].isin(MS_GENED)]]))),
            "avg_class_size_ict": r1(avg(pd.concat([a[a["Program Type"].isin(K5_ICT)], b[b["Program Type"].isin(MS_ICT)]]))),
            "avg_class_size_special": r1(avg(pd.concat([a[a_sc], b[b_sc]]))),
            "n_classes": int(a["Number of Classes"].sum() + b["Number of Classes"].sum()),
            "pupil_teacher_ratio": ptr_map.get(d),
        }
        schools[d] = rec

    g = caps.groupby("DBN")
    sums = g[numcols].sum()
    if len(sums) < EXPECTED["cap_schools"]:
        raise SystemExit(f"Table C: only {len(sums)} schools; expected >= {EXPECTED['cap_schools']}")
    blank = {k: None for k in schools[dbns[0]]}
    for d, row in sums.iterrows():
        n = int(row["Total # of classes"])
        ok = int(row["Total # of classes at or below cap"])
        rec = schools.setdefault(d, dict(blank, pupil_teacher_ratio=ptr_map.get(d)))
        rec["cap_pct_at_or_below"] = round(ok / n, 4) if n > 0 else None
        rec["cap_n_classes"] = n
        rec["cap_n_over"] = int(row["Total # of classes over cap"])
    for d, rec in schools.items():
        for k in ("cap_pct_at_or_below", "cap_n_classes", "cap_n_over"):
            rec.setdefault(k, None)

    fields = {
        "avg_class_size_overall": {
            "label": "Average class size",
            "definition": "Average number of students per class across the school's general education, ICT, G&T and accelerated classes, as of 10/31/26: K-5 official classes, K-5 cluster classes (gym, art, music, science and other subjects taught by a cluster teacher, counted by DOE starting in 2026-27) and every 6-12 course section in all subjects. Self-contained special classes are left out, as in DOE's own averages. Computed by this script as total students / total classes over those rows; the same formula on the whole file reproduces DOE's citywide 21.4.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheets 'K-5 Average' (Program Type Gen Ed, ICT, G&T, ICT & G&T, K-5 Cluster) and 'MS HS Average' (Program Type not 'SC')",
            "unit": "number", "direction": "lower"},
        "avg_class_size_k5": {
            "label": "Avg. class size, K-5 official classes",
            "definition": "Average students per K-5 official class (the homeroom class where students get core instruction: general ed, ICT, G&T, and ICT & G&T), as of 10/31/26, from ATS. Cluster classes and self-contained classes are left out. Includes bridge classes and a handful of grade 6 official classes that DOE puts on the K-5 sheet. Computed as total students / total classes.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheet 'K-5 Average', 'Subject' = 'Official Class', 'Program Type' in {Gen Ed, ICT, G&T, ICT & G&T}",
            "unit": "number", "direction": "lower"},
        "avg_class_size_k5_cluster": {
            "label": "Avg. K-5 cluster class",
            "definition": "Average students per K-5 cluster class (a subject such as physical education, art, music, science or technology taught by a teacher who teaches it across several official classes), as of 10/31/26, from STARS. New in DOE's 2026-27 reports. Cluster classes for self-contained students are left out.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheet 'K-5 Average', 'Program Type' = 'K-5 Cluster'",
            "unit": "number", "direction": "lower"},
        "avg_class_size_mshs": {
            "label": "Avg. class size, 6-12 core subjects",
            "definition": "Average students per class in grades 6-12 English, math, science and social studies course sections (general ed, ICT, accelerated, ICT & accelerated), fall 2026 term as of 10/31/26. DOE defines a class as students 'meeting at the same time ... in the same place.' Self-contained excluded. Computed as total students / total classes over those departments.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheet 'MS HS Average', 'Department' in {English, Math, Science, Social Studies}, 'Program Type' != 'SC'",
            "unit": "number", "direction": "lower"},
        "avg_class_size_gened": {
            "label": "Avg. general ed class",
            "definition": "Average students per general education class (program type 'Gen Ed'), K-5 official classes plus all 6-12 course sections, all subjects, as of 10/31/26. K-5 cluster classes have no program type and are left out. Computed as total students / total classes.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheets 'K-5 Average' and 'MS HS Average', 'Program Type' = 'Gen Ed'",
            "unit": "number", "direction": "lower"},
        "avg_class_size_ict": {
            "label": "Avg. ICT class",
            "definition": "Average students per Integrated Co-Teaching class (a general and a special education teacher together), K-5 official classes plus all 6-12 course sections, as of 10/31/26. Following DOE, combined ICT & G&T and ICT & accelerated classes count as ICT. Computed as total students / total classes.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheets 'K-5 Average' ('Program Type' in {ICT, ICT & G&T}) and 'MS HS Average' ('Program Type' in {ICT, ICT & Acc})",
            "unit": "number", "direction": "lower"},
        "avg_class_size_special": {
            "label": "Avg. self-contained special class",
            "definition": "Average students per self-contained special education class (K-5/K-8 official classes in settings 12:1:1, 12:1, 8:1:1, 6:1:1, 15:1, 12:1:4, plus 6-12 'SC' course sections), as of 10/31/26. K-5 cluster classes for self-contained students are left out, as in DOE's summary. These sizes are set by students' IEP settings and are not covered by the state caps. Null means the school reported no self-contained classes. Computed as total students / total classes.",
            "source_field": "sum('Number of Students') / sum('Number of Classes'), sheets 'K-5 Average' ('Program Type' starting 'SC ') and 'MS HS Average' ('Program Type' = 'SC')",
            "unit": "number", "direction": "neutral"},
        "n_classes": {
            "label": "Classes counted",
            "definition": "Number of classes in the November report for this school, all program types: K-5 official and cluster classes plus 6-12 course sections in every subject (a high school class is one section of one course, so this is far larger than the number of homerooms).",
            "source_field": "sum('Number of Classes'), sheets 'K-5 Average' and 'MS HS Average', all rows",
            "unit": "count", "direction": "neutral"},
        "pupil_teacher_ratio": {
            "label": "Pupil-teacher ratio",
            "definition": "DOE's school pupil-teacher ratio (students per teacher) for 2026-27 from Table C, rounded to one decimal. Neither file says which staff count as teachers. It is not a class-size measure.",
            "source_field": "'School Pupil-Teacher Ratio', Table C sheet '26-27 Pupil-to-Teacher Ratio'",
            "unit": "ratio", "direction": "neutral"},
        "cap_pct_at_or_below": {
            "label": "Classes within state cap",
            "definition": "Share of the school's classes at or below the state class-size caps (K-3: 20, grades 4-8: 23, grades 9-12: 25, physical education and performing groups: 40), as of 10/31/26. DOE granted no exemptions for 2026-27, so every counted class is in the share. Counts K-5 official and cluster classes and 6-12 course sections, including exam prep courses; excludes self-contained classes, 3-K and pre-K, District 75/79/88 schools and charters. Computed by summing Table C's K-5 rows and 6-12 course rows for the school; the same sum citywide gives DOE's 73.4%.",
            "source_field": "sum('Total # of classes at or below cap') / sum('Total # of classes'), Table C sheets '26-27 K-5 by DBN & Grade' and '26-27 6-12 by DBN & Course'",
            "unit": "pct", "direction": "higher"},
        "cap_n_classes": {
            "label": "Classes subject to cap",
            "definition": "Number of classes counted for the state cap, as of 10/31/26 (the denominator of cap_pct_at_or_below).",
            "source_field": "sum('Total # of classes'), Table C 2026-27 sheets",
            "unit": "count", "direction": "neutral"},
        "cap_n_over": {
            "label": "Classes over cap",
            "definition": "Number of classes above the state cap, as of 10/31/26.",
            "source_field": "sum('Total # of classes over cap'), Table C 2026-27 sheets",
            "unit": "count", "direction": "lower"},
    }

    cover = {k: sum(1 for r in schools.values() if r.get(k) is not None) for k in fields}
    n_cap = cover["cap_pct_at_or_below"]

    out = {
        "key": "class_size",
        "title": "Class size, 2026-27",
        "source": "NYC Department of Education: Class Size Report (City Council), November 2026-27, School Data; and Table C of the Nov. 15, 2026 Annual Report on Implementation of New York State's Class Size Caps (Education Law 211-d)",
        "source_url": "https://infohub.nyced.org/reports/government-reports/class-size-reports",
        "file_url": "https://infohub.nyced.org/docs/default-source/default-document-library/november-2026-27-class-size---school.xlsx",
        "other_file_urls": [
            "https://infohub.nyced.org/docs/default-source/default-document-library/fy27---table-c---2026-27-class-size-compliance-by-school.xlsx",
            "https://infohub.nyced.org/docs/default-source/default-document-library/annual-report-on-implementation.pdf",
            "https://infohub.nyced.org/docs/default-source/default-document-library/2026-27-average-class-size-summary---november.pdf",
            "https://infohub.nyced.org/docs/default-source/default-document-library/2026-27-class-size-reporting-methodology---web.pdf",
        ],
        "vintage": "2026-27 November report and Nov. 15, 2026 state report (both data as of 10/31/26)",
        "fetched": "2026-11-17",
        "fields": fields,
        "notes": [
            "One vintage. The average-size fields come from DOE's November 2026-27 City Council report and the cap_* fields from Table C of the Nov. 15, 2026 state-law report; both count classes as of 10/31/26.",
            "New in 2026-27, DOE counts K-5 cluster classes (subjects such as physical education, art, music, science and technology taught by a teacher who teaches that subject across several official classes) and 6-12 exam prep courses, both in the averages and in the cap counts. DOE's citywide 'all schools' average (21.4) includes K-5 cluster classes, and so does avg_class_size_overall. Because of these additions, 2026-27 figures don't compare directly with earlier years; avg_class_size_k5 (official classes only) is the closest to earlier K-5 figures.",
            "Averages are computed by this script as total students / total classes over the rows named in each field's source_field. That is DOE's own row formula, and run on the whole file it reproduces every citywide figure in DOE's November 2026-27 summary (all schools 21.4; K-5 Gen Ed 19.1, ICT 19.5, G&T 23.9, cluster 19.0; MS Gen Ed 22.2, ICT 23.3, accelerated 25.3; HS Gen Ed 22.9, ICT 24.1). The build stops if any check fails.",
            "Self-contained classes are kept out of avg_class_size_overall, _k5 and _mshs, as in DOE's averages, because their size is set by IEP ratios (12:1:1 and so on). They are reported on their own in avg_class_size_special. n_classes counts every program type.",
            "G&T and accelerated classes count toward avg_class_size_overall, _k5 and _mshs but have no field of their own. Following DOE, combined ICT & G&T and ICT & accelerated classes count as ICT.",
            "DOE drops outliers: general education and ICT classes with more than 100 or fewer than 5 students, and self-contained classes with fewer than 2.",
            "Suppression: none in the columns used. 'Number of Students', 'Number of Classes' and 'Average Class Size' are fully populated. Only 'Minimum Class Size' and 'Maximum Class Size' (and the 'Class Size' column on the Counts sheets) mask small values as '<15'; none of those are used.",
            "A null average means the school had no classes in that category (for example avg_class_size_mshs for an elementary school, or avg_class_size_special at a school with no self-contained classes). Nothing was suppressed.",
            f"cap_pct_at_or_below sums Table C's K-5 grade-and-subject rows and 6-12 course rows. Citywide that gives 168,337 of 229,491 classes = 73.4%, matching DOE's reported 73.4%. DOE's report: 'NYCPS did not utilize exemptions in this reporting period to meet the annual milestone.' So, unlike 2025-26, no class drops out of the share. {n_cap:,} schools have a share.",
            "Caps: K-3 20, grades 4-8 23, grades 9-12 25, physical education and performing-group classes 40. The law required 70% of classes at or below the caps in 2026-27; DOE says it reached 73.4%.",
            "Coverage: community school districts 1-32 only. Neither file includes District 75 (citywide special education), District 79 (alternative) or District 88 schools, or charter schools, so those schools get no record here.",
            "pupil_teacher_ratio comes from Table C's 2026-27 sheet; the November school file has no ratio sheet.",
            "Table C also has 2025-26 sheets (with exemptions) and 2027-28 projections; neither is used.",
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
