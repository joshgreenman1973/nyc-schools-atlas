#!/usr/bin/env python3
"""Build data/metrics/sqr.json from the NYC DOE School Quality Reports (SQR),
2024-25 "SQR: Citywide Results" Excel files.

Raw files (unmodified downloads, in data/sources/), all from
https://infohub.nyced.org/reports/students-and-schools/school-quality/school-quality-reports-and-resources
(the "Citywide Results" links; older years are on the .../school-quality-reports-citywide-results page):

  nyc_doe_sqr_ems_2024-25.xlsx  <- .../default-document-library/202425-ems-sqr-results.xlsx  (elementary, middle, K-8)
  nyc_doe_sqr_hs_2024-25.xlsx   <- .../default-document-library/202425-hs-sqr-results.xlsx   (high schools)
  nyc_doe_sqr_hst_2024-25.xlsx  <- .../default-document-library/202425-hst-sqr-results.xlsx  (transfer high schools)
  nyc_doe_sqr_ec_2024-25.xlsx   <- .../default-document-library/202425-ec-sqr-results.xlsx   (early childhood, K-1/K-2/K-3)
  nyc_doe_sqr_d75_2024-25.xlsx  <- .../default-document-library/202425-d75-sqr-results.xlsx  (District 75)

Definitions are quoted or paraphrased from the 2024-25 Educator Guides, saved alongside as
nyc_doe_sqr_educator_guide_{ems,hs,hst,ec,d75}_2024-25.pdf, plus
nyc_doe_sqr_final_changes_2024-25.pdf and nyc_doe_sqr_faq_comp_group_impact_score.pdf.

Layout of every sheet: title in B2, column headers in row 4, a blank row 5, data from row 6.
Column D is the DBN. Columns are looked up by exact header text, never by position.

A DBN can appear in more than one report (144 schools serving grades 6-12 or K-12 have both
an EMS and an HS report). Report-specific measures (impact/performance scores, category
ratings and scores) are therefore prefixed ems_/hs_/hst_. School-wide measures (teacher
experience, IEP services, survey percent positive) are taken once; the script checks that
when both reports carry a value they are identical, and raises if they ever differ.

Suppression / non-value markers in the files: "" (blank), "N/A", "N<5", "N<10", "N<15",
and the top-code "> 95%" (appears only in Economic Need Index and Percent HRA Eligible,
neither of which is taken). All become null. Any other non-numeric text in a numeric
field raises.

Run from anywhere:  python3 scripts/metrics/build_sqr.py
"""
import json
import os
import re

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC_DIR = os.path.join(ROOT, "data", "sources")
OUT = os.path.join(ROOT, "data", "metrics", "sqr.json")

FETCHED = "2026-10-07"
VINTAGE = "2024-25"
LANDING = "https://infohub.nyced.org/reports/students-and-schools/school-quality/school-quality-reports-and-resources"
FILE_BASE = "https://infohub.nyced.org/docs/default-source/default-document-library/"

REPORTS = {
    # report_type: (local file, remote file, minimum expected school rows)
    "EMS": ("nyc_doe_sqr_ems_2024-25.xlsx", "202425-ems-sqr-results.xlsx", 1300),  # file has 1,362
    "HS": ("nyc_doe_sqr_hs_2024-25.xlsx", "202425-hs-sqr-results.xlsx", 490),      # file has 506
    "HST": ("nyc_doe_sqr_hst_2024-25.xlsx", "202425-hst-sqr-results.xlsx", 50),    # file has 57
    "EC": ("nyc_doe_sqr_ec_2024-25.xlsx", "202425-ec-sqr-results.xlsx", 25),       # file has 31
    "D75": ("nyc_doe_sqr_d75_2024-25.xlsx", "202425-d75-sqr-results.xlsx", 55),    # file has 62
}
REPORT_ORDER = ["EMS", "HS", "HST", "EC", "D75"]

DBN_RE = re.compile(r"^\d{2}[MXKQR]\d{3}$")
SUPPRESSED = {"", "N/A", "N<5", "N<10", "N<15", "> 95%"}
RATINGS = ["Needs Improvement", "Fair", "Good", "Excellent"]

# ---------------------------------------------------------------------------
# Field specs: (field, sheet, exact header, kind)
# kind: pct (0-1 decimal, checked), num (number), rating (one of RATINGS)
# ---------------------------------------------------------------------------
P = "Percentage of students with IEPs receiving "
SCHOOLWIDE = [
    ("pct_teachers_3plus_years", "Summary", "Percent of teachers with 3 or more years of experience", "pct"),
    ("iep_all_programs_pct", "Summary", P + "all recommended special education programs", "pct"),
    ("iep_all_related_services_pct", "Summary", P + "all recommended related services", "pct"),
    ("survey_instruction_pct", "Summary", "Instruction/Learning Environment - School Percent Positive", "pct"),
    ("survey_iep_satisfaction_pct", "Summary", "Students with IEPs: IEP Service Satisfaction - School Percent Positive", "pct"),
    ("survey_advising_pct", "Summary", "Advising and Planning - School Percent Positive", "pct"),
    ("survey_safety_pct", "Summary", "Safety - School Percent Positive", "pct"),
    ("survey_leadership_pct", "Summary", "School Leadership - School Percent Positive", "pct"),
    ("survey_student_support_pct", "Summary", "Student Support - School Percent Positive", "pct"),
    ("survey_teaching_env_pct", "Summary", "Teaching Environment - School Percent Positive", "pct"),
    ("survey_communication_pct", "Summary", "Communication - School Percent Positive", "pct"),
    ("survey_family_involvement_pct", "Summary", "Family Involvement - School Percent Positive", "pct"),
    ("survey_family_trust_pct", "Summary", "Family-School Trust - School Percent Positive", "pct"),
]


