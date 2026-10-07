#!/usr/bin/env python3
"""Build data/metrics/pta.json from the NYC DOE Local Law 171 of 2018 report
(PA/PTA financial reporting), school year 2024-25.

Raw file (unmodified download):
  data/sources/nyc_doe_ll171_pta_financial_reporting_2024-25.xlsx
  from https://infohub.nyced.org/docs/default-source/default-document-library/pta-financial-reporting-20251126.xlsx
  (linked as "SY 2024-2025" on https://infohub.nyced.org/reports/government-reports/local-law-171-of-2018)

Sheets used:
  "School"               DBN, School Name, School Code, Beginning Balance, Total Income,
                         Total Expenses, Ending Balance
  "Student Demographics" DBN, School Name, Year, Total Enrollment, ... (Year = 2024-25)

Blank cells in the School sheet mean the PA/PTA had no report entered in SPLCI for
Nov 2024 - Nov 2025; they become null. The workbook has no text suppression markers.
"""
import json
import os
import re

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "data", "sources", "nyc_doe_ll171_pta_financial_reporting_2024-25.xlsx")
OUT = os.path.join(ROOT, "data", "metrics", "pta.json")

FETCHED = "2026-10-07"  # date the raw file was downloaded
EXPECTED_MIN_ROWS = 1400  # the 2024-25 School sheet has 1,540 school rows
DBN_RE = re.compile(r"^\d{2}[MXKQR]\d{3}$")


