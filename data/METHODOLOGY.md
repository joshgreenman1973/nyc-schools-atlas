# NYC Schools Atlas — methodology

This document records, field by field, where every value in `data/schools.json` comes from. If a number appears anywhere in the atlas, you should be able to trace it back through this document to a public source.

If something in the live tool ever conflicts with this document, this document is the source of truth — file an issue and the data will be regenerated from the source files in `data/sources/`.

## How to verify any number in the atlas

1. Open the school's tooltip — note the metric, the value, and the vintage shown.
2. Look up the field name below to find the source dataset and the source field name.
3. Open the matching CSV/JSON in `data/sources/`, filter on `dbn`, and confirm.

## Data dictionary

### Top-level fields

| Field | Type | Source | Vintage | Notes |
|---|---|---|---|---|
| `dbn` | string | NYC DOE School Locations (Socrata `a3nt-yts4`) | 2024–25 | Borough + district + school code. Primary key for joining to all DOE data. |
| `name`, `address`, `zip`, `boro`, `district`, `lat`, `lon` | strings/floats | NYC DOE School Locations (`a3nt-yts4`) for public/charter; NCES EDGE Geocoded Private Schools 2021–22 for private | 2024–25 / 2021–22 | |
| `sector` | enum | Derived: `public` from DOE; `charter` from DOE charter list; `private` from NCES | — | |
| `grades`, `website`, `overview`, `programs`, `admission`, `admission_programs` | various | NYC DOE 2021 directories (HS `8b6c-7uty`, MS `f6s7-vytj`, K `e7es-jx5j`) | 2021 | Program tags extracted from directory narratives. Not exhaustive. |
| `has_zone` | bool | Derived from NYC DOE School Zones 2024–25 (`cmjf-yawu`, `t26j-jbq7`) | 2024–25 | |

### `demo` block — student demographics

**Source:** NYC DOE *2017–18 to 2021–22 Demographic Snapshot* (Socrata `c7ru-d68s`).
**Vintage:** 2021–22 (the latest year DOE publishes on Open Data as of 2026-05-06).
**Known limitation:** Demographics are 4 years stale. DOE has more recent data internally; a FOIL request would unlock 2024–25. Tracked on the backlog.

| Field | DOE source field | Definition |
|---|---|---|
| `enrollment` | `total_enrollment` | Headcount, 2021–22. |
| `pct_asian`, `pct_black`, `pct_hispanic`, `pct_white`, `pct_multi`, `pct_native` | `% Asian`, `% Black`, etc. | Decimal share, 0–1. |
| `pct_female`, `pct_male` | `% Female`, `% Male` | Decimal share. |
| `pct_swd` | `% Students with Disabilities` | |
| `pct_ell` | `% English Language Learners` | |
| `poverty` | `% Poverty` | Percent (0–100). |
| `eni` | `Economic Need Index` | DOE's composite poverty/need score. Higher = higher need. |
| `enrollment_latest`, `year_enrollment` | NYSED BEDS | More recent enrollment from NYSED (see next section), tacked onto the same block for convenience. |

### `trend` array — six-year enrollment

**Source:** NYSED BEDS Day Enrollment database (`data.nysed.gov`).
**Vintage:** 2019–20 through 2024–25.
**Format:** `[["2019-20", 368], ["2020-21", 331], ...]`

NYSED publishes BEDS Day enrollment on a roughly one-year lag and is the most current source available without a FOIL request.

### `quality` block — outcomes (Phase 2 audit, May 2026)

**Source:** NYC DOE *End-of-Year Attendance and Chronic Absenteeism Data* and the matching graduation / college-readiness files, downloaded from [NYC DOE InfoHub](https://infohub.nyced.org/reports/students-and-schools/school-quality/information-and-data-overview/end-of-year-attendance-and-chronic-absenteeism-data). Raw file: `data/sources/nyc_doe_eoy_attendance_2023-24.json`. Build script: `scripts/build_quality.py`.
**Vintage:** 2023–24 school year.
**Per-school provenance:** every school with a `quality` block also has a `quality_meta` block recording `vintage`, `source`, `source_url`, and `fetched`. The tooltip reads `quality_meta.vintage` directly so the displayed year can never drift from the underlying data.

| Field | DOE source field | Definition |
|---|---|---|
| `attendance` | `attendance_k8_all` (or `attendance_hs_all` for high schools) | Average daily attendance rate, all students, decimal 0–1. |
| `chronic_absent` | `chronic_absent_ems_all` (or `chronic_absent_all` for high schools) | Share of enrolled students absent for **10% or more** of school days during the year. Federal/state standard definition. Decimal 0–1. |
| `grad_4yr` | `grad_pct_4_all` | Four-year graduation rate, all students, decimal 0–1. High schools only. |
| `ccr_4yr` | `ccr_4yr_all` | College & career readiness rate, all students, percent (0–100). High schools only. |

#### Why the school-by-school median looks higher than the citywide rate

The citywide chronic-absenteeism rate NYC DOE reports for 2023–24 is **34.8%** ([Chalkbeat coverage](https://www.chalkbeat.org/newyork/2025/09/17/nyc-public-schools-chronic-absenteeism-remains-high/)). The median across the 1,335 individual schools in this file is **67.0%**. Both numbers are correct; they measure different things.

- The **citywide rate** is student-weighted: every NYC public-school student counts once, so large lower-rate schools (most high schools) pull the average down.
- The **per-school median** treats every school equally, regardless of size. Most schools are small elementary/middle schools in higher-poverty areas, where chronic absence runs much higher.

When a tooltip shows a school's chronic-absence rate, that's the rate at *that specific school*, computed by DOE — not the citywide rate. A high number is not a data error; it reflects real conditions at that school.

### `quality_meta` block (added Phase 2)

Per-school provenance for the `quality` block. Schema:

```json
{
  "vintage": "2023-24",
  "source": "NYC DOE End-of-Year Attendance & Chronic Absenteeism",
  "source_url": "https://infohub.nyced.org/...",
  "fetched": "2026-05-06"
}
```

`null` if the school has no quality data (charters that don't report, private schools, very small programs, suppressed cells where n<5).

## Reproducing this build

All source files live in `data/sources/`. To rebuild `data/schools.json` from those sources:

```bash
python3 scripts/build_quality.py
```

The script joins on DBN, replaces every school's `quality` block, and stamps `quality_meta` on every record. Idempotent — run it as many times as you like.

## Audit history

- **2026-05-06** — Quality block audited against the authoritative DOE source after a tooltip spot-check. Values verified to match DOE 2023–24 EOY Attendance file 100%. `quality_meta` provenance block added. Full audit notes in `data/AUDIT.md`.

## Backlog (known data gaps)

- **Demographics are 2021–22.** Awaiting DOE Open Data update or a FOIL release of the 2024–25 snapshot.
- **Per-pupil spending** not included — DOE School Based Expenditure Report is not on Open Data in a usable form.
- **Programs and admissions** are 2021 directories — DOE has stopped publishing the K admissions guide annually.
- **Notable alumni** surfaced via Wikipedia link only, not bulk-scraped.