def rated(prefix):
    """Impact/performance scores and the three category ratings + scores (EMS, HS, HST)."""
    return [
        (prefix + "impact_score", "Summary", "Impact Score", "num"),
        (prefix + "performance_score", "Summary", "Performance Score", "num"),
        (prefix + "ip_rating", "Summary", "Instruction and Performance - Rating", "rating"),
        (prefix + "ip_score", "Scoring", "Instruction and Performance - Score", "num"),
        (prefix + "ssc_rating", "Summary", "Safety and School Climate - Rating", "rating"),
        (prefix + "ssc_score", "Scoring", "Safety and School Climate - Score", "num"),
        (prefix + "rwf_rating", "Summary", "Relationships with Families - Rating", "rating"),
        (prefix + "rwf_score", "Scoring", "Relationships with Families - Score", "num"),
    ]


ADV = [
    ("adv_any_enrolled_pct", "Summary", "Percentage of Students Enrolled in Any Advanced Course", "pct"),
    ("adv_ap_enrolled_pct", "Summary", "Percentage of Students Enrolled in an AP Course", "pct"),
    ("adv_ib_enrolled_pct", "Summary", "Percentage of Students Enrolled in an IB Course", "pct"),
    ("adv_clep_enrolled_pct", "Summary", "Percentage of Students Enrolled in a College Level Examination Program (CLEP)", "pct"),
    ("adv_college_credit_enrolled_pct", "Summary", "Percentage of Students Enrolled in a College Credited Course", "pct"),
    ("adv_cpcc_enrolled_pct", "Summary", "Percentage of Students Enrolled in an NYCPS-certified College Preparatory Course", "pct"),
    ("adv_mathsci_enrolled_pct", "Summary", "Percentage of Students Enrolled in an Advanced Math or Science Course", "pct"),
]

IP = "Instruction and Performance"
AI = "Additional Info"
SPEC = {
    "EMS": SCHOOLWIDE + rated("ems_") + [
        ("ela_prof_pct", IP, "Metric Value - Percentage of Students at Level 3 or 4, ELA", "pct"),
        ("math_prof_pct", IP, "Metric Value - Percentage of Students at Level 3 or 4, Math", "pct"),
        ("ela_avg_prof", IP, "Metric Value - Average Student Proficiency, ELA", "num"),
        ("math_avg_prof", IP, "Metric Value - Average Student Proficiency, Math", "num"),
    ],
    "HS": SCHOOLWIDE + rated("hs_") + ADV + [
        ("hs_grad_4yr_pct", IP, "Metric Value - 4-Year Graduation Rate - All Students", "pct"),
        ("hs_grad_6yr_pct", IP, "Metric Value - 6-Year Graduation Rate - All Students", "pct"),
        ("hs_ccr_4yr", IP, "Metric Value - 4-Year College and Career Readiness - All Students", "num"),
        ("hs_ccr_6yr", IP, "Metric Value - 6-Year College and Career Readiness - All Students", "num"),
        ("hs_ccpci_pct", IP, "Metric Value - College and Career Preparatory Course Index", "pct"),
        ("hs_ap_3plus_pct", AI, "Metric Value - % Scoring 3+ on any AP Exam", "pct"),
        ("hs_ib_4plus_pct", AI, "Metric Value - % Scoring 4+ on any IB Exam", "pct"),
        ("hs_college_credit_c_pct", AI, "Metric Value - % Earning a Grade of 'C' or Higher for College Credit", "pct"),
        ("hs_cpcc_pass_pct", AI, "Metric Value - % Passing a NYCPS-certified CPCC Course", "pct"),
        ("hs_alg2_chem_phys_65_pct", AI, "Metric Value - % Scoring 65+ on Alg2, Chem, or Phys Regents Exam", "pct"),
        ("hs_industry_assessment_pct", AI, "Metric Value - % Passing an Industry-Recognized Technical Assessment", "pct"),
        ("hs_cte_endorsement_pct", AI, "Metric Value - % Earning a Diploma with a CTE Endorsement", "pct"),
    ],
    "HST": SCHOOLWIDE + rated("hst_") + ADV + [
        ("hst_grad_pct", IP, "Metric Value - Transfer School Graduation Rate", "pct"),
        ("hst_ccr", AI, "Metric Value - Transfer School College and Career Readiness - All Students", "num"),
        ("hst_ccr_growth_pct", IP, "Metric Value - Growth in Transfer School College and Career Readiness - All Students", "pct"),
        ("hst_ccpci_pct", IP, "Metric Value - College and Career Preparatory Course Index", "pct"),
        ("hst_industry_assessment_pct", AI, "Metric Value - % Passing an Industry-Recognized Technical Assessment", "pct"),
    ],
    "EC": SCHOOLWIDE + [
        ("ela_prof_pct", AI, "Metric Value - Percentage of Students at Level 3 or 4, ELA", "pct"),
        ("math_prof_pct", AI, "Metric Value - Percentage of Students at Level 3 or 4, Math", "pct"),
        ("ela_avg_prof", AI, "Metric Value - Average Student Proficiency, ELA", "num"),
        ("math_avg_prof", AI, "Metric Value - Average Student Proficiency, Math", "num"),
    ],
    "D75": SCHOOLWIDE,
}
SCHOOLWIDE_FIELDS = {f for f, *_ in SCHOOLWIDE}

