# Methodology: NYC special education due process spending tracker

## What this tracks

Annual New York City spending on due process claims under the federal Individuals with Disabilities Education Act (IDEA), commonly called "Carter cases" in NYC. The umbrella figure includes three distinct payment types that DOE cannot separate in its own books:

- **Carter** — parent fronts private school tuition, then sues for reimbursement after showing DOE failed to offer a Free Appropriate Public Education (FAPE). Based on *Florence County School District Four v. Carter*, 510 U.S. 7 (1993).
- **Connors** — parent cannot front tuition; private school holds a seat on the promise of direct payment from DOE after the hearing. Based on *Connors v. Mills*, 34 F. Supp. 2d 795 (N.D.N.Y. 1998), further entrenched by *Mr. and Mrs. A. ex rel. D.A. v. NYCDOE* (S.D.N.Y. 2011).
- **Pendency / stay-put direct payments** — ongoing tuition obligations for students whose placements were established in prior years and remain active under IDEA's stay-put protections.

The dashboard also shows the split between tuition payments and payments for individual services (speech, occupational therapy, physical therapy, SETSS, paraprofessionals) delivered by private providers.

## Data sources

| Source | What it provides | URL |
|---|---|---|
| NYC Independent Budget Office (IBO) fiscal briefs | Annual spending, forecasts, category notes | [ibo.nyc.ny.us](https://ibo.nyc.ny.us/publicationsEducation.html) |
| NYC Comptroller — *Course Correction* (2023) | FY2012–FY2023 tuition/services split | [comptroller.nyc.gov](https://comptroller.nyc.gov/reports/course-correction/) |
| NYS Comptroller (OSC) — NYC DOE issue brief | FY2023 total, trend analysis | [osc.ny.gov](https://www.osc.ny.gov/files/reports/osdc/pdf/nyc-doe-issue-brief.pdf) |
| City Council Committee on Education testimony | DOE General Counsel on Carter/Connors data limits (March 13, 2025) | [citymeetings.nyc](https://citymeetings.nyc/meetings/new-york-city-council/2025-03-13-1000-am-committee-on-education/chapter/challenges-in-separating-spending-between-carter-and-connors-cases/) |
| Mayor's Management Report | Case counts, hearing timeliness | nyc.gov/site/operations/performance/mmr |
| Manhattan Institute — Weber report | Historical compilation of pre-2012 figures | [manhattan.institute](https://manhattan.institute/article/reassessing-carter-case-spending-for-students-with-disabilities-in-new-york-city-schools) |

## Figures used and how they reconcile

| Fiscal year | Spending | Source used | Notes |
|---|---|---|---|
| FY2005 | $47M | Weber compilation | Traces to earlier IBO/DOE reporting; not independently re-verified against IBO source documents |
| FY2010 | ~$143M | Weber compilation | Same caveat |
| FY2012 | $161M | Comptroller *Course Correction* | Tuition 74% ($119M), services 21% ($33M), other 5% |
| FY2015 | ~$250M | IBO | First full year after September 2014 settlement reform |
| FY2016 | ~$312M | Weber / IBO | |
| FY2020 | $499M | Weber / IBO | |
| FY2021 | $807M | OSC retrospective | **Reconciliation note:** IBO's March 2021 fiscal brief reported $653M for FY2021 in-year, including a $220M mid-year addition for prior-year settlements. OSC's later retrospective accounting puts actuals at $807M. Both figures are defensible; the dashboard uses the retrospective actual. |
| FY2022 | $918M | Comptroller *Course Correction* | Tuition share falling; services rising to 41% of total |
| FY2023 | $1,070M | OSC | Services rose to 58% of year-to-date payments by mid-FY2023 per Comptroller |
| FY2024 | ~$1,200M | DOE Council testimony | |
| FY2025 | $1,300M | Reporting, matches IBO projections | Flagged as unbudgeted need in early Mamdani administration fiscal statements |
| FY2026 | ~$1,300M | DOE budget | Projected |
| FY2027 | ~$1,500M | DOE budget | Projected |

## Per-student and comparative figures

- **$101,757** — average Carter-case settlement per student, FY2024. Roughly 3× the citywide per-pupil general-education spending.
- **~60%** — NYC share of all IDEA due process filings in the United States, FY2021, per the Center for Appropriate Dispute Resolution in Special Education (CADRE).
- **517 filings per 10,000 students** — New York State's filing rate, highest in the nation, with NYC accounting for essentially all of it.
- **98%** — NYC's share of New York State due process filings, against 36% of the state's student population.

## What we cannot show

These are not evasions — they are real limits of the public data:

- **Carter vs. Connors split.** DOE testified in March 2025 that direct payments are used for both Connors cases and for Carter pendency, and the system cannot distinguish them. This means the original equity promise of Connors — direct funding for families without means — cannot be empirically evaluated from public records.
- **School-by-school distribution.** No public accounting of how Carter dollars are distributed across private schools. Anecdotally concentrated in a small set of schools (Rebecca, Cooke, Stephen Gaynor, Mary McDowell, Gateway, Parkside, Churchill, Windward) but unverified.
- **Filing family demographics.** Income, race, neighborhood, counsel retention — none published.
- **Outcomes.** Private schools receiving IDEA payments are not required to report academic, behavioral, or post-secondary outcomes for these students.
- **In-house capacity.** No published dataset on District 75 seat availability, ICT seat availability, or related-service provider staffing by district and year.

## Policy inflection points marked in the chart

- **FY2015** — de Blasio administration's September 2014 settlement reform: 15-day settlement target, no re-litigation of prior settled cases, reduced paperwork.
- **FY2022** — OATH begins taking over impartial hearings from DOE to address backlog; court-appointed special master under *L.V. v. NYC DOE* overseeing basic operational fixes.
- **FY2025** — Flagged by the Mamdani administration as one of six major unbudgeted needs contributing to the projected $5.4B budget deficit.

## Assumptions and known limitations

- All figures are nominal, not inflation-adjusted. A real-dollar view would flatten part (but not most) of the growth curve.
- Figures for FY2005, FY2010, FY2016 lean on the Manhattan Institute compilation rather than primary IBO documents. These should be re-verified against IBO's original releases before any published reporting relies on them.
- "Budgeted" projections for FY2026–FY2027 are the city's own and historically have under-estimated actuals by wide margins.
- Case counts reported in the Mayor's Management Report count filings, not unique students; a single student can generate multiple filings across years.

## Update cadence

IBO, the Comptroller, and OSC publish on irregular schedules. Expect updates to this tracker roughly quarterly, with the fiscal year close (June 30) followed by the Comptroller's Comments on the Adopted Budget (July/August) as the main refresh point. The Mayor's Management Report lands in September (preliminary) and February (update).

## Schools section: sources and caveats

The "where the money goes" table lists private schools widely cited in legal guides, journalism, and City Council testimony as enrolling students placed under Carter or Connors. Inclusion is based on public reputation, not on any official DOE payee list — no such list is public. Tuition figures are from each school's own website or from privateschoolreview.com / findingschool.com listings, cross-checked where possible.

Published tuition is **not the same as the Carter settlement amount DOE pays**. Settlements commonly include related services (speech, occupational therapy, physical therapy, counseling), one-to-one paraprofessionals or shadows, transportation, legal fees, and expert evaluations on top of base tuition. The FY2024 average Carter settlement of $101,757 exceeds most published tuitions on the list, which is consistent with this bundling.

Several schools explicitly acknowledge serving this population. The Gateway School's admissions materials state that "most families pursue reimbursement and/or direct payment of tuition through the Department of Education." Mary McDowell Friends School's tuition and affordability page discusses Carter and Connors funding as a pathway. Churchill, Stephen Gaynor, and Windward all discuss the due process process with prospective families.

Schools on the list but with no published tuition (Rebecca School) are included because they are repeatedly cited in Carter case law, State Review Officer decisions, and prior reporting.

**FOIL target.** A request to DOE for payee-level tuition disbursements — school name, fiscal year, number of students, total paid — would make the school-by-school distribution public for the first time. This appears not to have been published by any outlet.

## For further reporting

The most valuable open question this tracker cannot answer: **which private schools are receiving what share of Carter spending, and could those programs be replicated or contracted directly?** A FOIL request to DOE for payee-level tuition disbursements by school by fiscal year would support either a cost-control or an "operate it as the de facto system it has become" argument. No such analysis appears to have been published.
