#!/usr/bin/env python3
"""Build data/metrics/counselors.json from DOE's 2025-26 guidance counselor report
(Local Law 56 of 2014), Appendix A: school-level guidance counselors and social workers.

Raw file (unmodified download):
  data/sources/nyc_doe_ll56_guidance_counselor_sw_reporting_2025-26.xlsx
  from https://infohub.nyced.org/docs/default-source/default-document-library/2025-26---gc-and-sw-report---reporting-spreadsheet-020926.xlsx
Companion memo (definitions, citywide totals):
  data/sources/nyc_doe_ll56_guidance_counselor_report_memo_2026-02-15.pdf

Reads only sheet "2025-26 GC & SW Data", one row per school, with cached cell values
(data_only=True; one column, 'School Psychologist Providing Mandated Counseling',
holds formulas that point at an external workbook and is not used).

Ratios. The file's ratio columns are 2024-25 enrollment divided by the staff count,
but the divisor is floored at 1: a school with 0 or 0.4 counselors shows its full
enrollment as the ratio. This script checks that pattern and keeps DOE's ratio only
where the count is at least 1 (where the ratio is a true students-per-counselor
figure). Where the count is below 1, or where the file's ratio disagrees with its
own enrollment and counts (4 cells), the ratio is stored as null.
"""
import json
import math
import os
import re

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "data", "sources", "nyc_doe_ll56_guidance_counselor_sw_reporting_2025-26.xlsx")
OUT = os.path.join(ROOT, "data", "metrics", "counselors.json")

SHEET = "2025-26 GC & SW Data"
EXPECTED_MIN_ROWS = 1500  # 1,610 school rows in the 2025-26 file
DBN_RE = re.compile(r"^[0-9]{2}[MXKQR][0-9A-Z]{3}$")  # 88-district rows use letters, e.g. 88XLC1

COLS = {
    "dbn": "DBN",
    "total": "Total Guidance Counselors (GC) & Social Workers (SW)",
    "gc": "Total GC",
    "sw": "Total SW",
    "ft_gc": "Full-time GC",
    "pt_gc": "Part-time GC",
    "gc_multi": "GC Serving More than One Location",
    "enroll": "2024-25 SY Enrollment",
    "r_all": "Ratio GC & SW",
    "r_gc": "Ratio GC Only",
}


def num(v, where, allow_text=()):
    """Return float, or None for blanks / known text markers. Raise on anything else."""
    if v is None:
        return None
    if isinstance(v, str):
        t = v.strip()
        if t == "":
            return None
        for marker in allow_text:
            if t.startswith(marker):
                return None
        raise ValueError(f"Unexpected text {v!r} at {where}")
    if isinstance(v, bool):
        raise ValueError(f"Unexpected boolean at {where}")
    f = float(v)
    if math.isnan(f):
        return None
    return f


def r2(x):
    return None if x is None else round(x, 2)


