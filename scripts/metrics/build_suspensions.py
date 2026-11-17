#!/usr/bin/env python3
"""Build data/metrics/suspensions.json from DOE's Local Law 93 Annual Report on
Student Discipline, 2025-26 (school-level removals and suspensions).

Raw file (unmodified download, posted Oct. 7, 2026):
  data/sources/nyc_doe_ll93_student_discipline_annual_2025-26.xlsx
  from https://infohub.nyced.org/docs/default-source/default-document-library/10072026-ll93-annual-report-on-student-discipline-dl-redacted.xlsx
Companion summary (citywide totals and DOE's redaction rule):
  data/sources/nyc_doe_ll93_annual_report_summary_2025-26.pdf
  from https://infohub.nyced.org/docs/default-source/default-document-library/10052026-october-2025--ll93-annual-report-dl-final-redacted.pdf
The 2024-25 file (nyc_doe_ll93_student_discipline_annual_2024-25.xlsx) is kept
in data/sources but no longer read.

Reads only the sheet "Annual Report --R-P-S Totals" (all students, one row per
school; DOE changes the sheet names' capitalization between years, so they are
matched without regard to case). Cell handling:
  - integer  -> integer
  - "R"      -> null (redacted by DOE)
  - blank    -> 0. Checked below against the same workbook's "Annual report--Days"
                sheet: every blank cell has zero incidents of that type there. The
                check only confirms zeros; it never fills in a redacted ("R") cell.
total_suspensions = PRINCIPAL + SUPERINTENDENT, computed only when neither part
is redacted. When one or both parts are redacted, suspensions_shown is the sum
of the parts DOE shows (a floor: the true total is at least this) and
suspensions_hidden_parts says how many parts are hidden. The file's own TOTAL
column counts removals too, so it is kept as a separate field
(total_removals_suspensions).
"""
import json
import os
import re
import sys

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "data", "sources", "nyc_doe_ll93_student_discipline_annual_2025-26.xlsx")
OUT = os.path.join(ROOT, "data", "metrics", "suspensions.json")

SHEET = "Annual Report --R-P-S Totals"
DAYS_SHEET = "Annual report--Days"
EXPECTED_MIN_ROWS = 1200  # file has 1,271 school rows for 2025-26
CITY_TOTALS = {"PRINCIPAL": 19284, "SUPERINTENDENT": 4549}  # summary PDF, 2025-26


def sheet(wb, name):
    """DOE renames sheets' capitalization (and spelling) from year to year."""
    want = name.lower().replace(" ", "")
    for n in wb.sheetnames:
        if n.lower().replace(" ", "") == want:
            return wb[n]
    raise ValueError(f"No sheet like {name!r}; sheets = {wb.sheetnames}")
DBN_RE = re.compile(r"^[0-9]{2}[MXKQR][0-9]{3}$")


def cell(v, where):
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return 0
    if isinstance(v, str):
        if v.strip().upper() == "R":
            return None
        raise ValueError(f"Unexpected text {v!r} at {where}")
    if isinstance(v, float):
        if v != int(v):
            raise ValueError(f"Non-integer count {v!r} at {where}")
        v = int(v)
    if v < 0:
        raise ValueError(f"Negative count {v!r} at {where}")
    return int(v)


