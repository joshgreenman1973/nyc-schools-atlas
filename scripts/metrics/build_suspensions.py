#!/usr/bin/env python3
"""Build data/metrics/suspensions.json from DOE's Local Law 93 Annual Report on
Student Discipline, 2024-25 (school-level removals and suspensions).

Raw file (unmodified download):
  data/sources/nyc_doe_ll93_student_discipline_annual_2024-25.xlsx
  from https://infohub.nyced.org/docs/default-source/default-document-library/10142025-ll93-annual-report-on-student-discipline-dl.xlsx

Reads only the sheet "Annual Report --R-P-S TOTALS" (all students, one row per
school). Cell handling:
  - integer  -> integer
  - "R"      -> null (redacted by DOE)
  - blank    -> 0. Checked below against the same workbook's "Annula Report--DAYS"
                sheet: every blank cell has zero incidents of that type there. The
                check only confirms zeros; it never fills in a redacted ("R") cell.
total_suspensions = PRINCIPAL + SUPERINTENDENT, computed only when neither part
is redacted. The file's own TOTAL column counts removals too, so it is kept as a
separate field (total_removals_suspensions).
"""
import json
import os
import re
import sys

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "data", "sources", "nyc_doe_ll93_student_discipline_annual_2024-25.xlsx")
OUT = os.path.join(ROOT, "data", "metrics", "suspensions.json")

SHEET = "Annual Report --R-P-S TOTALS"
DAYS_SHEET = "Annula Report--DAYS"  # sic, DOE's spelling
EXPECTED_MIN_ROWS = 1200  # file has 1,278 school rows for 2024-25
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
    rows = list(wb[SHEET].iter_rows(values_only=True))
    hdr = [str(h).strip() if h is not None else None for h in rows[0]]
    need = ["SchoolDBN", "REMOVAL", "PRINCIPAL", "SUPERINTENDENT", "TOTAL REMOVALS/SUSPENSIONS"]
    for n in need:
        if n not in hdr:
            raise ValueError(f"Column {n!r} not found in sheet {SHEET!r}; header = {hdr}")
    ix = {n: hdr.index(n) for n in need}

    # Zero check source: DAYS sheet, summed by type (verification only).
    drows = list(wb[DAYS_SHEET].iter_rows(values_only=True))
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
        schools[dbn] = rec

    if len(schools) < EXPECTED_MIN_ROWS:
        raise RuntimeError(f"Only {len(schools)} school rows parsed; expected >= {EXPECTED_MIN_ROWS}")
    if skipped != ["GRAND TOTAL"]:
        raise RuntimeError(f"Unexpected non-DBN rows: {skipped}")

    out = {
        "key": "suspensions",
        "title": "Removals and suspensions, 2024-25",
        "source": "NYC Department of Education, Local Law 93 of 2015 Annual Report on Student Discipline 2024-25 (sheet 'Annual Report --R-P-S TOTALS')",
        "source_url": "https://infohub.nyced.org/reports/government-reports/suspension-reports",
        "file_url": "https://infohub.nyced.org/docs/default-source/default-document-library/10142025-ll93-annual-report-on-student-discipline-dl.xlsx",
        "vintage": "2024-25",
        "fetched": "2026-10-07",
        "fields": {
            "principal_suspensions": {
                "label": "Principal's suspensions",
                "definition": "Number of principal's suspensions at the school during the 2024-25 school year (incidents, not students). DOE: 'A principal can suspend a student for one to five school days' (schools.nyc.gov/school-life/safe-schools/suspensions).",
                "source_field": "PRINCIPAL (sheet 'Annual Report --R-P-S TOTALS')",
                "unit": "count",
                "direction": "neutral",
            },
            "superintendent_suspensions": {
                "label": "Superintendent's suspensions",
                "definition": "Number of superintendent's suspensions during 2024-25. DOE: 'imposed for more serious behavior and may result in a period of suspension for more than five school days.'",
                "source_field": "SUPERINTENDENT (sheet 'Annual Report --R-P-S TOTALS')",
                "unit": "count",
                "direction": "neutral",
            },
            "total_suspensions": {
                "label": "Total suspensions",
                "definition": "Principal's plus superintendent's suspensions. Computed by this script (not a column in the file), only when neither part is redacted; otherwise null.",
                "source_field": "PRINCIPAL + SUPERINTENDENT (sheet 'Annual Report --R-P-S TOTALS')",
                "unit": "count",
                "direction": "neutral",
            },
            "removals": {
                "label": "Teacher removals",
                "definition": "Number of removals from class during 2024-25. The Discipline Code allows a teacher to remove a student whose behavior 'is substantially disruptive to the education process'; removed students stay in school and get classwork elsewhere in the building.",
                "source_field": "REMOVAL (sheet 'Annual Report --R-P-S TOTALS')",
                "unit": "count",
                "direction": "neutral",
            },
            "total_removals_suspensions": {
                "label": "Removals plus suspensions",
                "definition": "DOE's own total of removals, principal's suspensions and superintendent's suspensions for 2024-25.",
                "source_field": "TOTAL REMOVALS/SUSPENSIONS (sheet 'Annual Report --R-P-S TOTALS')",
                "unit": "count",
                "direction": "neutral",
            },
        },
        "notes": [
            "Counts are incidents (removals or suspensions issued), not students. The file carries no enrollment, so no per-student rate is computed here.",
            "Suppression: cells marked 'R' are redacted and stored as null. DOE's companion LL93 report (10302025-october-2025--ll93-annual-report-dl.pdf) says: 'Per the legislation and in accordance with the Family Educational Rights and Privacy Act (FERPA), any value from zero (0) to five (5) has been redacted.' In this file the smallest number shown is 6.",
            "Not every 'R' hides a value of 5 or less. Some larger cells, usually the TOTAL column, are also marked 'R', apparently so a redacted part can't be worked out by subtraction. DOE doesn't describe this; it's inferred from the file.",
            f"Blank cells are stored as 0. The file doesn't define blanks, but for every blank cell the same workbook's DAYS sheet shows zero incidents of that type ({blanks_checked:,} blank cells checked, 0 exceptions). That is despite the PDF's '0 to 5' wording.",
            "total_suspensions is principal's plus superintendent's suspensions, added by this script only when both parts are shown (numbers or blanks). The file's own TOTAL column also includes removals and is kept separately as total_removals_suspensions.",
            "Direction is neutral. As THE CITY's school-vetting guide puts it, a high rate may mean strict discipline and a low rate doesn't guarantee a calm school.",
            f"Coverage: {len(schools):,} DOE schools (districts 1-32, 75 and 79). Charter schools aren't in the report. DOE schools missing from the file get no record here; the file doesn't say whether a missing school had zero incidents.",
            "Only the all-students sheet is used. The workbook's subgroup sheets (race, gender, grade, age, SWD, ELL, foster care, temporary housing, infraction codes, days) are not read, except that the DAYS sheet is used to confirm that blanks are zeros.",
            "Newer data: DOE's March 2026 biannual report covers July-December 2025, but only as citywide monthly totals in a PDF. The 2025-26 school-level annual file is due around Oct. 31, 2026.",
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