def main():
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
    rows = list(wb[SHEET].iter_rows(values_only=True))
    hdr = [str(h).split("\n")[0].strip() if h is not None else None for h in rows[0]]
    idx = {}
    for k, name in COLS.items():
        if name not in hdr:
            raise SystemExit(f"Missing column {name!r}; got {hdr}")
        idx[k] = hdr.index(name)

    schools = {}
    marker_rows = {}
    floor_ok = 0
    ratio_exceptions = []
    totals = {"gc": 0.0, "sw": 0.0, "total": 0.0, "gc_multi": 0.0}
    file_total_row = None
    for i, r in enumerate(rows[1:], start=2):
        dbn = r[idx["dbn"]]
        if dbn is None or str(dbn).strip() == "":
            continue
        dbn = str(dbn).strip().upper()
        if dbn == "TOTAL":
            file_total_row = r
            continue
        if not DBN_RE.match(dbn):
            raise SystemExit(f"Row {i}: unexpected DBN {dbn!r}")
        if dbn in schools:
            raise SystemExit(f"Row {i}: duplicate DBN {dbn}")
        where = f"row {i} ({dbn})"
        total_raw = r[idx["total"]]
        if isinstance(total_raw, str) and total_raw.strip():
            # e.g. 04M310: "GC and SW counts reflected on 79M331"
            marker_rows[dbn] = total_raw.strip()
        total = num(total_raw, where, allow_text=("GC and SW counts reflected on",))
        gc = num(r[idx["gc"]], where)
        sw = num(r[idx["sw"]], where)
        ft_gc = num(r[idx["ft_gc"]], where)
        pt_gc = num(r[idx["pt_gc"]], where)
        gc_multi = num(r[idx["gc_multi"]], where)
        enroll = num(r[idx["enroll"]], where)
        r_all = num(r[idx["r_all"]], where, allow_text=("N/A",))
        r_gc = num(r[idx["r_gc"]], where, allow_text=("N/A",))

        if gc is not None and ft_gc is not None and pt_gc is not None and abs(gc - (ft_gc + pt_gc)) > 0.01:
            raise SystemExit(f"{where}: Total GC != Full-time GC + Part-time GC")
        if total is not None and gc is not None and sw is not None and abs(total - (gc + sw)) > 0.01:
            raise SystemExit(f"{where}: Total GC & SW != Total GC + Total SW")

        # Confirm DOE's ratio = enrollment / max(count, 1); keep it only when count >= 1.
        def keep_ratio(ratio, count, label):
            nonlocal floor_ok
            if ratio is None or count is None or enroll is None:
                return None
            expect = enroll / max(count, 1.0)
            if abs(ratio - expect) <= 0.01 * max(1.0, expect):
                floor_ok += 1
            else:
                ratio_exceptions.append(f"{dbn} {label}: file {ratio}, enrollment {int(enroll)} / count {count} = {round(enroll / count, 2) if count else 'n/a'}")
                return None  # the file's ratio disagrees with its own counts; don't publish it
            return ratio if count >= 1 else None

        rec = {
            "n_counselors": r2(ft_gc),
            "n_counselors_total": r2(gc),
            "n_social_workers": r2(sw),
            "students_per_counselor": r2(keep_ratio(r_gc, gc, "GC")),
            "students_per_counselor_or_sw": r2(keep_ratio(r_all, total, "GC & SW")),
            "enrollment_basis": None if enroll is None else int(enroll),
            "n_counselors_multi_site": r2(gc_multi),
        }
        schools[dbn] = rec
        for k in ("gc", "sw", "total", "gc_multi"):
            v = {"gc": gc, "sw": sw, "total": total, "gc_multi": gc_multi}[k]
            totals[k] += v or 0.0

    if len(schools) < EXPECTED_MIN_ROWS:
        raise SystemExit(f"Parsed {len(schools)} schools; expected at least {EXPECTED_MIN_ROWS}")
    # Reconcile with the file's own Total row and the memo (3,296 GCs; 2,049 SWs; 5,345 total; 16 multi-site GCs).
    if file_total_row is None:
        raise SystemExit("No 'Total' row found")
    for k, want_memo in (("total", 5345), ("gc", 3296), ("sw", 2049)):
        file_val = float(file_total_row[idx[k]])
        if abs(totals[k] - file_val) > 0.5 or abs(round(totals[k]) - want_memo) > 1:
            raise SystemExit(f"Sum of {k} = {totals[k]:.2f}; file Total row {file_val}; memo {want_memo}")
    if round(totals["gc_multi"]) != 16:
        raise SystemExit(f"GC Serving More than One Location sums to {totals['gc_multi']}, memo says 16")
    # The floor pattern must hold for nearly all rows before we rely on it.
    if len(ratio_exceptions) > 10:
        raise SystemExit("Ratio pattern broke on too many rows:\n" + "\n".join(ratio_exceptions[:20]))

    fields = {
        "n_counselors": {
            "label": "Full-time counselors",
            "definition": "Full-time guidance counselors at the school, as reported by DOE for 2025-26 (the report's Feb. 15, 2026 Appendix A). Counts include guidance counselors in the Absent Teacher Reserve, High Needs counselors and Single Shepherds. Decimal values occur where a counselor is split across locations.",
            "source_field": "'Full-time GC', sheet '2025-26 GC & SW Data'",
            "unit": "number", "direction": "neutral"},
        "n_counselors_total": {
            "label": "Guidance counselors",
            "definition": "All guidance counselors at the school, full-time plus part-time (part-timers appear as fractions such as 0.2). This is the count DOE divides into enrollment for its ratio.",
            "source_field": "'Total GC', sheet '2025-26 GC & SW Data'",
            "unit": "number", "direction": "neutral"},
        "n_social_workers": {
            "label": "Social workers",
            "definition": "All social workers at the school, full-time plus part-time. Includes School Response Clinicians, High Needs social workers and Bridging the Gap social workers. Social workers shared among schools are split fractionally (e.g. 0.2 at one school).",
            "source_field": "'Total SW', sheet '2025-26 GC & SW Data'",
            "unit": "number", "direction": "neutral"},
        "students_per_counselor": {
            "label": "Students per counselor",
            "definition": "DOE's ratio of 2024-25 enrollment to guidance counselors (Total GC). Kept only where the school has at least 1 counselor. Below that, DOE's file divides by 1 instead of the real count, so the ratio is stored as null. Citywide DOE reports 1:259 for all schools and 1:182 for schools with high school grades. A commonly cited benchmark is 250 students per counselor, fewer in high-needs schools.",
            "source_field": "'Ratio GC Only', sheet '2025-26 GC & SW Data' (= '2024-25 SY Enrollment' / 'Total GC')",
            "unit": "ratio", "direction": "lower"},
        "students_per_counselor_or_sw": {
            "label": "Students per counselor or social worker",
            "definition": "DOE's ratio of 2024-25 enrollment to guidance counselors plus social workers combined. Null where the combined count is below 1 (same divide-by-1 issue). Citywide DOE reports 1:160 for all schools and 1:125 for schools with high school grades.",
            "source_field": "'Ratio GC & SW', sheet '2025-26 GC & SW Data' (= '2024-25 SY Enrollment' / 'Total Guidance Counselors (GC) & Social Workers (SW)')",
            "unit": "ratio", "direction": "lower"},
        "enrollment_basis": {
            "label": "Enrollment used for ratios",
            "definition": "The 2024-25 enrollment DOE used as the numerator of both ratios. DOE: 'Ratios calculated using 2024-25 enrollment data unless the school opened in July 2025.'",
            "source_field": "'2024-25 SY Enrollment', sheet '2025-26 GC & SW Data'",
            "unit": "count", "direction": "neutral"},
        "n_counselors_multi_site": {
            "label": "Counselors serving more than one location",
            "definition": "DOE's count of guidance counselors at this school who also serve another location. Nonzero at only 15 schools; the column sums to 16, matching the memo: '15 schools have a guidance counselor who serves more than one location. There are 16 guidance counselors who serve more than one location.'",
            "source_field": "'GC Serving More than One Location', sheet '2025-26 GC & SW Data'",
            "unit": "number", "direction": "neutral"},
    }

    cover = {k: sum(1 for r in schools.values() if r.get(k) is not None) for k in fields}
    zero_gc = sum(1 for r in schools.values() if r["n_counselors_total"] == 0)
    frac_gc = sum(1 for r in schools.values() if r["n_counselors_total"] is not None and 0 < r["n_counselors_total"] < 1)

    notes = [
        "Vintage: DOE's Feb. 15, 2026 report under Local Law 56 of 2014, covering staff in the 2025-26 school year. The file doesn't give a staffing snapshot date. Ratios use 2024-25 enrollment, so the numerator is a year older than the staff counts.",
        "Counts are decimals, not whole people. Part-time and shared staff appear as fractions (0.2, 0.4 ...). Counts are rounded to two decimals here to strip floating-point noise in the file (e.g. 2.4000001).",
        "Shared staff. The file splits a shared counselor or social worker fractionally across the schools they serve. Counselor sharing is rare: 15 schools, 16 counselors (n_counselors_multi_site). Social worker sharing is common: the memo says '1,363 schools have a social worker who serves more than one location. There are 569 social workers who serve more than one location.' Schools on a shared campus each get their own row, and only the staff assigned to that DBN are counted. There is no campus-level total.",
        f"Ratio quirk. DOE's ratio columns equal enrollment / max(count, 1). Where a school has fewer than 1 counselor, the file shows its whole enrollment as the ratio, as if it had exactly one. {zero_gc} schools have 0 counselors and {frac_gc} have between 0 and 1. For all of them students_per_counselor is null here; use n_counselors_total (0 means no guidance counselor). The pattern held on every ratio cell except these, where DOE's ratio disagrees with its own counts and is stored as null: " + ("; ".join(ratio_exceptions) if ratio_exceptions else "none") + ".",
        "Suppression and text markers: no FERPA suppression. Ratio cells read 'N/A' where 2024-25 enrollment is 0 (District 88 central sites and 79M984) and are blank for two schools with no staff and no ratio (13K482, 20K413). These are null here. 04M310 (The Judith S. Kaye School) has no counts; its cell reads 'GC and SW counts reflected on 79M331', and its ratios read 'N/A - See note in column D'. Its fields are null.",
        "Benchmark: THE CITY's guide cites the commonly recommended 250 students per counselor, and fewer for high-needs schools. Counselors and social workers do different jobs. Counselors handle academic, college and career guidance; social workers mostly handle mental health. students_per_counselor counts guidance counselors only.",
        "Checks run by the build: summed counts reproduce the file's Total row and the memo's citywide totals (3,296 counselors, 2,049 social workers, 5,345 combined) and the 16 multi-site counselors. Total GC = Full-time GC + Part-time GC on every row.",
        "Coverage: 1,610 DOE school and program rows (districts 1-32, 75, 79 and 88 central sites). Charter schools are not in the report.",
        "Not used: bilingual counselor and social worker counts, yes/no program flags (High Needs, Bridging the Gap, School Response Clinician, Single Shepherd, Future Ready NYC, Pathways Advising and others), the CBO mental-health partner, and the sheets on postsecondary-planning training and demographics.",
    ]

    out = {
        "key": "counselors",
        "title": "Guidance counselors and social workers, 2025-26",
        "source": "NYC Department of Education, Report on Guidance Counselors Pursuant to Local Law 56 of 2014 (Feb. 15, 2026), Appendix A school reporting data (sheet '2025-26 GC & SW Data')",
        "source_url": "https://infohub.nyced.org/reports/government-reports/guidance-counselor-reporting",
        "file_url": "https://infohub.nyced.org/docs/default-source/default-document-library/2025-26---gc-and-sw-report---reporting-spreadsheet-020926.xlsx",
        "vintage": "2025-26 (report dated Feb. 15, 2026; ratios use 2024-25 enrollment)",
        "fetched": "2026-10-07",
        "fields": fields,
        "notes": notes,
        "schools": dict(sorted(schools.items())),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {OUT}: {len(schools)} schools; ratio pattern confirmed on {floor_ok} ratio cells; exceptions: {len(ratio_exceptions)}")
    for e in ratio_exceptions:
        print("   ", e)
    for k, v in cover.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
