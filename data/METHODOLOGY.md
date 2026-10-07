# NYC schools atlas: methodology

Last rebuilt Oct. 7, 2026. This file explains where every number on the map comes from, how the comparisons are made and what the map can't tell you. The full list of measures, with each one's source, year, coverage and definition, is generated from the data in [`MEASURES.md`](MEASURES.md).

The measures follow [Chalkbeat and The City Reporter's Oct. 7, 2026 guide to vetting a New York City public school](https://www.chalkbeat.org/newyork/2026/10/07/how-to-find-nyc-public-schools-parents-guide/). The aim is to put every number that guide recommends, where a school-level file exists for all schools at once, on one screen.

## What's on the map

- **Schools.** Public and charter schools come from the DOE Demographic Snapshot's 2025-26 school tab, which DOE says lists every school open in 2025-26. Locations come from the older DOE location file the map already used, and for 78 schools new since then, from NYC Planning's Facilities Database (Socrata `ji82-xba5`, DOE school records, July 2026), matched by name and borough. One new pre-K center (12X626) had no match and is left off. Private schools are the federal Private School Survey's 2023-24 locations (NCES EDGE, 539 in the city), replacing the 2021-22 list. The survey only lists schools that respond, so a private school can drop off one edition and return in the next; 132 schools on the old list aren't on the new one, and 139 are new.
- **Removed.** 104 records were dropped because their DBN isn't on the 2025-26 snapshot: closed or merged schools, schools that took a new DBN, evening high schools, District 79 alternative learning centers and hospital and home instruction sites. 61 duplicate records (one school drawn twice at the same point) were collapsed. Both lists are in `data/removed_schools.json`. One exception is kept: 15K418 The Children's School, which shares a building with District 75's 75K372; DOE reports the building's enrollment under 75K372, but 15K418 has its own 2026 survey results.
- **Demographics and enrollment.** DOE Demographic Snapshot 2021-22 to 2025-26 (InfoHub, version Aug. 20, 2026). Race, disability, English learner, poverty and Economic Need Index figures are 2025-26. The enrollment line covers 2021-22 to 2025-26. DOE masks poverty and need index values above 95% or below 5%; the map shows those as "over 95%" or "under 5%".
- **Measures.** 35, listed in `MEASURES.md`. Charter schools also show their authorizer (SUNY, the Board of Regents or the NYC schools chancellor), the year they opened and links to the authorizer's and the state's pages, from NYSED's charter school directory (Sept. 2, 2025) and its school pages. No public file gives each charter's term end date, so that isn't shown. Each comes from a build script in `scripts/metrics/` that reads a raw file saved in `data/sources/` and writes `data/metrics/<key>.json`. `scripts/build_metrics.py` merges them into `data/metrics.json`, which the map reads.

## How a school is compared

Every measure is shown against schools of the same **level**, so an elementary school's chronic absence is compared with other elementary schools, not with high schools:

| Level | Rule |
|---|---|
| District 75 | DBN starts with 75 |
| Transfer high | DOE files a transfer-high-school quality report for it |
| Early childhood | serves only 3-K and pre-K |
| High | serves any grade from 9 to 12 (includes 6-12 and K-12 schools) |
| Middle | lowest grade is 5 or higher, highest is 8 or lower |
| Elementary | everything else, including K-8 |

Grades come from the 2025-26 snapshot's grade-by-grade enrollment.

**Percentile.** For each measure, a school's percentile is the share of same-level schools with a lower value, counting ties as half. If fewer than 25 same-level schools have the measure, the school is ranked against every school that has it, and the sheet says so.

**The bar on each row** is a histogram of every same-level school's value (24 bins between the 1st and 99th percentile of all schools, so a few extreme values don't flatten it). The dashed line is the median. The colored mark is the school.

**Colors.** Measures with a direction nobody disputes (attendance, teacher trust in the principal, graduation, students per counselor and so on) are colored on a red-to-blue scale by fifth of the peer group, oriented so blue is always the more favorable end; for chronic absence, vaping and class size, lower is more favorable. Measures with no agreed direction (spending, PTA money, suspensions, enrollment, demographics, building use, CTE exams, special class sizes) use a separate purple scale from lowest to highest, so the color never implies a judgment. The palette was checked for color-blind separation with the dataviz validator.

