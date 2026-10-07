#!/usr/bin/env python3
"""Build data/metrics/accessibility.json from DOE's Building Accessibility
Profile (BAP) List, the workbook "Current_Building_Accessibility_Profile_List.xlsm"
(last updated 8/14/2026) that schools.nyc.gov links as "Download the
department-wide BAP List".

Raw file (unmodified download, opened read-only with openpyxl; macros are never run):
  data/sources/nyc_doe_building_accessibility_profile_list_2026-08-14.xlsm

Sheets used:
  "Current Accessible School List" (visible): one row per school x building, for
      buildings with some accessibility. This is the published list and the only
      source of accessibility values, ratings and BAP links here.
  "RAW Data" (hidden): DOE's building roster. Used ONLY to identify each school's
      main building ("ATS Code" -> "Building Code", "Primary Site Description" = P)
      and to list open schools that have no building on the list. Its own
      "Accessibility Description" column is stale (it disagrees with the list for
      hundreds of buildings) and is NOT used.

Main-building rule, per DBN:
  1. If the roster gives the DBN's main building and that building is on the list,
     use that row.
  2. If the DBN is not in the roster and has exactly one building on the list,
     use that row.
  3. Otherwise accessibility is null; listed_sites says how many of the school's
     other buildings are on the list.
"""
import json
import os
import re
import sys
from collections import defaultdict

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "data", "sources", "nyc_doe_building_accessibility_profile_list_2026-08-14.xlsm")
OUT = os.path.join(ROOT, "data", "metrics", "accessibility.json")

LIST_SHEET = "Current Accessible School List"
RAW_SHEET = "RAW Data"
EXPECTED_MIN_LIST_ROWS = 1700   # 1,778 rows in the Aug. 14, 2026 list
EXPECTED_MIN_ROSTER = 1600      # 1,740 school codes in the roster sheet
DBN_RE = re.compile(r"^[0-9]{2}[MXKQR][0-9]{3}$")
RATING_RE = re.compile(r"^(\d{1,2}) out of 10$")
ALLOWED = {"Fully Accessible", "Partially Accessible"}


def s(v):
    return "" if v is None else str(v).strip()