def main():
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    rows = list(sheet(wb, SHEET).iter_rows(values_only=True))
    hdr = [str(h).strip() if h is not None else None for h in rows[0]]
    need = ["SchoolDBN", "REMOVAL", "PRINCIPAL", "SUPERINTENDENT", "TOTAL REMOVALS/SUSPENSIONS"]
    for n in need:
        if n not in hdr:
            raise ValueError(f"Column {n!r} not found in sheet {SHEET!r}; header = {hdr}")
    ix = {n: hdr.index(n) for n in need}

    # Zero check source: DAYS sheet, summed by type (verification only).
    drows = list(sheet(wb, DAYS_SHEET).iter_rows(values_only=True))
    dhdr = [str(h).strip() if h is not None else "" for h in drows[0]]
    days = {str(r[0]).strip(): r for r in drows[1:] if r[0]}

    def days_sum(dbn, kind):
        r = days.get(dbn)
        if r is None:
            return None
        return sum((r[j] or 0) for j, h in enumerate(dhdr)
                   if j >= 4 and h.endswith(kind) and isinstance(r[j], (int, float)))

    schools = {}
    skipped = []
    blanks_checked = 0
    for i, r in enumerate(rows[1:], start=2):
        raw = r[ix["SchoolDBN"]]
        if raw is None:
            continue
        dbn = str(raw).strip().upper()
        if not DBN_RE.match(dbn):
            skipped.append(dbn)  # e.g. "Grand Total"
            continue
        if dbn in schools:
            raise ValueError(f"Duplicate DBN {dbn} at row {i}")
        rec = {}
        for field, col in [("removals", "REMOVAL"),
                           ("principal_suspensions", "PRINCIPAL"),
                           ("superintendent_suspensions", "SUPERINTENDENT"),
                           ("total_removals_suspensions", "TOTAL REMOVALS/SUSPENSIONS")]:
            v = r[ix[col]]
            rec[field] = cell(v, f"{SHEET} row {i} {col}")
            if v is None and col != "TOTAL REMOVALS/SUSPENSIONS":
                blanks_checked += 1
                s = days_sum(dbn, col)
                if s not in (0, None):
                    raise ValueError(f"{dbn}: blank {col} but DAYS sheet shows {s}")
        p, s = rec["principal_suspensions"], rec["superintendent_suspensions"]
        rec["total_suspensions"] = (p + s) if (p is not None and s is not None) else None
        rec["suspensions_shown"] = (p or 0) + (s or 0)
        rec["suspensions_hidden_parts"] = (p is None) + (s is None)
        schools[dbn] = rec

    nums = [v for r in schools.values() for v in (r["principal_suspensions"], r["superintendent_suspensions"]) if v]
    min_shown = min(nums)
    if min_shown <= 5:
        raise RuntimeError(f"A shown suspension count is {min_shown}; DOE says it redacts 0 to 5")
    n_one = sum(1 for r in schools.values() if r["suspensions_hidden_parts"] == 1)
    n_both = sum(1 for r in schools.values() if r["suspensions_hidden_parts"] == 2)
    if len(schools) < EXPECTED_MIN_ROWS:
        raise RuntimeError(f"Only {len(schools)} school rows parsed; expected >= {EXPECTED_MIN_ROWS}")
    if skipped != ["GRAND TOTAL"]:
        raise RuntimeError(f"Unexpected non-DBN rows: {skipped}")
    grand = next(r for r in rows[1:] if r[ix["SchoolDBN"]] and str(r[ix["SchoolDBN"]]).strip().upper() == "GRAND TOTAL")
    for col, want in CITY_TOTALS.items():
        if grand[ix[col]] != want:
            raise RuntimeError(f"Grand Total {col} = {grand[ix[col]]}, summary PDF says {want}")

    out = {
        "key": "suspensions",
        "title": "Removals and suspensions, 2025-26",
        "source": "NYC Department of Education, Local Law 93 of 2015 Annual Report on Student Discipline 2025-26 (sheet 'Annual Report --R-P-S Totals')",
        "source_url": "https://infohub.nyced.org/reports/government-reports/suspension-reports",
        "file_url": "https://infohub.nyced.org/docs/default-source/default-document-library/10072026-ll93-annual-report-on-student-discipline-dl-redacted.xlsx",
        "vintage": "2025-26",
        "fetched": "2026-11-17",
        "fields": {
            "principal_suspensions": {
                "label": "Principal's suspensions",
                "definition": "Number of principal's suspensions at the school during the 2025-26 school year (incidents, not students). DOE: 'A principal can suspend a student for one to five school days' (schools.nyc.gov/school-life/safe-schools/suspensions).",
                "source_field": "PRINCIPAL (sheet 'Annual Report --R-P-S Totals')",
                "unit": "count",
                "direction": "neutral",
            },
            "superintendent_suspensions": {
                "label": "Superintendent's suspensions",
                "definition": "Number of superintendent's suspensions during 2025-26. DOE: 'imposed for more serious behavior and may result in a period of suspension for more than five school days.'",
                "source_field": "SUPERINTENDENT (sheet 'Annual Report --R-P-S Totals')",
                "unit": "count",
                "direction": "neutral",
            },
            "total_suspensions": {
                "label": "Total suspensions",
                "definition": "Principal's plus superintendent's suspensions. Computed by this script (not a column in the file), only when neither part is redacted; otherwise null.",
                "source_field": "PRINCIPAL + SUPERINTENDENT (sheet 'Annual Report --R-P-S Totals')",
                "unit": "count",
                "direction": "neutral",
            },
            "suspensions_shown": {
                "label": "Suspensions shown",
                "definition": "Sum of the principal's and superintendent's counts DOE shows, counting a redacted part as 0. When suspensions_hidden_parts is 0 this equals total_suspensions; otherwise it is a floor, since the true total is at least this.",
                "source_field": "PRINCIPAL + SUPERINTENDENT, redacted parts as 0 (sheet 'Annual Report --R-P-S Totals')",
                "unit": "count",
                "direction": "neutral",
            },
            "suspensions_hidden_parts": {
                "label": "Redacted suspension counts",
                "definition": "How many of the two suspension counts (principal's, superintendent's) DOE redacted for the school: 0, 1 or 2.",
                "source_field": "count of 'R' in PRINCIPAL, SUPERINTENDENT (sheet 'Annual Report --R-P-S Totals')",
                "unit": "count",
                "direction": "neutral",
            },
            "removals": {
                "label": "Teacher removals",
                "definition": "Number of removals from class during 2025-26. The Discipline Code allows a teacher to remove a student whose behavior 'is substantially disruptive to the education process'; removed students stay in school and get classwork elsewhere in the building.",
                "source_field": "REMOVAL (sheet 'Annual Report --R-P-S Totals')",
                "unit": "count",
                "direction": "neutral",
            },
            "total_removals_suspensions": {
                "label": "Removals plus suspensions",
                "definition": "DOE's own total of removals, principal's suspensions and superintendent's suspensions for 2025-26.",
                "source_field": "TOTAL REMOVALS/SUSPENSIONS (sheet 'Annual Report --R-P-S Totals')",
                "unit": "count",
                "direction": "neutral",
            },
        },
        "notes": [
            "Counts are incidents (removals or suspensions issued), not students. The file carries no enrollment, so no per-student rate is computed here.",
            "Suppression: cells marked 'R' are redacted and stored as null. DOE's companion LL93 summary for 2025-26 (10052026-october-2025--ll93-annual-report-dl-final-redacted.pdf) says: 'Per the legislation and in accordance with the Family Educational Rights and Privacy Act (FERPA), any value from zero (0) to five (5) has been redacted.' In this file the smallest number shown is " + f"{min_shown}.",
            f"Where one suspension count is shown and the other is redacted ({n_one:,} schools), suspensions_shown is a floor: the school had at least that many. Where both are redacted ({n_both:,} schools), DOE's rule puts each at 0 to 5, so 0 to 10 in all. This script never fills in a redacted cell, and does not work one out from DOE's TOTAL column, which DOE sometimes shows when parts are redacted.",
            f"Blank cells are stored as 0. The file doesn't define blanks, but for every blank cell the same workbook's DAYS sheet shows zero incidents of that type ({blanks_checked:,} blank cells checked, 0 exceptions), and a cell whose DAYS row is redacted is not contradicted. That is despite the PDF's '0 to 5' wording.",
            "total_suspensions is principal's plus superintendent's suspensions, added by this script only when both parts are shown (numbers or blanks). The file's own TOTAL column also includes removals and is kept separately as total_removals_suspensions.",
            "Direction is neutral. As THE CITY's school-vetting guide puts it, a high rate may mean strict discipline and a low rate doesn't guarantee a calm school.",
            f"Coverage: {len(schools):,} DOE schools (districts 1-32, 75 and 79). Charter schools aren't in the report. DOE schools missing from the file get no record here; the file doesn't say whether a missing school had zero incidents.",
            "The Grand Total row matches the summary PDF's 2025-26 totals (19,284 principal's and 4,549 superintendent's suspensions); the build stops if it doesn't.",
            "Only the all-students sheet is used. The workbook's subgroup sheets (race, gender, grade, age, SWD, ELL, foster care, temporary housing, infraction codes, days, transfers) are not read, except that the DAYS sheet is used to confirm that blanks are zeros.",
        ],
        "schools": dict(sorted(schools.items())),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")

    n = len(schools)
    for fld in out["fields"]:
        nn = sum(1 for r in schools.values() if r[fld] is not None)
        print(f"{fld}: {nn}/{n} non-null")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
