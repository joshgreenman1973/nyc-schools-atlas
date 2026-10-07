#!/usr/bin/env python3
"""Build data/metrics/capacity.json from the NYC School Construction Authority /
NYC Public Schools "Enrollment, Capacity & Utilization Report" (the Blue Book),
2025-26 school year, target calculation.

RAW SOURCE
  NYC Open Data dataset gkd7-3vk7 "Enrollment Capacity And Utilization Reports",
  full export (all seven editions stacked; this script keeps Data As Of = 09/09/2026):
    data/sources/nyc_sca_enrollment_capacity_utilization_gkd7-3vk7_all_vintages_thru_2025-26.csv
    from https://data.cityofnewyork.us/api/views/gkd7-3vk7/rows.csv?accessType=DOWNLOAD
  The 09/09/2026 rows are the 2025-26 Blue Book ("Based on 10/31/2025 Audited Registers").
  Checked against the PDF edition (Blue Book 2025-2026.pdf on nycsca.org): the CSV's
  per-building org rows sum to all 409 per-district "TOTAL" lines in the PDF's
  Organizational Report (the 410th line merges two orgs that share a name).

UNIT OF ANALYSIS
  One row per organization (school) per building. An org in several buildings gets
  enrollment and capacity summed across its buildings, and utilization recomputed the
  way the SCA computes it (round half up of 100 * enrollment / capacity; this rule
  reproduces every one of the 2,153 published org-level utilization values).
  Rows whose Org ID is not a borough letter + 3 digits (e.g. MCBO community-based orgs,
  MSBH health centers, MADM offices, MSFS food services) are not schools and are dropped.

CROSSWALK (SCA Org ID, e.g. "M015" -> DOE DBN, e.g. "01M015"), in order
  1. DOE LCGMS school list, Location Code -> ATS System Code (downloaded 2026-10-07,
     https://www.nycenet.edu/PublicApps/LCGMS.aspx):
       data/sources/nyc_doe_lcgms_school_data_2026-10-07.xls
  2. NYC Open Data "2019 - 2020 School Locations" (wg9x-4ke6), location_code -> system_code:
       data/sources/nyc_doe_school_locations_2019-20_wg9x-4ke6.csv
  3. The atlas's own DBN list (data/schools.json): DBN whose last four characters equal
     the Org ID, when exactly one does. (In both DOE lists the Location Code equals the
     last four characters of the DBN for every school.) This picks up District 79
     programs that LCGMS omits.
  4. MANUAL_MATCHES below.
"""
import io
import json
import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC_DIR = os.path.join(ROOT, "data", "sources")
BB = os.path.join(SRC_DIR, "nyc_sca_enrollment_capacity_utilization_gkd7-3vk7_all_vintages_thru_2025-26.csv")
LCGMS = os.path.join(SRC_DIR, "nyc_doe_lcgms_school_data_2026-10-07.xls")
LOC1920 = os.path.join(SRC_DIR, "nyc_doe_school_locations_2019-20_wg9x-4ke6.csv")
ATLAS = os.path.join(ROOT, "data", "schools.json")
OUT = os.path.join(ROOT, "data", "metrics", "capacity.json")

FETCHED = "2026-10-07"
DATA_AS_OF = "09/09/2026"
EXPECTED_MIN_ORGS = 1600  # 1,736 school-type orgs in the 2025-26 edition
ORG_RE = re.compile(r"^[MXKQR]\d{3}$")
DBN_RE = re.compile(r"^\d{2}[MXKQR]\d{3}$")

MANUAL_MATCHES = {
    # SCA Org ID -> (DBN, reason)
    "Q675": ("84Q705", "SCA org Q675 'RENAISSANCE CHARTER SCHOOL - Q' sits in building Q885; LCGMS lists exactly one school with Building Code Q885: 84Q705 'Renaissance Charter School'"),
}


def to_int(v):
    v = (v or "").strip().replace(",", "")
    return int(float(v)) if v != "" else None


def util_round(e, c):
    """SCA rule: round half up of 100*e/c, as a percent; returned as a 0-1 decimal."""
    if e is None or not c:
        return None
    return int(100 * e / c + 0.5) / 100


