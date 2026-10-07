# NYC schools atlas: methodology

Last rebuilt Oct. 7, 2026. This file explains where every number on the map comes from, how the comparisons are made and what the map can't tell you. The full list of measures, with each one's source, year, coverage and definition, is generated from the data in [`MEASURES.md`](MEASURES.md).

The measures follow [Chalkbeat and The City Reporter's Oct. 7, 2026 guide to vetting a New York City public school](https://www.chalkbeat.org/newyork/2026/10/07/how-to-find-nyc-public-schools-parents-guide/). The aim is to put every number that guide recommends, where a school-level file exists for all schools at once, on one screen.

## What's on the map

- **Schools.** 2,445: 1,622 district public, 284 charter and 539 private. Public and charter schools are the ones on the DOE Demographic Snapshot's 2025-26 school tab, which DOE says lists every school open in 2025-26, plus 15K418 (below).
- **Names and addresses** come from DOE's current school list (LCGMS, downloaded Oct. 7, 2026); 144 schools have been renamed since the map's older names. 17 map schools are missing from that list, which usually means they closed, merged or took a new number after 2025-26; their sheets say so.
- **Locations.** Dots for schools already on the map come from the 2019-20 DOE location file. Where DOE's current address differs and NYC Planning's GeoSearch places that exact address more than 75 m away, the dot moves there (69 schools). A move of more than 2 km also needs a second source, either NYC Planning's Facilities Database or Insideschools' listing; 9 charter schools whose current DOE address couldn't be confirmed stay at their earlier location (listed in `data/removed_schools.json`). The 79 schools new since 2019-20 are placed from the Facilities Database (July 2026), matched by name and borough, or from DOE's current address. P.S. Q256 (75Q256), a District 75 school in Syosset, Long Island, sits outside the city at its real address; it had been plotted at the South Pole.
- **Private schools** are the federal Private School Survey's 2023-24 locations (NCES EDGE), names and addresses, replacing the 2021-22 list. The survey only lists schools that respond, so a private school can drop off one edition and return in the next; 132 schools on the old list aren't on the new one, and 139 are new.
- **Removed.** 104 records were dropped because their DBN isn't on the 2025-26 snapshot: closed or merged schools, schools that took a new DBN, evening high schools, District 79 alternative learning centers and hospital and home instruction sites. 61 duplicate records (one school drawn twice at the same point) were collapsed. The removed, added, duplicate, moved and renamed lists are all in `data/removed_schools.json`. One exception is kept: 15K418 The Children's School, which shares a building with District 75's 75K372; DOE reports the building's enrollment under 75K372, but 15K418 has its own 2026 survey results.
- **Attendance zones** are DOE's 2024-25 zones. A shared zone lists several schools; all of them count as zoned (824 public schools zoned, 798 not).
- **Enrollment chart.** One bar per year from 2021-22 to 2025-26, starting at zero, with the count on each bar and the change from the first year to the last written out underneath.
- **Demographics and enrollment.** DOE Demographic Snapshot 2021-22 to 2025-26 (InfoHub, version Aug. 20, 2026). Race, disability, English learner, poverty and Economic Need Index figures are 2025-26. The enrollment line covers 2021-22 to 2025-26. DOE masks poverty and need index values above 95% or below 5%; the map shows those as "over 95%" or "under 5%".
- **Measures.** 35, listed in `MEASURES.md`. Charter schools also show their authorizer (SUNY, the Board of Regents or the NYC schools chancellor), the year the charter opened and links to the authorizer's and the state's pages, from NYSED's charter school directory (Sept. 2, 2025) and its school pages. Ten authorizer links that don't reach the school's own page (a logo image, a generic list, a 404 or a malformed address) are left off. No public file gives each charter's term end date, so that isn't shown. Each comes from a build script in `scripts/metrics/` that reads a raw file saved in `data/sources/` and writes `data/metrics/<key>.json`. `scripts/build_metrics.py` merges them into `data/metrics.json`, which the map reads.

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

**Rank.** For each measure the build records two numbers per school: the share of the other same-level schools with a strictly lower value and the share with a strictly higher value, each rounded down to a whole percent. The sheet's sentences come straight from those (for P.S. 307's performance score, "Lower than 96% of the 926 other elementary schools"; for an elementary school where every responding teacher would recommend it, "Tied for highest" among the elementary schools, because 142 other elementary schools are also at 100%), so they stay literally true when schools tie. Colors, sorting and the top and bottom tenth use the midpoint of the two. Ranks are computed on the same rounded values the map displays. If fewer than 25 same-level schools have the measure, the school is ranked against every school that has it, and the sentence drops the level and just says "schools."