FIELD_META = {
    "report_type": dict(label="SQR report(s)", unit="text", direction="neutral",
        source_field="which of the five citywide files the DBN appears in",
        definition="Which School Quality Report(s) DOE issued for this school in 2024-25: EMS (elementary, middle, K-8), HS (high school), HST (transfer high school), EC (early childhood), D75 (District 75). Schools serving grades 6-12 or K-12 get two reports, written \"EMS+HS\"."),
    "school_type": dict(label="SQR school type", unit="text", direction="neutral",
        source_field="School Type (Summary sheet, each file)",
        definition="DOE's school-type label on the report (Elementary, Middle, K-8, High School, High School Transfer, K-1, K-2, K-3, D75). Two-report schools are joined with \" + \". Impact and performance scores are standardized within school type."),
    "pct_teachers_3plus_years": dict(label="Teachers with 3+ years' experience", unit="pct", direction="higher",
        source_field="Percent of teachers with 3 or more years of experience (Summary sheet, all five files)",
        definition="Percent of teachers with 3 or more years of experience (DOE column label; the 2024-25 Educator Guides give no further definition)."),
    "iep_all_programs_pct": dict(label="IEP students fully receiving special-ed programs", unit="pct", direction="higher",
        source_field="Percentage of students with IEPs receiving all recommended special education programs (Summary sheet, all five files)",
        definition="Of students with IEPs as of June 2025 whose IEP recommends a special education program (Special Class, Integrated Co-Teaching or SETSS), the share \"fully receiving\": DOE counts a student as fully receiving \"if there is an exact match between the IEP and the course enrollment in the STARS scheduling system.\" (2024-25 EMS Educator Guide.)"),
    "iep_all_related_services_pct": dict(label="IEP students fully receiving related services", unit="pct", direction="higher",
        source_field="Percentage of students with IEPs receiving all recommended related services (Summary sheet, all five files)",
        definition="Of students with IEPs whose IEP recommends related services (speech, occupational or physical therapy, counseling and the like), the share whose received services \"match all of the recommended services.\" (2024-25 EMS Educator Guide.)"),
    "survey_instruction_pct": dict(label="Survey: instruction/learning environment (% positive)", unit="pct", direction="higher",
        source_field="Instruction/Learning Environment - School Percent Positive (Summary sheet)",
        definition="Percent of positive responses to NYC School Survey questions DOE maps to the Instruction/Learning Environment measure; the survey subcategory inside the Instruction and Performance category."),
    "survey_iep_satisfaction_pct": dict(label="Survey: IEP service satisfaction (% positive)", unit="pct", direction="higher",
        source_field="Students with IEPs: IEP Service Satisfaction - School Percent Positive (Summary sheet)",
        definition="Percent of positive responses to NYC School Survey questions on services for students with IEPs (part of the Instruction and Performance category)."),
    "survey_advising_pct": dict(label="Survey: advising and planning (% positive)", unit="pct", direction="higher",
        source_field="Advising and Planning - School Percent Positive (Summary sheet)",
        definition="Percent positive on NYC School Survey questions mapped to Advising and Planning (Safety and School Climate category)."),
    "survey_safety_pct": dict(label="Survey: safety (% positive)", unit="pct", direction="higher",
        source_field="Safety - School Percent Positive (Summary sheet)",
        definition="Percent positive on NYC School Survey questions mapped to Safety (Safety and School Climate category)."),
    "survey_leadership_pct": dict(label="Survey: school leadership (% positive)", unit="pct", direction="higher",
        source_field="School Leadership - School Percent Positive (Summary sheet)",
        definition="Percent positive on NYC School Survey questions mapped to School Leadership (Safety and School Climate category)."),
    "survey_student_support_pct": dict(label="Survey: student support (% positive)", unit="pct", direction="higher",
        source_field="Student Support - School Percent Positive (Summary sheet)",
        definition="Percent positive on NYC School Survey questions mapped to Student Support (Safety and School Climate category)."),
    "survey_teaching_env_pct": dict(label="Survey: teaching environment (% positive)", unit="pct", direction="higher",
        source_field="Teaching Environment - School Percent Positive (Summary sheet)",
        definition="Percent positive on NYC School Survey questions mapped to Teaching Environment (Safety and School Climate category)."),
    "survey_communication_pct": dict(label="Survey: communication with families (% positive)", unit="pct", direction="higher",
        source_field="Communication - School Percent Positive (Summary sheet)",
        definition="Percent positive on NYC School Survey questions mapped to Communication (Relationships with Families category)."),
    "survey_family_involvement_pct": dict(label="Survey: family involvement (% positive)", unit="pct", direction="higher",
        source_field="Family Involvement - School Percent Positive (Summary sheet)",
        definition="Percent positive on NYC School Survey questions mapped to Family Involvement (Relationships with Families category)."),
    "survey_family_trust_pct": dict(label="Survey: family-school trust (% positive)", unit="pct", direction="higher",
        source_field="Family-School Trust - School Percent Positive (Summary sheet)",
        definition="Percent positive on NYC School Survey questions mapped to Family-School Trust (Relationships with Families category); DOE builds it from Parent-Principal Trust and Parent-Teacher Trust measures."),
    "ela_prof_pct": dict(label="ELA proficient (Level 3-4)", unit="pct", direction="higher",
        source_field="Metric Value - Percentage of Students at Level 3 or 4, ELA (EMS: Instruction and Performance sheet; EC: Additional Info sheet)",
        definition="\"The percentage of students who scored at Level 3 or Level 4 on the State exam, out of all the students at the school who took the exam\" (2025 State ELA test, grades 3-8; students on the Oct. 31, 2024 audited register). EMS and EC reports."),
    "math_prof_pct": dict(label="Math proficient (Level 3-4)", unit="pct", direction="higher",
        source_field="Metric Value - Percentage of Students at Level 3 or 4, Math (EMS: Instruction and Performance sheet; EC: Additional Info sheet)",
        definition="Same as ELA, for the 2025 State math test. DOE folds in math Regents results for 7th and 8th graders who took a Regents instead of the grade-level test, converted to \"imputed proficiency ratings.\" EMS and EC reports."),
    "ela_avg_prof": dict(label="Average ELA proficiency rating (1.00-4.50)", unit="number", direction="higher",
        source_field="Metric Value - Average Student Proficiency, ELA (EMS: Instruction and Performance sheet; EC: Additional Info sheet)",
        definition="Average Proficiency Rating on DOE's 1.00-4.50 scale for all students who took the 2025 State ELA exam; the first digit is the performance level (e.g. 2.90 is a high Level 2)."),
    "math_avg_prof": dict(label="Average math proficiency rating (1.00-4.50)", unit="number", direction="higher",
        source_field="Metric Value - Average Student Proficiency, Math (EMS: Instruction and Performance sheet; EC: Additional Info sheet)",
        definition="Average Proficiency Rating on DOE's 1.00-4.50 scale for all students who took the 2025 State math exam (with the Regents imputation described under math_prof_pct)."),
    "adv_any_enrolled_pct": dict(label="Enrolled in any advanced course", unit="pct", direction="higher",
        source_field="Percentage of Students Enrolled in Any Advanced Course (Summary sheet, HS and HST files)",
        definition="Share of students enrolled, as of Oct. 31, 2024, in at least one credit-bearing advanced course: AP, IB, CLEP, a college-credit course, a DOE-certified college preparatory (CPCC) course, or other advanced math/science (Algebra II, Calculus, Chemistry, Physics). The guide does not state the denominator; for 02M475 the Snapshot shows \"2776 (85%)\" against 3,266 enrolled, i.e. school enrollment."),
    "adv_ap_enrolled_pct": dict(label="Enrolled in an AP course", unit="pct", direction="higher",
        source_field="Percentage of Students Enrolled in an AP Course (Summary sheet, HS and HST files)",
        definition="Share of students enrolled in an Advanced Placement course (course code sixth character \"X\") as of Oct. 31, 2024."),
    "adv_ib_enrolled_pct": dict(label="Enrolled in an IB course", unit="pct", direction="higher",
        source_field="Percentage of Students Enrolled in an IB Course (Summary sheet, HS and HST files)",
        definition="Share of students enrolled in an International Baccalaureate course (course code sixth character \"B\") as of Oct. 31, 2024."),
    "adv_clep_enrolled_pct": dict(label="Enrolled in CLEP", unit="pct", direction="higher",
        source_field="Percentage of Students Enrolled in a College Level Examination Program (CLEP) (Summary sheet, HS and HST files)",
        definition="Share of students enrolled in College Board College Level Examination Program coursework as of Oct. 31, 2024."),
    "adv_college_credit_enrolled_pct": dict(label="Enrolled in a college-credit course", unit="pct", direction="higher",
        source_field="Percentage of Students Enrolled in a College Credited Course (Summary sheet, HS and HST files)",
        definition="Share of students enrolled in a college course that awards credit (course code sixth character \"U\"; e.g. College Now, early college) as of Oct. 31, 2024."),
    "adv_cpcc_enrolled_pct": dict(label="Enrolled in a DOE-certified college prep course", unit="pct", direction="higher",
        source_field="Percentage of Students Enrolled in an NYCPS-certified College Preparatory Course (Summary sheet, HS and HST files)",
        definition="Share of students enrolled in a course approved for College Preparatory Course Certification (CPCC) for the report year, as of Oct. 31, 2024."),
    "adv_mathsci_enrolled_pct": dict(label="Enrolled in other advanced math/science", unit="pct", direction="higher",
        source_field="Percentage of Students Enrolled in an Advanced Math or Science Course (Summary sheet, HS and HST files)",
        definition="Share of students enrolled in Algebra II, Calculus, Chemistry or Physics courses that are not already counted as AP, IB, college credit or CPCC, as of Oct. 31, 2024."),
    "hs_grad_4yr_pct": dict(label="4-year graduation rate", unit="pct", direction="higher",
        source_field="Metric Value - 4-Year Graduation Rate - All Students (HS file, Instruction and Performance sheet)",
        definition="Share of the school's four-year cohort (entered high school 2021-22, Class of 2025) that graduated with a Regents or Local Diploma, including August graduates."),
    "hs_grad_6yr_pct": dict(label="6-year graduation rate", unit="pct", direction="higher",
        source_field="Metric Value - 6-Year Graduation Rate - All Students (HS file, Instruction and Performance sheet)",
        definition="Share of the school's six-year cohort (entered high school 2019-20) that graduated with a Regents or Local Diploma within six years, including August graduates."),
    "hs_ccr_4yr": dict(label="College and career readiness score, 4-year (0-100)", unit="number", direction="higher",
        source_field="Metric Value - 4-Year College and Career Readiness - All Students (HS file, Instruction and Performance sheet)",
        definition="Average College and Career Readiness (CCR) score, 0-100, of students in the four-year cohort (Class of 2025), graduates and non-graduates alike. Students earn points for test scores, advanced course completion, course grades, endorsements and certificates in six categories, weighted by how well each predicts CUNY GPA. Counts toward non-charter HS ratings starting in 2024-25."),
    "hs_ccr_6yr": dict(label="College and career readiness score, 6-year (0-100)", unit="number", direction="higher",
        source_field="Metric Value - 6-Year College and Career Readiness - All Students (HS file, Instruction and Performance sheet)",
        definition="Average CCR score, 0-100, of the six-year cohort after their sixth year of high school."),
    "hs_ccpci_pct": dict(label="College and Career Preparatory Course Index", unit="pct", direction="higher",
        source_field="Metric Value - College and Career Preparatory Course Index (HS file, Instruction and Performance sheet)",
        definition="\"The percentage of students in the school's four-year cohort who successfully completed approved rigorous courses and assessments after four years of high school\" (Class of 2025): 65+ on Algebra II, Chemistry or Physics Regents; 3+ on any AP exam; 4+ on any IB exam; CLEP credit; C or better in a college-credit course; passing a DOE-certified college-ready course; a diploma with a Seal of Biliteracy, CTE, Civic Readiness or Arts endorsement; or passing an industry-recognized technical assessment. Each student counted once; an AP 2 or IB 3 counts half."),
    "hs_ap_3plus_pct": dict(label="Scored 3+ on an AP exam", unit="pct", direction="higher",
        source_field="Metric Value - % Scoring 3+ on any AP Exam (HS file, Additional Info sheet)",
        definition="% Scoring 3+ on any AP Exam. A component of the CCPCI; its N count equals the CCPCI N count, so the base is the four-year cohort (Class of 2025), not AP test-takers."),
    "hs_ib_4plus_pct": dict(label="Scored 4+ on an IB exam", unit="pct", direction="higher",
        source_field="Metric Value - % Scoring 4+ on any IB Exam (HS file, Additional Info sheet)",
        definition="% Scoring 4+ on any IB Exam; base is the four-year cohort (same N as the CCPCI)."),
    "hs_college_credit_c_pct": dict(label="Earned C+ in a college-credit course", unit="pct", direction="higher",
        source_field="Metric Value - % Earning a Grade of 'C' or Higher for College Credit (HS file, Additional Info sheet)",
        definition="% Earning a Grade of 'C' or Higher for College Credit (e.g. College Now, early college); base is the four-year cohort (same N as the CCPCI)."),
    "hs_cpcc_pass_pct": dict(label="Passed a DOE-certified college prep course", unit="pct", direction="higher",
        source_field="Metric Value - % Passing a NYCPS-certified CPCC Course (HS file, Additional Info sheet)",
        definition="% Passing a NYCPS-certified CPCC Course; base is the four-year cohort (same N as the CCPCI)."),
    "hs_alg2_chem_phys_65_pct": dict(label="65+ on Algebra II, Chemistry or Physics Regents", unit="pct", direction="higher",
        source_field="Metric Value - % Scoring 65+ on Alg2, Chem, or Phys Regents Exam (HS file, Additional Info sheet)",
        definition="% Scoring 65+ on Alg2, Chem, or Phys Regents Exam; base is the four-year cohort (same N as the CCPCI)."),
    "hs_industry_assessment_pct": dict(label="Passed an industry-recognized technical assessment", unit="pct", direction="higher",
        source_field="Metric Value - % Passing an Industry-Recognized Technical Assessment (HS file, Additional Info sheet)",
        definition="% Passing an Industry-Recognized Technical Assessment (the CTE certification exam measure); base is the four-year cohort (same N as the CCPCI)."),
    "hs_cte_endorsement_pct": dict(label="Diploma with CTE endorsement", unit="pct", direction="higher",
        source_field="Metric Value - % Earning a Diploma with a CTE Endorsement (HS file, Additional Info sheet)",
        definition="% Earning a Diploma with a CTE Endorsement; its N count equals the 4-year graduation cohort N, so the base is the whole cohort, not just graduates."),
    "hst_grad_pct": dict(label="Transfer school graduation rate", unit="pct", direction="higher",
        source_field="Metric Value - Transfer School Graduation Rate (HST file, Instruction and Performance sheet)",
        definition="Share of the transfer school's graduation cohort (students whose transfer-school graduation deadline, end of year six or seven of high school, fell in 2025) who graduated with a Regents or Local Diploma, including August graduates. Not comparable to the 4-year rate."),
    "hst_ccr": dict(label="Transfer school CCR score (0-100)", unit="number", direction="higher",
        source_field="Metric Value - Transfer School College and Career Readiness - All Students (HST file, Additional Info sheet)",
        definition="Average CCR score, 0-100, of the 2024-25 transfer school graduating cohort. Informational only; not used in 2024-25 ratings."),
    "hst_ccr_growth_pct": dict(label="Transfer school CCR growth (% of gap closed)", unit="pct", direction="higher",
        source_field="Metric Value - Growth in Transfer School College and Career Readiness - All Students (HST file, Instruction and Performance sheet)",
        definition="Weighted average share of each student's incoming CCR \"gap\" (points not yet earned) that the student closed while at the transfer school; longer-enrolled students weigh more. Informational only in 2024-25."),
    "hst_ccpci_pct": dict(label="Transfer school College and Career Preparatory Course Index", unit="pct", direction="higher",
        source_field="Metric Value - College and Career Preparatory Course Index (HST file, Instruction and Performance sheet)",
        definition="Share of the transfer school graduating cohort who completed approved rigorous courses and assessments (same list as the HS CCPCI)."),
    "hst_industry_assessment_pct": dict(label="Transfer school: passed industry-recognized technical assessment", unit="pct", direction="higher",
        source_field="Metric Value - % Passing an Industry-Recognized Technical Assessment (HST file, Additional Info sheet)",
        definition="% Passing an Industry-Recognized Technical Assessment, transfer school cohort."),
}