def main():
    df = pd.read_csv(BB, dtype=str, keep_default_na=False)
    need = ["Geo Dist", "Bldg ID", "Bldg Name", "Bldg Enroll", "Target Bldg Cap", "Target Bldg Util",
            "Org ID", "Incl. Class", "Organization Name", "Org Enroll", "Org Target Cap",
            "Org Target Util", "Data As Of"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise SystemExit(f"missing columns {miss}")
    for c in df.columns:
        df[c] = df[c].str.strip()
    d = df[df["Data As Of"] == DATA_AS_OF]
    if len(d) < 3000:
        raise SystemExit(f"only {len(d)} rows for Data As Of {DATA_AS_OF}")
    d = d[d["Org ID"].str.match(ORG_RE)]

    # ---- crosswalk sources ----------------------------------------------------
    raw = open(LCGMS, "rb").read().decode("utf-16")
    lc = pd.read_html(io.StringIO(raw), header=0,
                      converters={"ATS System Code": str, "Location Code": str, "Building Code": str})[0].fillna("")
    lc = lc[lc["ATS System Code"].astype(str).str.strip().str.upper().str.match(DBN_RE)]
    if len(lc) < 1800:
        raise SystemExit(f"LCGMS parse found only {len(lc)} schools")
    l2d = {r["Location Code"].strip(): r["ATS System Code"].strip().upper() for _, r in lc.iterrows()}
    loc = pd.read_csv(LOC1920, dtype=str, keep_default_na=False)
    l2d_1920 = {r["location_code"].strip(): r["system_code"].strip().upper() for _, r in loc.iterrows()
                if DBN_RE.match(r["system_code"].strip().upper())}
    atlas_by_code = {}
    for rec in json.load(open(ATLAS)):
        dbn = (rec.get("dbn") or "").upper()
        if DBN_RE.match(dbn):
            atlas_by_code.setdefault(dbn[2:], set()).add(dbn)

    # ---- aggregate per org -------------------------------------------------------
    orgs = {}
    for _, r in d.iterrows():
        o = orgs.setdefault(r["Org ID"], {"name": r["Organization Name"], "rows": []})
        o["rows"].append(r)
    if len(orgs) < EXPECTED_MIN_ORGS:
        raise SystemExit(f"only {len(orgs)} school orgs parsed; expected >= {EXPECTED_MIN_ORGS}")

    schools, how, unmatched, dup = {}, {}, [], []
    for org_id, o in orgs.items():
        if org_id in l2d:
            dbn, method = l2d[org_id], "lcgms_location_code"
        elif org_id in l2d_1920:
            dbn, method = l2d_1920[org_id], "locations_2019_20_location_code"
        elif len(atlas_by_code.get(org_id, ())) == 1:
            dbn, method = next(iter(atlas_by_code[org_id])), "atlas_dbn_suffix"
        elif org_id in MANUAL_MATCHES:
            dbn, method = MANUAL_MATCHES[org_id][0], "manual"
        else:
            tot = sum(to_int(r["Org Enroll"]) or 0 for r in o["rows"])
            unmatched.append(f"{org_id} {o['name']} (enrollment {tot})")
            continue
        if dbn in schools:
            dup.append((dbn, org_id))
            continue
        rows = o["rows"]
        enr = [to_int(r["Org Enroll"]) for r in rows]
        cap = [to_int(r["Org Target Cap"]) for r in rows]
        E = sum(x for x in enr if x is not None) if any(x is not None for x in enr) else None
        C = sum(x for x in cap if x is not None) if any(x is not None for x in cap) else None
        if len(rows) == 1:
            u = to_int(rows[0]["Org Target Util"])
            util = u / 100 if u is not None else None
        else:
            util = util_round(E, C)
        # primary building: the one holding most of this org's students (first listed on ties)
        prim = max(range(len(rows)), key=lambda i: (enr[i] or 0, -i))
        pb = rows[prim]
        bu = to_int(pb["Target Bldg Util"])
        schools[dbn] = {
            "utilization": util,
            "capacity": C,
            "enrollment": E,
            "building_id": pb["Bldg ID"] or None,
            "building_name": pb["Bldg Name"] or None,
            "building_utilization": bu / 100 if bu is not None else None,
            "building_enrollment": to_int(pb["Bldg Enroll"]),
            "building_capacity": to_int(pb["Target Bldg Cap"]),
            "n_buildings": len(rows),
        }
        how[dbn] = (method, org_id)

    if dup:
        raise SystemExit(f"two SCA orgs mapped to the same DBN: {dup}")
    n_util = sum(1 for v in schools.values() if v["utilization"] is not None)
    if n_util < 1400:
        raise SystemExit(f"only {n_util} schools with utilization")

    from collections import Counter
    mc = Counter(m for m, _ in how.values())
    notes = [
        "Target calculation, the version the SCA publishes as the 'Classic Edition' and the only one on NYC Open Data. The report itself says Target Capacity and Utilization 'reflect aspirational goals for school buildings': maximum class sizes of 18 in pre-K, 20 in K-3, 23 in grades 4-8 and 25 in grades 9-12 (previously 28 and 30 for grades 4-8 and 9-12).",
        "Enrollment is the audited register as of Oct. 31, 2025. Capacity comes from the Principal Annual Space Survey, in which principals report how each room is used; SCA verifies a share of buildings each year.",
        "Utilization = enrollment / capacity. Over 1.00 means more students than the target seats. The SCA notes one statistic cannot capture the full picture of how a building's space is used.",
        "A school spread across several buildings (common for District 75 and some high schools) has its enrollment and capacity summed across buildings and utilization recomputed from those sums, matching the SCA's own rounding rule. building_* fields describe the building holding most of the school's students; n_buildings says how many there are.",
        "District 75 inclusion programs (Incl. Class '#') carry enrollment but zero capacity in host buildings, because those students sit in general-education classrooms counted in the host school's capacity. Summing them, as the SCA does in its TOTAL lines, nudges a District 75 school's overall utilization up.",
        "Blank cells (no enrollment or no capacity reported for an org in a building) are null. Programs with no capacity (e.g. some YABC and adult programs) have null utilization.",
        f"Org-to-DBN crosswalk: {mc.get('lcgms_location_code', 0)} via the DOE LCGMS list (Location Code), {mc.get('locations_2019_20_location_code', 0)} via NYC Open Data 2019-20 School Locations, {mc.get('atlas_dbn_suffix', 0)} via a unique atlas DBN ending in the Org ID (District 79 programs), {mc.get('manual', 0)} manual (Renaissance Charter School, matched on building Q885).",
    ]
    if unmatched:
        notes.append(f"SCA orgs with no DBN match ({len(unmatched)}), mostly alternate learning centers and adult or citywide programs: " + "; ".join(sorted(unmatched)))

    out = {
        "key": "capacity",
        "title": "Building capacity and utilization",
        "source": "NYC School Construction Authority and NYC Public Schools, Enrollment, Capacity & Utilization Report (Blue Book) 2025-26, Target Calculation, via NYC Open Data",
        "source_url": "https://www.nycsca.org/community/capital-plan-reports-data#Enrollment-Capacity-Utilization-69",
        "file_url": "https://data.cityofnewyork.us/api/views/gkd7-3vk7/rows.csv?accessType=DOWNLOAD",
        "vintage": "2025-26",
        "fetched": FETCHED,
        "fields": {
            "utilization": {
                "label": "School utilization",
                "definition": "Calculated by dividing org. enrollment by org. capacity (target calculation). 1.00 = exactly full.",
                "source_field": "Org Target Util (gkd7-3vk7, Data As Of 09/09/2026); recomputed from summed Org Enroll / Org Target Cap for schools in more than one building",
                "unit": "pct",
                "direction": "neutral",
            },
            "capacity": {
                "label": "Target capacity",
                "definition": "Derived by multiplying each room used by the organization by the number of students it accommodates (target calculation), summed across the school's buildings.",
                "source_field": "Org Target Cap (gkd7-3vk7, Data As Of 09/09/2026)",
                "unit": "count",
                "direction": "neutral",
            },
            "enrollment": {
                "label": "Enrollment (Blue Book)",
                "definition": "Audited register as of Oct. 31, 2025 for the organization, summed across its buildings.",
                "source_field": "Org Enroll (gkd7-3vk7, Data As Of 09/09/2026)",
                "unit": "count",
                "direction": "neutral",
            },
            "building_id": {
                "label": "Building ID",
                "definition": "A discrete four-character code for each building (the building holding most of the school's students).",
                "source_field": "Bldg ID (gkd7-3vk7)",
                "unit": "text",
                "direction": "neutral",
            },
            "building_name": {
                "label": "Building",
                "definition": "The present name of the building.",
                "source_field": "Bldg Name (gkd7-3vk7)",
                "unit": "text",
                "direction": "neutral",
            },
            "building_utilization": {
                "label": "Building utilization",
                "definition": "Building enrollment divided by building capacity, all schools in the building combined (target calculation).",
                "source_field": "Target Bldg Util (gkd7-3vk7)",
                "unit": "pct",
                "direction": "neutral",
            },
            "building_enrollment": {
                "label": "Building enrollment",
                "definition": "Enrollment for the building, the sum of the enrollment of the organizations housed in it.",
                "source_field": "Bldg Enroll (gkd7-3vk7)",
                "unit": "count",
                "direction": "neutral",
            },
            "building_capacity": {
                "label": "Building capacity",
                "definition": "Each room in the building multiplied by the number of students it accommodates (target calculation).",
                "source_field": "Target Bldg Cap (gkd7-3vk7)",
                "unit": "count",
                "direction": "neutral",
            },
            "n_buildings": {
                "label": "Buildings",
                "definition": "Number of buildings in which the Blue Book lists this school.",
                "source_field": "count of rows per Org ID (gkd7-3vk7)",
                "unit": "count",
                "direction": "neutral",
            },
        },
        "notes": notes,
        "crosswalk": {dbn: {"method": m, "org_id": o} for dbn, (m, o) in sorted(how.items())},
        "schools": dict(sorted(schools.items())),
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    nn = {k: sum(1 for v in schools.values() if v[k] is not None) for k in
          ("utilization", "capacity", "enrollment", "building_id", "building_utilization")}
    print(f"wrote {OUT}: {len(schools)} schools from {len(orgs)} orgs; non-null {nn}; methods {dict(mc)}; unmatched {len(unmatched)}")
    for u in sorted(unmatched):
        print("  unmatched:", u)


if __name__ == "__main__":
    main()
