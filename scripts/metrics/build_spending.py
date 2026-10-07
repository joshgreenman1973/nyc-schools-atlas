#!/usr/bin/env python3
"""Build data/metrics/spending.json: per-pupil spending by school, 2024-25,
from NYSED's ESSA Financial Transparency data (School Report Card database).

RAW SOURCE
  NYSED Report Card Database 2024-25, https://data.nysed.gov/files/essa/24-25/SRC2025.zip
  (390 MB zip of a 1.6 GB Access database, SRC2025_Group4.mdb; too big for the repo).
  The one table used, "Expenditures per Pupil", is exported unmodified (every row, every
  column, both years in the table) to
    data/sources/nysed_src2025_expenditures_per_pupil_table.csv
  To regenerate that CSV from the database:
    pip install access-parser
    python3 build_spending.py --from-mdb /path/to/SRC2025_Group4.mdb

CROSSWALK (NYSED 12-digit BEDS code -> DOE DBN), applied in this order
  1. Exact BEDS match in the DOE's LCGMS school list (ATS System Code + BEDS Number),
     downloaded 2026-10-07 from https://www.nycenet.edu/PublicApps/LCGMS.aspx
       data/sources/nyc_doe_lcgms_school_data_2026-10-07.xls  (HTML table, UTF-16)
  2. Exact BEDS match in NYC Open Data "2019 - 2020 School Locations" (wg9x-4ke6)
       data/sources/nyc_doe_school_locations_2019-20_wg9x-4ke6.csv
     (catches schools that have since closed and dropped out of LCGMS)
  3. Charter schools only: NYC charter BEDS codes are county(2) + district(2) + "00" +
     "86" + a 4-digit charter number. When a charter moves district, NYSED and the DOE
     sometimes carry different district digits. If the last six digits ("86"+number)
     are unique among NYSED's NYC charter rows AND unique among the charter BEDS codes in
     one of the two DOE lists, that DOE DBN is used.
  4. MANUAL_MATCHES below: a charter whose LCGMS BEDS field is malformed and whose
     charter-number suffix is not unique; matched on name, with both names recorded.
  Anything still unmatched is listed in notes.
"""
import argparse
import csv
import io
import json
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC_DIR = os.path.join(ROOT, "data", "sources")
EXP_CSV = os.path.join(SRC_DIR, "nysed_src2025_expenditures_per_pupil_table.csv")
LCGMS = os.path.join(SRC_DIR, "nyc_doe_lcgms_school_data_2026-10-07.xls")
LOC1920 = os.path.join(SRC_DIR, "nyc_doe_school_locations_2019-20_wg9x-4ke6.csv")
OUT = os.path.join(ROOT, "data", "metrics", "spending.json")

FETCHED = "2026-10-07"
YEAR = "2025"            # NYSED convention: YEAR 2025 = 2024-25 school year
VINTAGE = "2024-25"
NYC_COUNTY_PREFIXES = ("30", "31", "32", "33", "34", "35")  # NYC citywide + 5 counties
EXPECTED_MIN_SCHOOLS = 1700  # 1,872 NYC school rows in the 2024-25 table
DBN_RE = re.compile(r"^\d{2}[MXKQR]\d{3}$")

# NYSED ENTITY_CD -> (DBN, reason). Names are as printed in each source.
MANUAL_MATCHES = {
    "342700861100": ("84Q422", "NYSED 'SUCCESS ACADEMY CS-NYC 14' = LCGMS 84Q422 'Success Academy Charter School - NYC 14' (LCGMS BEDS field holds 38400010422; suffix 861100 is shared with another NYSED charter)"),
}