def main():
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)

    # --- published list -------------------------------------------------
    rows = list(wb[LIST_SHEET].iter_rows(values_only=True))
    if s(rows[0][1]) != "Last Updated:":
        raise ValueError(f"Unexpected first row in {LIST_SHEET!r}: {rows[0]}")
    last_updated = s(rows[0][2])
    hdr = [s(h) for h in rows[2]]
    need = ["Building Code", "School DBN", "School Name", "Accessibility Description", "BAP URL", "BAP Full URL"]
    for n in need:
        if n not in hdr:
            raise ValueError(f"Column {n!r} missing from {LIST_SHEET!r}; header = {hdr}")
    ix = {n: hdr.index(n) for n in need}

    listed = defaultdict(list)
    n_list_rows = 0
    for i, r in enumerate(rows[3:], start=4):
        if not any(v is not None for v in r):
            continue
        dbn = s(r[ix["School DBN"]]).upper()
        if not DBN_RE.match(dbn):
            raise ValueError(f"Bad DBN {dbn!r} at {LIST_SHEET} row {i}")
        acc = s(r[ix["Accessibility Description"]])
        if acc not in ALLOWED:
            raise ValueError(f"Unexpected accessibility {acc!r} at row {i}")
        m = RATING_RE.match(s(r[ix["BAP URL"]]))  # this column holds the rating text
        if not m:
            raise ValueError(f"Unexpected rating {r[ix['BAP URL']]!r} at row {i}")
        url = s(r[ix["BAP Full URL"]])
        if not url.startswith("https://nycdoe.sharepoint.com/"):
            raise ValueError(f"Unexpected BAP link {url!r} at row {i}")
        rating = int(m.group(1))
        if (acc == "Fully Accessible") != (rating >= 9):
            raise ValueError(f"Rating {rating} vs {acc!r} breaks the 9-10 = Fully rule at row {i}; update the notes")
        listed[dbn].append({
            "building_code": s(r[ix["Building Code"]]).upper(),
            "accessibility": acc,
            "bap_rating": rating,
            "bap_url": url,
        })
        n_list_rows += 1
    if n_list_rows < EXPECTED_MIN_LIST_ROWS:
        raise RuntimeError(f"Only {n_list_rows} list rows parsed; expected >= {EXPECTED_MIN_LIST_ROWS}")

    # --- roster (main building per DBN) ---------------------------------
    raw = list(wb[RAW_SHEET].iter_rows(values_only=True))
    rh = [s(h) for h in raw[0]]
    for n in ["Building Code", "ATS Code", "Primary Site Description"]:
        if n not in rh:
            raise ValueError(f"Column {n!r} missing from {RAW_SHEET!r}")
    bix, aix = rh.index("Building Code"), rh.index("ATS Code")
    racc = rh.index("Accessibility Description")
    main_bldg = {}
    roster_acc = {}  # used only to quantify how stale the roster is, never as a value
    for r in raw[1:]:
        dbn = s(r[aix]).upper()
        if not dbn:
            continue  # secondary sites carry no ATS code
        if not DBN_RE.match(dbn):
            raise ValueError(f"Bad ATS code {dbn!r} in {RAW_SHEET}")
        if dbn in main_bldg:
            raise ValueError(f"Duplicate ATS code {dbn} in {RAW_SHEET}")
        main_bldg[dbn] = s(r[bix]).upper()
        roster_acc[dbn] = s(r[racc])
    if len(main_bldg) < EXPECTED_MIN_ROSTER:
        raise RuntimeError(f"Only {len(main_bldg)} roster schools; expected >= {EXPECTED_MIN_ROSTER}")

    # --- combine ----------------------------------------------------------
    schools = {}
    tally = defaultdict(int)
    for dbn in sorted(set(listed) | set(main_bldg)):
        sites = listed.get(dbn, [])
        mb = main_bldg.get(dbn)
        pick = None
        if mb is not None:
            hits = [x for x in sites if x["building_code"] == mb]
            if hits:
                pick = hits[0]
                tally["rule1_main_building_listed"] += 1
            elif sites:
                tally["main_building_not_listed_other_sites_listed"] += 1
            else:
                tally["roster_school_no_building_listed"] += 1
            main_listed = bool(hits)
        else:
            if len(sites) == 1:
                pick = sites[0]
                mb = pick["building_code"]
                main_listed = True
                tally["rule2_not_in_roster_single_site"] += 1
            else:
                main_listed = None
                tally["not_in_roster_multi_site_unresolved"] += 1
        schools[dbn] = {
            "accessibility": pick["accessibility"] if pick else None,
            "bap_rating": pick["bap_rating"] if pick else None,
            "bap_url": pick["bap_url"] if pick else None,
            "building_code": mb,
            "main_building_listed": main_listed,
            "listed_sites": len(sites),
            "accessibility_source_year": "2026",
        }

    stale = sum(1 for d, rec in schools.items()
                if rec["listed_sites"] == 0 and roster_acc.get(d) in ALLOWED)
    out = {
        "key": "accessibility",
        "title": "Building accessibility",
        "source": "NYC Public Schools, Office of Accessibility Planning (Division of School Facilities): Building Accessibility Profile (BAP) List, sheet 'Current Accessible School List'",
        "source_url": "https://www.schools.nyc.gov/school-life/space-and-facilities/building-accessibility",
        "file_url": "https://nycdoe.sharepoint.com/sites/BAP/_layouts/15/download.aspx?UniqueId=7b78a743-a93a-4d7f-8802-899787bc478e",
        "vintage": f"BAP List last updated {last_updated}",
        "fetched": "2026-10-07",
        "fields": {
            "accessibility": {
                "label": "Building accessibility",
                "definition": "DOE's accessibility description for the school's main building: 'Fully Accessible' or 'Partially Accessible'. Null when the main building isn't on DOE's list. DOE: 'Non-accessible buildings are not included on the BAP List.'",
                "source_field": "Accessibility Description (sheet 'Current Accessible School List')",
                "unit": "text",
                "direction": "neutral",
            },
            "bap_rating": {
                "label": "Accessibility rating (1-10)",
                "definition": "DOE's Building Accessibility Profile rating for the main building. 10 = 'All educational primary function areas within the building are accessible' (built or fully remediated since 1992). 1 = 'general access to at least some of the ground floor through an accessible entrance' with no accessible bathrooms or classrooms. In this file 9-10 are labeled Fully Accessible and 1-8 Partially Accessible.",
                "source_field": "column headed 'BAP URL', which holds the rating text 'N out of 10' (sheet 'Current Accessible School List')",
                "unit": "number",
                "direction": "higher",
            },
            "bap_url": {
                "label": "Building Accessibility Profile",
                "definition": "Link to DOE's detailed Building Accessibility Profile for the main building (entrances, elevators, bathrooms, floor by floor).",
                "source_field": "BAP Full URL (sheet 'Current Accessible School List')",
                "unit": "text",
                "direction": "neutral",
            },
            "building_code": {
                "label": "Main building code",
                "definition": "DOE building code of the school's main building, from the workbook's roster sheet (row with this DBN as 'ATS Code'), or the only listed building for schools not in the roster.",
                "source_field": "Building Code (hidden sheet 'RAW Data', or sheet 'Current Accessible School List')",
                "unit": "text",
                "direction": "neutral",
            },
            "main_building_listed": {
                "label": "Main building on DOE's accessible list",
                "definition": "true if the main building appears on the list for this school; false if it doesn't; null if the main building couldn't be identified. Boolean.",
                "source_field": "derived: Building Code (hidden sheet 'RAW Data') matched against Building Code + School DBN (sheet 'Current Accessible School List')",
                "unit": "text",
                "direction": "neutral",
            },
            "listed_sites": {
                "label": "Buildings on the accessible list",
                "definition": "Number of buildings (main building plus any other sites) listed for this school on DOE's list. 0 = none of the school's buildings is listed.",
                "source_field": "count of rows with this School DBN (sheet 'Current Accessible School List')",
                "unit": "count",
                "direction": "neutral",
            },
            "accessibility_source_year": {
                "label": "Accessibility data year",
                "definition": f"Year of the BAP List edition used (sheet header: 'Last Updated: {last_updated}').",
                "source_field": "cell C1 'Last Updated' (sheet 'Current Accessible School List')",
                "unit": "text",
                "direction": "neutral",
            },
        },
        "notes": [
            "Downloaded from the public 'Anyone with the link' SharePoint folder that schools.nyc.gov links as 'Download the department-wide BAP List' (folder link https://nycdoe.sharepoint.com/:f:/s/BAP/Epw2-AKp5K5LvWC6XLT7NO4BZ65mBbicLyNQv3uIm7OnMQ). No login was needed. The workbook is macro-enabled (.xlsm); it was read as data only and no macros were run.",
            f"The list has {n_list_rows:,} school-by-building rows covering {len(listed):,} school codes. It includes charter schools in DOE buildings (84 DBNs) and District 75 and 79 programs with many sites.",
            f"The list only includes buildings with some accessibility. DOE: 'There are school buildings that are not accessible and, therefore, do not have a BAP. Non-accessible buildings are not included on the BAP List.' Schools in the roster with no listed building have accessibility null and listed_sites 0. This script doesn't write 'Not accessible', because the two sheets don't fully agree: {stale} roster schools whose main building the roster itself marks Fully or Partially Accessible have no building on the list. The lead can choose to show listed_sites = 0 as 'not on DOE's accessible-buildings list.'",
            "Main building: the hidden 'RAW Data' sheet lists one row per school code ('ATS Code') with its building code; non-primary sites have blank ATS codes. It's used only to pick the main building. Its own 'Accessibility Description' column disagrees with the published list for hundreds of buildings (usually 'No Accessibility' where the list now shows a rating), so it was ignored. The hidden 'BAP MASTER' and 'March_2023 (2)' sheets are older and were also ignored.",
            "When a school's main building isn't on the list but another of its sites is, accessibility is null, main_building_listed is false and listed_sites is 1 or more. This is common for District 75 programs, which are spread across many buildings.",
            "Rule counts: " + ", ".join(f"{k} = {v}" for k, v in sorted(tally.items())) + ".",
            "Ratings are per building, so co-located schools share their building's rating and BAP link.",
            f"Charter schools: {sum(1 for d in schools if d.startswith('84')):,} charter DBNs appear (roster or list). The roster and list cover DOE-owned or DOE-leased buildings, so charters in private space have no record here. Missing is not the same as inaccessible.",
            "Fully vs. partially: in this edition every 'Fully Accessible' row is rated 9 or 10 and every 'Partially Accessible' row 1 to 8.",
            "The atlas's older 'Fully/Partially/Not accessible' program tags come from the 2021 DOE directories, a different and older source.",
        ],
        "schools": schools,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")

    n = len(schools)
    for fld in out["fields"]:
        nn = sum(1 for r in schools.values() if r[fld] is not None)
        print(f"{fld}: {nn}/{n} non-null")
    print(dict(tally))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