**"Worth asking about" and "Stands out"** list measures where the school is in the least or most favorable tenth of its peers. "Worth asking about" also lists three benchmarks the guide names or implies:
- more than 250 students per guidance counselor (the guide's recommended ratio), or no guidance counselor at all;
- half or more of teachers not recommending the school (the guide counts 56 such schools in 2026; the data here finds the same 56);
- a building over 100% of its School Construction Authority capacity.

These are prompts for questions on a tour, not grades.

## Derived measures

Computed here rather than published as such:

- **Impact and performance scores** use DOE's elementary/middle, high school or transfer-school score, whichever matches the school's level. DOE standardizes each within its report type, so the three are never ranked together.
- **Suspensions per 100 students** = (principal's + superintendent's suspensions, 2024-25) / 2024-25 enrollment from the Demographic Snapshot x 100. DOE redacts counts of 1 to 5, so a school gets a figure only when both counts are shown; 561 schools have one. Charter schools aren't in DOE's discipline report.
- **Enrollment change** = (2025-26 enrollment - 2021-22 enrollment) / 2021-22 enrollment, only where 2021-22 enrollment was at least 20.
- **PTA money per student** = PTA/PA income / 2024-25 enrollment, both from DOE's Local Law 171 workbook.
- **Students per counselor** is DOE's own ratio, except where a school has less than one counselor; DOE's file shows the whole enrollment as the ratio there, so the map shows "no counselor" or leaves it blank.
- **Building accessibility** comes from DOE's current Building Accessibility Profile list. DOE leaves inaccessible buildings off the list, so a school in DOE's roster whose building isn't listed reads "Not on DOE's accessible-buildings list" rather than "not accessible." The sidebar's "Fully accessible" filter now uses this list instead of the 2021 directory tags.

## What's missing, and why

- **Charter schools** are absent from DOE's attendance, class size, counselor, PTA and discipline reports, and DOE posts charter graduation rates separately (not yet up for the Class of 2025). Charters do have survey, spending, enrollment and, where reported, test and quality-report data.
- **Private schools** report none of these measures.
- **Galaxy budget detail** (librarians, art teachers, therapists by school) and **Budget at a Glance** are per-school web apps with no bulk download; the sheet links to DOE's school pages instead. Per-student spending uses NYSED's school-level spending report for 2024-25, which covers district and charter schools alike.
- **The six old DOE framework ratings** (Rigorous Instruction, Trust and so on) were retired after 2022-23. DOE now rates three areas, shown under "Also on file": instruction and performance, safety and school climate, and relationships with families.
- **Programs and admissions tags** still come from DOE's 2021 school directories.
- **School survey results for students** come from a rewritten 2026 survey that DOE says is a new baseline; don't compare them with earlier years. Elementary schools have no student survey.
- **Proficiency tracks demographics.** Use the impact score, which compares students with similar students elsewhere, to judge what a school adds.

## Rebuilding

```bash
python3 scripts/build_refresh.py          # school list, demographics, enrollment
python3 scripts/metrics/build_<key>.py    # one per source, any order
python3 scripts/build_metrics.py --strict # merge; --strict fails if a source is missing
```

Each per-source script stops with an error if it reads fewer rows than expected or finds an unknown suppression marker, so a broken download can't silently produce an empty map.

## Corrections

**Oct. 7, 2026: chronic absence was inverted.** From May to October 2026 the map's "chronic absence" figure was the share of students who were not chronically absent. P.S. 188 Kingsbury showed 94%; its real rate is 7%. The source field, DOE's `chronic_absent_ems_all`, is labeled "Percentage of Students with >90% Attendance" in DOE's own metadata, and the file was also mislabeled as 2023-24 end-of-year data when it was the 2024-25 School Quality Report. The May audit (`AUDIT.md`) checked that the numbers matched the file but not what the file measured, and explained the implausible 67% median as a weighting effect. It wasn't. Chronic absence now comes straight from DOE's end-of-year attendance file; the median school is at 37%, close to the citywide 33%.
