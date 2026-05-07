#!/usr/bin/env python3
"""Rebuild the `quality` block in data/schools.json from the authoritative DOE source.

Reads:  data/sources/nyc_doe_eoy_attendance_2023-24.json
        data/schools.json (current file, used as the school roster)

Writes: data/schools.json (in place) — every record gets a refreshed `quality`
        block plus a sibling `quality_meta` block recording vintage, source,
        and fetch date.

Run from repo root:  python3 scripts/build_quality.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHOOLS_PATH = ROOT / "data" / "schools.json"
SOURCE_PATH = ROOT / "data" / "sources" / "nyc_doe_eoy_attendance_2023-24.json"

VINTAGE = "2023-24"
SOURCE_LABEL = "NYC DOE End-of-Year Attendance & Chronic Absenteeism"
SOURCE_URL = "https://infohub.nyced.org/reports/students-and-schools/school-quality/information-and-data-overview/end-of-year-attendance-and-chronic-absenteeism-data"
FETCHED = "2026-05-06"

ATTENDANCE_VARS = {"attendance_k8_all", "attendance_hs_all"}
CHRONIC_VARS = {"chronic_absent_ems_all", "chronic_absent_all"}
GRAD_VAR = "grad_pct_4_all"
CCR_VAR = "ccr_4yr_all"


def to_float(v):
    if v in (None, "", "s"):  # "s" = suppressed for small n in DOE files
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_index(rows):
    idx = {}
    for r in rows:
        dbn = r.get("dbn")
        var = r.get("metric_variable_name")
        if not dbn or not var:
            continue
        idx.setdefault(dbn, {})[var] = to_float(r.get("metric_value"))
    return idx


def quality_for(metrics):
    if not metrics:
        return None
    out = {}
    for v in ATTENDANCE_VARS:
        if metrics.get(v) is not None:
            out["attendance"] = metrics[v]
            break
    for v in CHRONIC_VARS:
        if metrics.get(v) is not None:
            out["chronic_absent"] = metrics[v]
            break
    if metrics.get(GRAD_VAR) is not None:
        out["grad_4yr"] = metrics[GRAD_VAR]
    if metrics.get(CCR_VAR) is not None:
        out["ccr_4yr"] = metrics[CCR_VAR]
    return out or None


def main():
    schools = json.loads(SCHOOLS_PATH.read_text())
    source_rows = json.loads(SOURCE_PATH.read_text())
    idx = build_index(source_rows)

    matched = changed = 0
    for s in schools:
        metrics = idx.get(s.get("dbn"))
        new_q = quality_for(metrics)
        if new_q:
            matched += 1
            if s.get("quality") != new_q:
                changed += 1
            s["quality"] = new_q
            s["quality_meta"] = {
                "vintage": VINTAGE,
                "source": SOURCE_LABEL,
                "source_url": SOURCE_URL,
                "fetched": FETCHED,
            }
        else:
            s["quality"] = None
            s["quality_meta"] = None

    SCHOOLS_PATH.write_text(json.dumps(schools, separators=(", ", ": ")))
    print(f"Schools: {len(schools)}  matched: {matched}  values changed: {changed}")


if __name__ == "__main__":
    main()