RATED_META = {
    "impact_score": ("{T} impact score (0-1, median 0.5)", "number", "higher",
        "Impact Score (Summary sheet, {T} file)",
        "DOE's value-added \"impact\" score: the school's results minus its Comparison Group estimate (what the same students would be expected to achieve at an average city school, controlling for incoming test scores, race, gender, English learner status, special education placement and economic need), standardized within school type to 0.00-1.00 with the median set at 0.50. Uncapped values in the file can exceed 1. Metrics: {M}."),
    "performance_score": ("{T} performance score (0-1, median 0.5)", "number", "higher",
        "Performance Score (Summary sheet, {T} file)",
        "Same scale as the impact score, but measured against the citywide average for the school type with no adjustment for who the students are. Uncapped values can exceed 1. Metrics: {M}."),
    "ip_rating": ("{T} Instruction and Performance rating", "text", "higher",
        "Instruction and Performance - Rating (Summary sheet, {T} file)",
        "Category rating from the first digit of the 1-4.99 category score: 4 Excellent, 3 Good, 2 Fair, 1 Needs Improvement. Combines rated test/graduation/credit/special-population metrics with the Instruction survey subcategory. Successor (since 2023-24) to the old Student Achievement rating. Null when unrated (e.g. new schools, under 25% of students tested)."),
    "ip_score": ("{T} Instruction and Performance score (1-4.99)", "number", "higher",
        "Instruction and Performance - Score (Scoring sheet, {T} file)",
        "Weighted average of the metric scores in the Instruction and Performance category, 1.00-4.99."),
    "ssc_rating": ("{T} Safety and School Climate rating", "text", "higher",
        "Safety and School Climate - Rating (Summary sheet, {T} file)",
        "Category rating (Excellent/Good/Fair/Needs Improvement, from the first digit of the score) built from survey measures on advising, safety, school leadership, student support and teaching environment plus attendance. Unrated if teacher or student survey response was under 30% or under 5 respondents."),
    "ssc_score": ("{T} Safety and School Climate score (1-4.99)", "number", "higher",
        "Safety and School Climate - Score (Scoring sheet, {T} file)",
        "Weighted average of subcategory scores, 1.00-4.99."),
    "rwf_rating": ("{T} Relationships with Families rating", "text", "higher",
        "Relationships with Families - Rating (Summary sheet, {T} file)",
        "Category rating (Excellent/Good/Fair/Needs Improvement) built from survey measures on communication, family involvement and family-school trust. Unrated if the average of teacher and parent response rates was under 30% or under 5 teachers or parents responded."),
    "rwf_score": ("{T} Relationships with Families score (1-4.99)", "number", "higher",
        "Relationships with Families - Score (Scoring sheet, {T} file)",
        "Weighted average of subcategory scores, 1.00-4.99."),
}
IMPACT_METRICS = {
    "EMS": "mean ELA state test score 50%, mean math state test score 50%",
    "HS": "mean ELA Regents score, mean Algebra I Regents score, 4-year graduation rate, postsecondary enrollment 6 months after graduation, 25% each",
    "HST": "mean ELA Regents score 25%, mean Algebra I Regents score 25%, 6-year graduation rate 50%",
}
for T in ("EMS", "HS", "HST"):
    for suffix, (label, unit, direction, sf, d) in RATED_META.items():
        FIELD_META[T.lower() + "_" + suffix] = dict(
            label=label.format(T=T), unit=unit, direction=direction,
            source_field=sf.format(T=T), definition=d.format(T=T, M=IMPACT_METRICS[T]))