**The bar on each row** is a histogram of every same-level school's value in 24 bins. The range runs from the 1st to the 99th percentile of all schools, so a few extreme values don't flatten it; for percentages that cover most of the scale it runs from 0 to 100%. Values outside the range sit at the edge. The dashed line is the median. The colored mark is the school.

**Colors.** Measures with a direction nobody disputes (attendance, teacher trust in the principal, graduation, students per counselor and so on) are colored on a red-to-blue scale by fifth of the peer group, oriented so blue is always the more favorable end; for chronic absence, vaping and class size, lower is more favorable. Measures with no agreed direction (spending, PTA money, suspensions, enrollment, demographics, building use, CTE exams, special class sizes) use a separate purple scale from lowest to highest, so the color never implies a judgment. The palette was checked for color-blind separation with the dataviz validator.

**"Worth asking about" and "Stands out"** list measures where the school is in the least or most favorable tenth of its peers. "Worth asking about" also lists three benchmarks the guide names or implies:
- more than 250 students per guidance counselor (the guide's recommended ratio), or no guidance counselor at all;
- half or more of teachers not recommending the school (the guide counts 56 such schools in 2026; the data here finds the same 56);
- a school whose enrollment is over 100% of the capacity the School Construction Authority assigns it (the sentence also gives the whole building's figure when the school shares a building).

These are prompts for questions on a tour, not grades.

## Derived measures

Computed here rather than published as such:

- **Impact and performance scores** use DOE's elementary/middle, high school or transfer-school score, whichever matches the school's level. DOE standardizes each within its report type, so the three are never ranked together.
- **English and math proficiency** are spring 2026 for district schools (DOE's school results) and spring 2025 for charter schools (the state's newest bulk file). Scores fell in 2026, so charter schools are ranked only against other charter schools of their level tested in 2025, and their sentences say so.
- **Suspensions per 100 students** = (principal's + superintendent's suspensions, 2024-25) / 2024-25 kindergarten-to-12th-grade enrollment from the Demographic Snapshot x 100; 3-K and pre-K children, who can't be suspended, are left out. DOE redacts counts of 1 to 5; those 713 schools read "Redacted by DOE" and 324 district schools absent from DOE's report read "Not listed in DOE's report." 561 schools have a rate. Charter schools aren't in the report.
- **Classes within the state cap** is DOE's share of non-exempt classes. Exempt classes drop out of the share, so where half or more of a school's classes are exempt (83 schools, including Stuyvesant with 699 of 806), the map shows the exempt count instead.
- **Students per counselor** = 2024-25 enrollment / full- and part-time guidance counselors in 2025-26, as in DOE's report. Where a school has less than one counselor, DOE's file divides by one; the map divides by the actual fraction (0.8 counselors for 656 students is 820). Schools with no counselor say so.
- **PTA money per student** = PTA/PA income / 2024-25 enrollment, both from DOE's Local Law 171 workbook. The figures are self-reported. 321 schools whose report shows zero in every money column are shown that way and not ranked.
- **Enrollment change** = (2025-26 enrollment - 2021-22 enrollment) / 2021-22 enrollment, only where 2021-22 enrollment was at least 20.
- **Space use** is SCA's utilization for the school itself (its enrollment over the seats SCA assigns it). When the school shares a building, the whole building's utilization is shown under "Also on file."
- **Building accessibility** reads DOE's August 2026 Building Accessibility Profile list against the building DOE's current school list gives for the school. DOE leaves inaccessible buildings off the list, so a school whose building isn't listed reads "Not on DOE's accessible-buildings list" rather than "not accessible." The sidebar's "Fully accessible" filter uses this list instead of the 2021 directory tags.
- **Rounding.** Values are stored with enough digits that the page rounds each one only once, so a ratio of 163.46 shows as 163, not 164.

## Insideschools reviews

Insideschools (Advocates for Children of New York) has a page for most schools at `insideschools.org/school/<DBN>`. 989 of them carry a staff-written review: one that opens with "What's Special" or ends with a dated staff byline. Pages with only boilerplate ("This is a zoned, neighborhood school"), a generic summary built from DOE data or a message written by the school itself aren't counted. 964 reviews give a month and year, which the map shows with the link, with any later update.

Because DOE reuses DBNs, a review is linked only when it is the same school: its name matches the map's name, or it matches DOE's current name for that DBN at DOE's current address (the school was renamed), or it matches the name the DBN had on the map before DOE renamed it (11 reviews; the link says "written when the school was called ..."). Five pairs with different spellings of the same name were checked by hand and are listed in `scripts/metrics/build_insideschools.py`. Pages were read once, at about one a second; no review text is stored or shown, since Insideschools' terms bar copying it.

## What's missing, and why

- **Charter schools** are absent from DOE's attendance, class size, counselor, PTA and discipline reports, and DOE posts charter graduation rates separately (not yet up for the Class of 2025). Charters do have survey, spending, enrollment and, where reported, test and quality-report data. Charter and district spending figures are reported by different entities and don't compare cleanly.
- **Transfer high schools** aren't in DOE's attendance file, and their four-year graduation rate is the standard one, not DOE's separate transfer-school rate; they are ranked only against each other.
- **Private schools** report none of these measures.
- **Galaxy budget detail** (librarians, art teachers, therapists by school) and **Budget at a Glance** are per-school web apps with no bulk download; the sheet links to DOE's school pages instead. Per-student spending uses NYSED's school-level spending report for 2024-25, which covers district and charter schools alike.
- **The old DOE framework ratings** (the six framework ratings such as Rigorous Instruction and Trust, plus the overall Student Achievement rating) were retired after 2022-23. DOE now rates three areas, shown under "Also on file": instruction and performance, safety and school climate, and relationships with families. Schools serving grades 6-12 or K-12 get separate middle-grades and high-school ratings; the sheet shows the high-school one and says so. Ten schools now serving high school grades had only a middle-grades report in 2024-25; the sheet shows those ratings labeled as middle grades and leaves their impact and performance scores blank, since they can't be ranked against high schools.
- **Some 2024-25 measures describe the school as it was then.** A few schools have since changed grades; Achievement First Voyager (84K876), for example, was a small middle school in 2024-25 and now serves grades 9-12. A few published values look odd but are DOE's own, such as 0.5% of teachers with three or more years' experience at Nuasin Next Generation Charter School (84X461).
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

## Verification, Oct. 7, 2026

Every number was checked by re-deriving it from the raw files with code written separately from the build: all 1,905 public and charter schools on every measure, plus the demographics, enrollment, school counts and claims in this file. No value differed from its source except by rounding. The checks found meaning and labeling problems, all fixed above: building versus school capacity, exempt classes inflating the cap share, fractional counselors, redacted versus unlisted suspensions, charters' older test year, stale accessibility and location matches, missing shared zones, a school at the South Pole, stale private-school addresses and dead charter links. They also confirmed that DOE's discipline workbook reveals counts its main sheet redacts (its DAYS sheet has no redaction); the map does not use those sheets.

## Corrections

**Oct. 7, 2026: chronic absence was inverted.** From May to October 2026 the map's "chronic absence" figure was the share of students who were not chronically absent. P.S. 188 Kingsbury showed 94%; its real rate is 7%. The source field, DOE's `chronic_absent_ems_all`, is labeled "Percentage of Students with >90% Attendance" in DOE's own metadata, and the file was also mislabeled as 2023-24 end-of-year data when it was the 2024-25 School Quality Report. The May audit (`AUDIT.md`) checked that the numbers matched the file but not what the file measured, and explained the implausible 67% median as a weighting effect. It wasn't. Chronic absence now comes straight from DOE's end-of-year attendance file; the median school is at 37%, close to the citywide 33%.