def num(v):
    """Return a float rounded to cents, or None for a blank cell."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        raise ValueError(f"unexpected text value in numeric column: {v!r}")
    return round(float(v), 2)


def main():
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)

    # ---- School sheet -------------------------------------------------------
    rows = list(wb["School"].iter_rows(values_only=True))
    hdr = [str(h).strip() if h is not None else "" for h in rows[0]]
    need = ["DBN", "School Name", "School Code", "Beginning Balance", "Total Income",
            "Total Expenses", "Ending Balance"]
    if hdr[: len(need)] != need:
        raise SystemExit(f"School sheet header changed: {hdr}")
    idx = {h: i for i, h in enumerate(hdr)}

    # ---- Student Demographics sheet (enrollment denominator) -----------------
    drows = list(wb["Student Demographics"].iter_rows(values_only=True))
    dh = [str(h).strip() if h is not None else "" for h in drows[0]]
    if dh[:4] != ["DBN", "School Name", "Year", "Total Enrollment"]:
        raise SystemExit(f"Student Demographics header changed: {dh[:4]}")
    enroll = {}
    for r in drows[1:]:
        if r[0] is None:
            continue
        if str(r[2]).strip() != "2024-25":
            raise SystemExit(f"unexpected year in demographics: {r[:4]}")
        e = r[3]
        if isinstance(e, (int, float)):
            enroll[str(r[0]).strip().upper()] = int(e)

    schools = {}
    n_rows = 0
    for r in rows[1:]:
        if r[0] is None:
            continue
        dbn = str(r[0]).strip().upper()
        if not DBN_RE.match(dbn):
            raise SystemExit(f"bad DBN {dbn!r}")
        if dbn in schools:
            raise SystemExit(f"duplicate DBN {dbn}")
        n_rows += 1
        inc = num(r[idx["Total Income"]])
        exp = num(r[idx["Total Expenses"]])
        endb = num(r[idx["Ending Balance"]])
        e = enroll.get(dbn)
        per = round(inc / e, 2) if (inc is not None and e) else None
        schools[dbn] = {
            "pta_revenue": inc,
            "pta_expenses": exp,
            "pta_ending_balance": endb,
            "pta_per_student": per,
        }

    if n_rows < EXPECTED_MIN_ROWS:
        raise SystemExit(f"only {n_rows} school rows parsed; expected >= {EXPECTED_MIN_ROWS}")
    n_rev = sum(1 for v in schools.values() if v["pta_revenue"] is not None)
    if n_rev < 1000:
        raise SystemExit(f"only {n_rev} schools with income; expected >= 1000")

    # cross-check against the workbook's own citywide total
    city = list(wb["Citywide"].iter_rows(values_only=True))
    city_income = float(city[1][2])
    tot = sum(v["pta_revenue"] for v in schools.values() if v["pta_revenue"] is not None)
    if abs(tot - city_income) > 50:  # cents rounding across ~1,200 rows
        raise SystemExit(f"school income sum {tot} != citywide {city_income}")

    vals = list(schools.values())
    n_blank = sum(1 for v in vals if all(v[k] is None for k in ("pta_revenue", "pta_expenses", "pta_ending_balance")))
    n_inc_noexp = sum(1 for v in vals if v["pta_revenue"] is not None and v["pta_expenses"] is None)
    n_zero = sum(1 for v in vals if v["pta_revenue"] == 0)

    out = {
        "key": "pta",
        "title": "PA/PTA income and spending",
        "source": "NYC Department of Education, Report on PTA and PA Financial Reporting (Local Law 171 of 2018)",
        "source_url": "https://infohub.nyced.org/reports/government-reports/local-law-171-of-2018",
        "file_url": "https://infohub.nyced.org/docs/default-source/default-document-library/pta-financial-reporting-20251126.xlsx",
        "vintage": "2024-25",
        "fetched": FETCHED,
        "fields": {
            "pta_revenue": {
                "label": "PA/PTA income",
                "definition": "Total income the school's parent association or PTA reported for the 2024-25 school year (annual financial report, self-reported).",
                "source_field": "Total Income (sheet: School)",
                "unit": "dollars",
                "direction": "neutral",
            },
            "pta_expenses": {
                "label": "PA/PTA spending",
                "definition": "Total expenses the school's parent association or PTA reported for the 2024-25 school year (self-reported).",
                "source_field": "Total Expenses (sheet: School)",
                "unit": "dollars",
                "direction": "neutral",
            },
            "pta_ending_balance": {
                "label": "PA/PTA ending balance",
                "definition": "Funds the PA/PTA reported holding at the end of the reporting period (self-reported).",
                "source_field": "Ending Balance (sheet: School)",
                "unit": "dollars",
                "direction": "neutral",
            },
            "pta_per_student": {
                "label": "PA/PTA income per student",
                "definition": "Derived: Total Income divided by the school's 2024-25 Total Enrollment as given in the same workbook.",
                "source_field": "Total Income (sheet: School) / Total Enrollment (sheet: Student Demographics, Year 2024-25)",
                "unit": "dollars",
                "direction": "neutral",
            },
        },
        "notes": [
            "Data are self-reported. PA/PTAs keep their own books and submit paper interim and annual reports to the principal; principals and parent coordinators then key them into the DOE's School Parent Leadership Contact Information (SPLCI) database (workbook NOTES sheet).",
            f"Only reports entered in SPLCI between November 2024 and November 2025 are included. A school whose PA/PTA had no report entered appears with blank cells; those are null here. {n_blank} of {n_rows:,} listed schools are entirely blank, and {n_inc_noexp} more have income but a blank expense cell.",
            f"A reported 0 is kept as 0 ({n_zero} schools report zero income). A zero can mean a PA/PTA that raised nothing or one whose report was entered with zeros; the source does not distinguish.",
            "Pre-K centers, District 79 alternative schools, charter schools (District 84), transfer schools and schools not open in 2024-25 are not in the report, so they have no record here.",
            "Dollar values are stored to the cent. The workbook stores many values as single-precision floats (e.g. 23818.369140625); they are rounded to two decimals. School incomes sum to the workbook's Citywide Total Income of $69,816,000.87.",
            "A handful of rows look like data-entry slips (e.g. negative beginning or ending balances, or income equal to the beginning balance). They are kept as published.",
            "pta_per_student is derived here, not published: Total Income / Total Enrollment from the workbook's own Student Demographics sheet (2024-25, from the DOE Demographic Snapshot). It is null when income is blank.",
        ],
        "schools": dict(sorted(schools.items())),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    n_exp = sum(1 for v in schools.values() if v["pta_expenses"] is not None)
    n_per = sum(1 for v in schools.values() if v["pta_per_student"] is not None)
    print(f"wrote {OUT}: {len(schools)} schools; revenue {n_rev}, expenses {n_exp}, per-student {n_per}")


if __name__ == "__main__":
    main()