def read_sheet(path, sheet):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)[sheet]
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 6:
        raise ValueError(f"{path}:{sheet} has only {len(rows)} rows")
    hdr = list(rows[3])
    if "DBN" not in hdr:
        raise ValueError(f"{path}:{sheet} row 4 has no DBN header")
    di = hdr.index("DBN")
    out = {}
    for r in rows[5:]:
        dbn = r[di]
        if dbn is None or str(dbn).strip() == "":
            continue
        dbn = str(dbn).strip().upper()
        if not DBN_RE.match(dbn):
            raise ValueError(f"{path}:{sheet} unexpected DBN value {dbn!r}")
        if dbn in out:
            raise ValueError(f"{path}:{sheet} duplicate DBN {dbn}")
        out[dbn] = r
    return hdr, out


def col(hdr, name, where):
    if hdr.count(name) != 1:
        raise KeyError(f"{where}: header {name!r} found {hdr.count(name)} times")
    i = hdr.index(name)
    # Metric Value columns must sit right after their own N count column.
    if name.startswith("Metric Value - "):
        prev = str(hdr[i - 1] or "")
        stem = name[len("Metric Value - "):]
        if prev.lower() != ("n count - " + stem).lower():
            raise KeyError(f"{where}: {name!r} is not preceded by its N count column (found {prev!r})")
    return i


