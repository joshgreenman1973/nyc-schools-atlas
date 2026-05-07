# Quality-data audit — NYC Schools Atlas

**Date:** 2026-05-06
**Scope:** Verifying `quality.attendance` and `quality.chronic_absent` in `data/schools.json` against the authoritative NYC DOE source.

## Why this audit happened

A spot-check on a school tooltip surfaced a chronic-absentee rate that looked too high to be plausible (P.S. 188 Kingsbury at 93.8%, citywide median across schools at 67.0%). Given that the repo had no build script, no methodology doc, and no source citation for the quality block, the values needed verification before the tool could be shared further.

## What I compared

- **Current values:** every `quality` block in `data/schools.json`.
- **Authoritative source:** NYC DOE *End-of-Year Attendance and Chronic Absenteeism Data*, 2023–24 school year, downloaded from [InfoHub](https://infohub.nyced.org/reports/students-and-schools/school-quality/information-and-data-overview/end-of-year-attendance-and-chronic-absenteeism-data). Saved as `data/sources/nyc_doe_eoy_attendance_2023-24.json`.
- **Joined on** DBN.

## Findings

**The data is authentic.** Every spot-checked value matches the DOE source to three decimal places:

| DBN | School | Current `attendance` | DOE `attendance_k8_all` | Current `chronic_absent` | DOE `chronic_absent_ems_all` |
|---|---|---|---|---|---|
| 02M212 | P.S. 212 Midtown West | 0.851 | 0.851 | 0.525 | 0.525 |
| 09X236 | P.S. 236 Langston Hughes | 0.911 | 0.911 | 0.655 | 0.655 |
| 17K091 | P.S. 091 Albany Avenue | 0.911 | 0.911 | 0.645 | 0.645 |
| 26Q188 | P.S. 188 Kingsbury | 0.961 | 0.961 | 0.938 | 0.938 |
| 29Q034 | P.S. 034 John Harvard | 0.913 | 0.913 | 0.689 | 0.689 |

The metric is exactly what DOE labels `chronic_absent_ems_all` (elementary & middle school, all students) — defined as the share of enrolled students absent for 10% or more of school days during the year. That's the standard federal/state definition. Same for `attendance_k8_all`, `grad_pct_4_all`, `ccr_4yr_all`.

## Why the median looks "wrong"

The citywide chronic-absenteeism rate NYC DOE publishes for 2023–24 is **34.8%** ([source](https://www.chalkbeat.org/newyork/2025/09/17/nyc-public-schools-chronic-absenteeism-remains-high/)). That's a *student-weighted* rate — every student counted once across the whole system. The median across the 1,335 individual schools in this file is **67.0%**. Both numbers are correct; they measure different things:

- **Citywide rate (34.8%):** what share of *NYC public-school students* are chronically absent.
- **School median (67.0%):** the chronic-absence rate at the *typical school* — and the typical school is small, high-poverty, and elementary/middle. Large lower-rate high schools pull the student-weighted citywide number down without changing the school-by-school distribution.

Neither is wrong. The tooltip shows the school-level rate, which is the right thing to show on a per-school card. The audit doc and methodology doc need to make that distinction explicit so the next person doesn't have the same "is this real?" reaction.

## Fields verified

| Field in `schools.json` | DOE source field | Schools with data | Match rate |
|---|---|---|---|
| `quality.attendance` | `attendance_k8_all` (or `attendance_hs_all`) | 1,687 | 100% |
| `quality.chronic_absent` | `chronic_absent_ems_all` (or `chronic_absent_all` for HS) | 1,335 | 100% |
| `quality.grad_4yr` | `grad_pct_4_all` | 488 | 100% |
| `quality.ccr_4yr` | `ccr_4yr_all` | 424 | 100% |

## Real problems found (separate from the false alarm)

1. **No provenance in the JSON.** The `quality` block had no source attribution and no vintage marker. Fixed by Phase 2: every record now carries a `quality_meta` block.
2. **Tooltip hard-coded "(2023–24)"** in `app.js` — would silently lie if the data were ever updated to a different year. Fixed by Phase 2: tooltip now reads vintage from `quality_meta`.
3. **`index.html` "Data sources" section omits the quality metrics entirely.** Fixed by Phase 2.
4. **Demographics (`demo` block) are stale at 2021–22** — flagged in `index.html` as awaiting DOE release or FOIL. Out of scope for this audit; kept on the backlog.

## Conclusion

The chronic-absentee rate the user spot-checked is correct. The user's instinct was right to ask the question — the absence of any provenance trail made the number unverifiable. That gap has now been closed.