def export_from_mdb(mdb_path):
    from access_parser import AccessParser  # pip install access-parser
    db = AccessParser(mdb_path)
    t = db.parse_table("Expenditures per Pupil")
    cols = list(t.keys())
    n = len(t[cols[0]])
    with open(EXP_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i in range(n):
            w.writerow([t[c][i] for c in cols])
    print(f"exported {n} rows to {EXP_CSV}")


def read_lcgms():
    raw = open(LCGMS, "rb").read().decode("utf-16")
    conv = {c: str for c in ["ATS System Code", "Location Code", "BEDS Number", "Building Code",
                             "Location Name", "Managed By Name"]}
    df = pd.read_html(io.StringIO(raw), header=0, converters=conv)[0].fillna("")
    for c in conv:
        df[c] = df[c].astype(str).str.strip()
    df = df[df["ATS System Code"].str.upper().str.match(DBN_RE)]
    if len(df) < 1800:
        raise SystemExit(f"LCGMS parse found only {len(df)} schools")
    return df


def to_num(v):
    v = (v or "").strip()
    if v == "":
        return None
    return float(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-mdb", help="re-export the Expenditures per Pupil table from SRC2025_Group4.mdb first")
    args = ap.parse_args()
    if args.from_mdb:
        export_from_mdb(args.from_mdb)

    e = pd.read_csv(EXP_CSV, dtype=str, keep_default_na=False)
    need = ["YEAR", "PUPIL_COUNT_TOT", "PER_FEDERAL_EXP", "PER_STATE_LOCAL_EXP",
            "PER_FED_STATE_LOCAL_EXP", "ENTITY_CD", "ENTITY_NAME", "DATA_REPORTED_EXP"]
    miss = [c for c in need if c not in e.columns]
    if miss:
        raise SystemExit(f"missing columns {miss}")
    e = e[(e["YEAR"].str.replace(".0", "", regex=False) == YEAR)
          & e["ENTITY_CD"].str[:2].isin(NYC_COUNTY_PREFIXES)
          & (e["ENTITY_CD"].str[-4:] != "0000")]  # drop the NYC Chancellor's Office row
    if len(e) < EXPECTED_MIN_SCHOOLS:
        raise SystemExit(f"only {len(e)} NYC school rows for YEAR {YEAR}")

    # ---- crosswalk sources --------------------------------------------------
    lc = read_lcgms()
    b2d_lcgms = {r["BEDS Number"]: r["ATS System Code"].upper() for _, r in lc.iterrows()
                 if re.fullmatch(r"\d{12}", r["BEDS Number"])}
    lc_names = {r["ATS System Code"].upper(): r["Location Name"] for _, r in lc.iterrows()}
    loc = pd.read_csv(LOC1920, dtype=str, keep_default_na=False)
    loc["BEDS"] = loc["BEDS"].str.strip()
    loc["system_code"] = loc["system_code"].str.strip().str.upper()
    b2d_1920 = {r["BEDS"]: r["system_code"] for _, r in loc.iterrows()
                if re.fullmatch(r"\d{12}", r["BEDS"]) and DBN_RE.match(r["system_code"])}
    names_1920 = dict(zip(loc["system_code"], loc["location_name"]))

    def charter_suffix_index(b2d):
        idx = {}
        for b, d in b2d.items():
            if b[6:8] == "86" and d.startswith("84"):
                idx.setdefault(b[6:], set()).add(d)
        return {k: next(iter(v)) for k, v in idx.items() if len(v) == 1}

    suf_lcgms = charter_suffix_index(b2d_lcgms)
    suf_1920 = charter_suffix_index(b2d_1920)
    nysed_suf_counts = e[e["ENTITY_CD"].str[6:8] == "86"]["ENTITY_CD"].str[6:].value_counts()

    schools, how, unmatched, dup = {}, {}, [], []
    for _, r in e.iterrows():
        cd = r["ENTITY_CD"].strip()
        dbn, method = None, None
        if cd in b2d_lcgms:
            dbn, method = b2d_lcgms[cd], "lcgms_beds"
        elif cd in b2d_1920:
            dbn, method = b2d_1920[cd], "locations_2019_20_beds"
        elif cd[6:8] == "86" and nysed_suf_counts.get(cd[6:], 0) == 1 and (cd[6:] in suf_lcgms or cd[6:] in suf_1920):
            dbn = suf_lcgms.get(cd[6:]) or suf_1920.get(cd[6:])
            method = "charter_number_suffix"
        elif cd in MANUAL_MATCHES:
            dbn, method = MANUAL_MATCHES[cd][0], "manual_name_match"
        if not dbn:
            unmatched.append(f"{cd} {r['ENTITY_NAME'].strip()}")
            continue
        if dbn in schools:
            dup.append((dbn, cd))
            continue
        reported = r["DATA_REPORTED_EXP"].strip() == "Y"
        pc = to_num(r["PUPIL_COUNT_TOT"])
        rec = {
            "per_pupil": to_num(r["PER_FED_STATE_LOCAL_EXP"]) if reported else None,
            "per_pupil_federal": to_num(r["PER_FEDERAL_EXP"]) if reported else None,
            "per_pupil_state_local": to_num(r["PER_STATE_LOCAL_EXP"]) if reported else None,
            "pupil_count": int(pc) if pc is not None else None,
        }
        for k in ("per_pupil", "per_pupil_federal", "per_pupil_state_local"):
            if rec[k] is not None:
                rec[k] = int(round(rec[k]))  # source stores whole dollars as floats
        schools[dbn] = rec
        how[dbn] = (method, cd, r["ENTITY_NAME"].strip())

    if dup:
        raise SystemExit(f"two NYSED rows mapped to the same DBN: {dup}")
    if len(schools) < EXPECTED_MIN_SCHOOLS:
        raise SystemExit(f"only {len(schools)} schools matched")

    from collections import Counter
    mcount = Counter(v[0] for v in how.values())
    notes = [
        "THE CITY's caveat: a higher per-pupil figure doesn't necessarily mean more resources. Small schools with falling enrollment can look inflated under 'hold harmless' budget policies, and per-pupil amounts swing with the enrollment denominator.",
        "NYSED definition (2023-24 and later reports): 'Spending Per Pupil: This School' is the total non-excluded expenditures divided by school enrollment. Enrollment is the P-12 count on BEDS day (typically the first Wednesday of October), including pre-K in the school but not pre-K in community-based organizations.",
        "Excluded from the totals (NYSED business rules): charter-school tuition paid by the district, debt service, depreciation/amortization (charters), and 'other' exclusions such as services to nonpublic schools and payments to pre-K community-based organizations.",
        "These are actual expenditures for the fiscal year ending June 30, 2025, reported by the district (NYC DOE) or by each charter school; NYSED treats charters as independent local education agencies. Exclusions differ by type (districts exclude charter tuition; charters exclude depreciation/amortization), so charter and district figures are not built identically.",
        "The school figure spans every function NYSED tracks: instruction, pupil and instructional-staff support, general and school administration, building operation and maintenance, student transportation, business/central support, food service, and 'Districtwide Current Expenditures' attributable to the school that cannot be reported by function. It is broader than the school's own budget.",
        "Values are whole dollars, exactly as stored in the database's PER_* columns (NYSED's web pages show the same figures to the cent, e.g. Stuyvesant $21,663.74 vs 21664 here).",
        "One NYC school row has DATA_REPORTED_EXP = 'N' and blank amounts (CHOICE CHARTER SCHOOL, 320700861005); it is null here. The database has no other suppression markers in this table.",
        f"BEDS-to-DBN crosswalk: {mcount.get('lcgms_beds', 0)} via the DOE LCGMS list (2026-10-07), {mcount.get('locations_2019_20_beds', 0)} via NYC Open Data 2019-20 School Locations, {mcount.get('charter_number_suffix', 0)} charters via the unique 6-digit charter-number suffix of the BEDS code, {mcount.get('manual_name_match', 0)} by documented name match. See the script header.",
        "Some DOE charter names have changed since the atlas was built; e.g. NYSED 'GIRLS PREP CHARTER SCHOOL-BRONX' is LCGMS 84X487 'Bronx Charter School for Excellence 6'.",
    ]
    if unmatched:
        notes.append(f"Unmatched NYSED rows ({len(unmatched)}): " + "; ".join(unmatched))

    out = {
        "key": "spending",
        "title": "Per-pupil spending",
        "source": "New York State Education Department, ESSA Financial Transparency (School Level Finance Survey) data, School Report Card database 2024-25, table 'Expenditures per Pupil'",
        "source_url": "https://data.nysed.gov/downloads.php",
        "file_url": "https://data.nysed.gov/files/essa/24-25/SRC2025.zip",
        "vintage": VINTAGE,
        "fetched": FETCHED,
        "fields": {
            "per_pupil": {
                "label": "Spending per student",
                "definition": "Per pupil expenditures using federal and state/local funds (FED_STATE_LOCAL_EXP / PUPIL_COUNT_TOT): the school's total non-excluded expenditures divided by its enrollment.",
                "source_field": "PER_FED_STATE_LOCAL_EXP (table: Expenditures per Pupil, YEAR = 2025)",
                "unit": "dollars",
                "direction": "neutral",
            },
            "per_pupil_federal": {
                "label": "Federal spending per student",
                "definition": "Per pupil expenditures using federal funds (FEDERAL_EXP / PUPIL_COUNT_TOT).",
                "source_field": "PER_FEDERAL_EXP (table: Expenditures per Pupil, YEAR = 2025)",
                "unit": "dollars",
                "direction": "neutral",
            },
            "per_pupil_state_local": {
                "label": "State and local spending per student",
                "definition": "Per pupil expenditures using state and local funds (STATE_LOCAL_EXP / PUPIL_COUNT_TOT).",
                "source_field": "PER_STATE_LOCAL_EXP (table: Expenditures per Pupil, YEAR = 2025)",
                "unit": "dollars",
                "direction": "neutral",
            },
            "pupil_count": {
                "label": "Enrollment used",
                "definition": "Pupil count NYSED divided by (P-12 enrollment on BEDS day, October 2024).",
                "source_field": "PUPIL_COUNT_TOT (table: Expenditures per Pupil, YEAR = 2025)",
                "unit": "count",
                "direction": "neutral",
            },
        },
        "notes": notes,
        "crosswalk": {d: {"method": m, "beds": b, "nysed_name": n} for d, (m, b, n) in sorted(how.items())},
        "schools": dict(sorted(schools.items())),
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    nn = {k: sum(1 for v in schools.values() if v[k] is not None) for k in
          ("per_pupil", "per_pupil_federal", "per_pupil_state_local", "pupil_count")}
    print(f"wrote {OUT}: {len(schools)} schools; non-null {nn}; methods {dict(mcount)}; unmatched {len(unmatched)}")
    for u in unmatched:
        print("  unmatched:", u)
    for d, (m, b, n) in sorted(how.items()):
        if m in ("charter_number_suffix", "manual_name_match"):
            print(f"  {m}: {b} {n!r} -> {d} {lc_names.get(d) or names_1920.get(d)!r}")


if __name__ == "__main__":
    main()