def clean(v, kind, where):
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if s in SUPPRESSED:
            return None
        if kind == "rating":
            if s not in RATINGS:
                raise ValueError(f"{where}: unexpected rating text {v!r}")
            return s
        raise ValueError(f"{where}: unexpected text {v!r} in numeric field")
    if kind == "rating":
        raise ValueError(f"{where}: number {v!r} in rating field")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{where}: unexpected type {type(v)}")
    x = float(v)
    if kind == "pct" and not (0.0 <= x <= 1.0):
        # Impossible shares published by DOE are nulled, but only the ones already
        # reviewed; any new out-of-range value stops the build.
        if (where, x) in KNOWN_INVALID:
            return None
        raise ValueError(f"{where}: percentage {x} outside 0-1")
    return int(x) if isinstance(v, int) else x


# Published values above 100% (reviewed 2026-10-07). Nulled; listed in notes.
KNOWN_INVALID = {
    ("HST/Summary/16K669/adv_any_enrolled_pct", 1.063),
    ("HST/Summary/16K669/adv_ap_enrolled_pct", 1.053),
}


def main():
    schools = {}
    school_types = {}
    one_side_blank = {}  # dbn -> report(s) where a school-wide value was blank
    counts = {}
    for rt in REPORT_ORDER:
        local, _, min_rows = REPORTS[rt]
        path = os.path.join(SRC_DIR, local)
        sheets = {}
        for _, sheet, _, _ in SPEC[rt] + [("", "Summary", "", "")]:
            if sheet not in sheets:
                sheets[sheet] = read_sheet(path, sheet)
        summ_hdr, summ = sheets["Summary"]
        if len(summ) < min_rows:
            raise ValueError(f"{rt}: parsed {len(summ)} school rows, expected at least {min_rows}")
        for sheet, (_, rows) in sheets.items():
            if set(rows) != set(summ):
                raise ValueError(f"{rt}: DBN set in {sheet} differs from Summary")
        counts[rt] = len(summ)
        st_i = col(summ_hdr, "School Type", f"{rt}/Summary")
        idx = [(f, sheet, col(sheets[sheet][0], h, f"{rt}/{sheet}"), kind) for f, sheet, h, kind in SPEC[rt]]
        for dbn in summ:
            rec = schools.setdefault(dbn, {"report_type": [], "school_type": []})
            rec["report_type"].append(rt)
            rec["school_type"].append(str(summ[dbn][st_i]).strip())
            for f, sheet, i, kind in idx:
                val = clean(sheets[sheet][1][dbn][i], kind, f"{rt}/{sheet}/{dbn}/{f}")
                if f in rec:
                    # Only school-wide fields may come from two reports; unprefixed
                    # report fields (ela_*, math_*, adv_*) live in files with no DBN overlap.
                    if f not in SCHOOLWIDE_FIELDS:
                        raise ValueError(f"{dbn}: field {f} set by two reports")
                    old = rec[f]
                    if old is not None and val is not None and old != val:
                        raise ValueError(f"{dbn}: {f} differs across reports ({old} vs {val})")
                    if (old is None) != (val is None):
                        one_side_blank.setdefault(dbn, set()).add(rt if val is None else "EMS")
                    if old is None and val is not None:
                        rec[f] = val
                else:
                    rec[f] = val
    for dbn, rec in schools.items():
        rec["report_type"] = "+".join(rec["report_type"])
        rec["school_type"] = " + ".join(rec["school_type"])

    field_order = ["report_type", "school_type"] + [f for f, *_ in SCHOOLWIDE]
    for rt in REPORT_ORDER:
        for f, *_ in SPEC[rt]:
            if f not in field_order:
                field_order.append(f)
    missing_meta = [f for f in field_order if f not in FIELD_META]
    if missing_meta:
        raise KeyError(f"no metadata for {missing_meta}")
    for f in field_order:
        nn = sum(1 for r in schools.values() if r.get(f) is not None)
        if nn == 0:
            raise ValueError(f"field {f} has no non-null values")

    out_schools = {}
    for dbn in sorted(schools):
        rec = schools[dbn]
        out_schools[dbn] = {f: rec[f] for f in field_order if f in rec}

    n_two = sum(1 for r in schools.values() if "+" in r["report_type"])
    doc = {
        "key": "sqr",
        "title": "School Quality Reports: ratings, impact, teachers, special-ed services, advanced courses",
        "source": "NYC Department of Education (NYC Public Schools), School Quality Reports 2024-25, \"SQR: Citywide Results\" Excel files (EMS, HS, HST, EC, D75)",
        "source_url": LANDING,
        "file_url": " ; ".join(FILE_BASE + REPORTS[rt][1] for rt in REPORT_ORDER),
        "file_urls": {rt: FILE_BASE + REPORTS[rt][1] for rt in REPORT_ORDER},
        "vintage": VINTAGE,
        "fetched": FETCHED,
        "fields": {f: {k: FIELD_META[f][k] for k in ("label", "definition", "source_field", "unit", "direction")} for f in field_order},
        "notes": [
            "Vintage is school year 2024-25 (the Snapshot calls it 2025). Released on InfoHub with Educator Guides last updated May 19, 2026; no 2025-26 files exist yet (202526-*-sqr-results.xlsx returns 404).",
            "There are five source files; file_url lists all five direct downloads separated by \" ; \" and file_urls maps each report type to its file.",
            f"School rows per file: EMS {counts['EMS']}, HS {counts['HS']}, HST {counts['HST']}, EC {counts['EC']}, D75 {counts['D75']}. {n_two} DBNs (grades 6-12 / K-12) have both an EMS and an HS report, so report-specific fields carry ems_/hs_/hst_ prefixes; {len(schools)} unique DBNs in all.",
            "The six Framework for Great Schools ratings (Rigorous Instruction, Collaborative Teachers, Supportive Environment, Effective School Leadership, Strong Family-Community Ties, Trust) and the overall Student Achievement rating no longer exist in the SQR. The last citywide file carrying them is 2022-23 (202223-ems-sqr-results.xlsx). Since 2023-24 DOE rates three categories instead: Instruction and Performance, Safety and School Climate, Relationships with Families. Those ratings and scores are the *_ip_*, *_ssc_*, *_rwf_* fields; the ten survey_* fields are the school-survey measures that feed them.",
            "Early Childhood and District 75 schools \"do not receive scores or ratings\" (2024-25 EC and D75 Educator Guides), so they have no impact, performance or category fields.",
            "Impact and performance scores appear on the SQR: Dashboard \"for informational purposes\"; the category ratings come from separate metric scores. Both scores are standardized within school type, so an EMS score and an HS score are not on a common base.",
            "Suppression markers in the source become null: blank cells, \"N/A\", \"N<5\", \"N<10\", \"N<15\". The top-code \"> 95%\" appears only in Economic Need Index and Percent HRA Eligible, which are not taken.",
            f"School-wide fields (teachers, IEP services, survey) were checked to be identical wherever a two-report school has a value in both reports. For {len(one_side_blank)} two-report schools ({', '.join(sorted(one_side_blank))}) some school-wide values (survey percent positive, in practice) appear on one report and are blank on the other; the non-blank value is used.",
            "IEP service fields: DOE's guide says a student counts as fully receiving special education programs on an exact IEP-to-STARS schedule match as of June 2025. THE CITY's Oct. 7, 2026 guide (as relayed by the lead, not re-checked here) adds that DOE counts a student as served if services happened at some point in the year. The EMS guide's related-services paragraph says \"as of June 2024\", which looks like an unedited carryover from the prior year's guide. The \"some\" and \"no\" service shares exist in the file but are \"N/A\" for most schools and are not taken.",
            "Math proficiency for grades 7-8 includes math Regents scores converted to imputed grade-level proficiency ratings for students who skipped the grade-level test under the double-testing waiver.",
            "Two published values are impossible and were set to null: transfer school 16K669 shows 1.063 (106.3%) for Percentage of Students Enrolled in Any Advanced Course and 1.053 for Percentage of Students Enrolled in an AP Course (HST file, Summary sheet).",
            "Charter schools (DBNs starting 84): the IEP service fields and the CCR scores (hs_ccr_*, hst_ccr, hst_ccr_growth_pct) are blank for every charter in the files; advanced-course enrollment is blank for 50 of 91 charter HS/HST rows, teacher experience for 86 of 282 charters. Survey-based ratings are often blank for charters because of low response rates.",
            "HS CCPCI components (hs_ap_3plus_pct etc.) share the CCPCI denominator, the four-year cohort; this is inferred from identical N count columns, not stated in the guide.",
            "CCR scores (hs_ccr_*, hst_ccr) are on a 0-100 point scale, not percentages. Average proficiency is on a 1.00-4.50 scale.",
            "NOT TAKEN (available in the files): enrollment; demographics (gender, ELL, IEP share, SETSS/ICT/Special Class recommendation shares, Economic Need Index, temp housing, HRA eligible, overage/under-credited, student race; teacher race; nearby-student and district/borough race comparisons); years of principal experience; attendance (average, % with 90%+ attendance, teacher attendance, HST/D75 average change in attendance); IEP 'some'/'no' service shares; incoming 5th-grade (EMS) / 8th-grade (HS) proficiency; advanced-course enrollment by race; every metric's Rating/N count/Comparison Group/Metric Score columns; city/district/borough survey comparisons and student/teacher/parent survey response rates. EMS: 9th-grade credit accumulation of former 8th graders, movement of students with IEPs to less restrictive settings, ELL progress, % of 8th graders earning HS credit and taking/passing accelerated courses (by subject), core course pass rates (ELA, math, science, social studies), MS adjusted core course pass rate of former students, subgroup average proficiency (ICT, SETSS, Special Class, ELL, lowest third, Black/Hispanic males in lowest third), proficiency by grade and race/gender, grade 8 science, 3rd-to-5th and 5th-to-8th grade growth. HS: 10+ credits in years 1-3 (all, lowest third), graduation for students with IEPs and ELLs and excluding NYSAA, average Regents scores and pass rates by subject (and for IEP/ELL students), completion rate for remaining Regents, 4- and 6-year persistence, postsecondary enrollment at 6 and 18 months (total and by institution type), college persistence, ACT/SAT participation and scores, college-ready Regents thresholds, % Regents diploma (4/6 year), % diploma with arts endorsement, CCR and CCPCI by subgroup. HST: credit accumulation per year by starting credits, graduation rate by admission category and subgroup, HST persistence, postsecondary enrollment, CCR and CCPCI for overage/under-credited students, Regents measures, other CCPCI components. EC: movement to less restrictive settings, attendance. D75: integration into non-D75 environment, movement to less restrictive settings, NYSAA (alternate assessment) levels, local/standard assessment shares.",
        ],
        "schools": out_schools,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {OUT}: {len(out_schools)} schools, {len(field_order)} fields")
    for f in field_order:
        nn = sum(1 for r in out_schools.values() if r.get(f) is not None)
        print(f"  {f:32s} {nn}")


if __name__ == "__main__":
    main()
