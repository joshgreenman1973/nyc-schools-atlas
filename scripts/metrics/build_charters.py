#!/usr/bin/env python3
"""Build data/metrics/charters.json: authorizer, opening year and authorizer
links for New York City charter schools, keyed by DOE DBN.

RAW SOURCES (all in data/sources/, unmodified)
  nysed_charter_school_directory_2025-09-02.xlsx
      NYSED "NYS Charter School Directory" Excel file (as of Sept. 2, 2025), from
      https://www.nysed.gov/sites/default/files/programs/charter-schools/nys-charter-school-directory-as-of-09-02-2025.xlsx
      -> SED Code (BEDS), name, district, Year Opened, Authorizer.
  nysed_charter_schools_directory_page_2026-10-07.html
      The directory web page, https://www.nysed.gov/charter-schools/charter-schools-directory
      -> link from each school name to its NYSED school page.
  nysed_charter_school_pages_nyc_2026-10-07.tar.gz
      Those NYSED school pages for every NYC charter that has one (289), fetched
      2026-10-07 -> NYSED Institution ID (P_INST_ID, to join back to the Excel file)
      and the "School Information Maintained by <authorizer>" link.
  nyc_doe_lcgms_school_data_2026-10-07.xls
      DOE LCGMS school list (ATS System Code + BEDS Number), from the "Downloadable
      School Data in Excel Format" button at https://www.nycenet.edu/PublicApps/LCGMS.aspx.
      (Saved by the capacity/spending build; this script's own download the same
      day was byte-identical.)
  nyc_doe_school_locations_2019-20_wg9x-4ke6.csv
      NYC Open Data "2019 - 2020 School Locations" (system_code + BEDS), for
      charters whose BEDS code no longer appears in LCGMS. (Also byte-identical to
      this script's own download.)

CROSSWALK, NYSED SED Code (12-digit BEDS) -> DOE DBN, applied in order:
  1. exact BEDS match in LCGMS;
  2. exact BEDS match in 2019-20 School Locations;
  3. NYC charter BEDS codes are county(2) + district(2) + "00" + "86" + a 4-digit
     charter number. When a charter changes district, the district digits can
     differ between NYSED and DOE. If the last six digits are unique among NYSED's
     NYC rows and unique among charter (84) DBNs in LCGMS (then 2019-20), use it;
  4. MANUAL_MATCHES below (named, with the reason).
Everything else is listed as unmatched in the notes.
"""
import io
import json
import os
import re
import sys
import tarfile
from collections import Counter
from html import unescape

import openpyxl
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "data", "sources")
XLSX = os.path.join(SRC, "nysed_charter_school_directory_2025-09-02.xlsx")
DIR_HTML = os.path.join(SRC, "nysed_charter_schools_directory_page_2026-10-07.html")
PAGES_TGZ = os.path.join(SRC, "nysed_charter_school_pages_nyc_2026-10-07.tar.gz")
LCGMS = os.path.join(SRC, "nyc_doe_lcgms_school_data_2026-10-07.xls")
LOC1920 = os.path.join(SRC, "nyc_doe_school_locations_2019-20_wg9x-4ke6.csv")
OUT = os.path.join(ROOT, "data", "metrics", "charters.json")

DBN_RE = re.compile(r"^\d{2}[MXKQR]\d{3}$")
EXPECTED_MIN_NYC = 280   # 299 NYC rows in the Sept. 2, 2025 file
EXPECTED_MIN_MATCHED = 270

AUTHORIZER_LABEL = {
    "SUNY": "SUNY Charter Schools Institute",
    "Regents": "NYS Board of Regents (NYSED)",
    "NYCDOE": "NYC Department of Education (Chancellor)",
}

# SED Code -> (DBN, reason)
MANUAL_MATCHES = {
    "342700861100": ("84Q422", "NYSED 'Success Academy Charter School-NYC 14' = LCGMS 84Q422 'Success Academy Charter School - NYC 14'. LCGMS's BEDS field for 84Q422 holds the malformed '38400010422', and the charter-number suffix 861100 is shared with another NYSED NYC row (South Bronx Community Charter High School), so rules 1-3 can't match it."),
}

# Authorizer links that returned HTTP 404 when checked on 2026-10-07; left null.
BROKEN_LINKS = {
    "https://www.newyorkcharters.org/math-engineering-and-science-academy-charter-high-school-2-2/",
}
GENERIC_LINKS = {  # not school-specific
    "http://www.newyorkcharters.org/charter-schools/",
    "https://www.newyorkcharters.org/charter-schools/",
}


def norm_name(s):
    s = unescape(str(s or ""))
    s = s.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def read_directory_xlsx():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h).strip() if h is not None else "" for h in rows[1]]
    need = ["Institution ID", "SED Code", "Charter School Name", "School District", "Region", "Year Opened", "Authorizer"]
    for n in need:
        if n not in hdr:
            raise ValueError(f"Column {n!r} missing; header = {hdr}")
    out = []
    for r in rows[2:]:
        if not any(v is not None for v in r):
            continue
        d = dict(zip(hdr, r))
        if str(d["Region"]).strip() != "New York City":
            continue
        sed = str(d["SED Code"]).strip()
        if not re.fullmatch(r"\d{12}", sed):
            raise ValueError(f"Bad SED Code {sed!r}")
        auth = str(d["Authorizer"]).strip()
        if auth not in AUTHORIZER_LABEL:
            raise ValueError(f"Unexpected authorizer {auth!r} for {d['Charter School Name']}")
        yo = d["Year Opened"]
        if not (isinstance(yo, int) or (isinstance(yo, float) and yo == int(yo))):
            raise ValueError(f"Unexpected Year Opened {yo!r}")
        out.append({
            "inst_id": str(int(d["Institution ID"])),
            "sed": sed,
            "name": str(d["Charter School Name"]).strip(),
            "district": str(d["School District"]).strip(),
            "year_opened": int(yo),
            "authorizer_code": auth,
        })
    if len(out) < EXPECTED_MIN_NYC:
        raise RuntimeError(f"Only {len(out)} NYC rows in {XLSX}")
    return out


def read_directory_links():
    s = open(DIR_HTML, encoding="utf-8", errors="replace").read()
    links = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", s, flags=re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)
        if len(cells) < 6:
            continue
        a = re.search(r'href="([^"]+)"', cells[0])
        name = norm_name(re.sub(r"<[^>]+>", "", cells[0]))
        if a:
            links[name] = a.group(1)
    if len(links) < 300:
        raise RuntimeError(f"Only {len(links)} linked rows on the directory page")
    return links


def read_pages():
    pages = {}
    with tarfile.open(PAGES_TGZ, "r:gz") as tf:
        for m in tf.getmembers():
            if not m.name.endswith(".html"):
                continue
            slug = os.path.basename(m.name)[:-5]
            s = tf.extractfile(m).read().decode("utf-8", errors="replace")
            inst = re.search(r"P_INST_ID=(\d+)", s)
            maint = re.search(r'<a [^>]*href="([^"]+)"[^>]*>\s*School Information Maintained by ([^<]+)</a>', s)
            pages[slug] = {
                "inst_id": inst.group(1) if inst else None,
                "maint_url": unescape(maint.group(1)).strip() if maint else None,
                "maint_by": maint.group(2).strip() if maint else None,
            }
    if len(pages) < 280:
        raise RuntimeError(f"Only {len(pages)} NYSED school pages in {PAGES_TGZ}")
    return pages


def read_lcgms():
    raw = open(LCGMS, "rb").read().decode("utf-16")
    conv = {c: str for c in ["ATS System Code", "BEDS Number", "Location Name", "Managed By Name"]}
    df = pd.read_html(io.StringIO(raw), header=0, converters=conv)[0].fillna("")
    for c in conv:
        df[c] = df[c].astype(str).str.strip()
    df["ATS System Code"] = df["ATS System Code"].str.upper()
    if len(df) < 1800:
        raise RuntimeError(f"LCGMS parse found only {len(df)} rows")
    return df


def main():
    nysed = read_directory_xlsx()
    dir_links = read_directory_links()
    pages = read_pages()
    page_by_inst = {p["inst_id"]: (slug, p) for slug, p in pages.items() if p["inst_id"]}

    lc = read_lcgms()
    b2d_lc = {r["BEDS Number"]: r["ATS System Code"] for _, r in lc.iterrows()
              if re.fullmatch(r"\d{12}", r["BEDS Number"]) and DBN_RE.match(r["ATS System Code"])}
    names_lc = dict(zip(lc["ATS System Code"], lc["Location Name"]))
    loc = pd.read_csv(LOC1920, dtype=str, keep_default_na=False)
    loc["BEDS"] = loc["BEDS"].str.strip()
    loc["system_code"] = loc["system_code"].str.strip().str.upper()
    b2d_19 = {r["BEDS"]: r["system_code"] for _, r in loc.iterrows()
              if re.fullmatch(r"\d{12}", r["BEDS"]) and DBN_RE.match(r["system_code"])}
    names_19 = dict(zip(loc["system_code"], loc["location_name"]))

    def suffix_index(b2d):
        idx = {}
        for b, d in b2d.items():
            if b[6:8] == "86" and d.startswith("84"):
                idx.setdefault(b[6:], set()).add(d)
        return idx

    suf_lc, suf_19 = suffix_index(b2d_lc), suffix_index(b2d_19)
    nysed_suf = Counter(r["sed"][6:] for r in nysed)

    schools, method_ct, unmatched, name_pairs = {}, Counter(), [], []
    doe_link_checks = 0
    conflicts = []
    for r in nysed:
        sed = r["sed"]
        dbn, how = None, None
        if sed in MANUAL_MATCHES:
            dbn, how = MANUAL_MATCHES[sed][0], "manual"
        elif sed in b2d_lc:
            dbn, how = b2d_lc[sed], "lcgms_beds"
        elif sed in b2d_19:
            dbn, how = b2d_19[sed], "locations_2019_20_beds"
        elif sed[6:8] == "86" and nysed_suf[sed[6:]] == 1:
            if len(suf_lc.get(sed[6:], ())) == 1:
                dbn, how = next(iter(suf_lc[sed[6:]])), "lcgms_charter_number"
            elif len(suf_19.get(sed[6:], ())) == 1:
                dbn, how = next(iter(suf_19[sed[6:]])), "locations_2019_20_charter_number"
        if dbn is None:
            unmatched.append(f"{r['name']} (SED {sed}, opened {r['year_opened']}, {r['authorizer_code']})")
            continue
        if not dbn.startswith("84"):
            raise ValueError(f"{r['name']} matched non-charter DBN {dbn}")
        if dbn in schools:
            raise ValueError(f"DBN {dbn} matched twice ({schools[dbn]['nysed_name']} / {r['name']})")
        method_ct[how] += 1
        doe_name = names_lc.get(dbn) or names_19.get(dbn) or ""
        if how != "lcgms_beds" and re.sub(r"[^a-z0-9]", "", norm_name(doe_name)) != re.sub(r"[^a-z0-9]", "", norm_name(r["name"])):
            name_pairs.append(f"{dbn}: NYSED '{r['name']}' / DOE '{doe_name}' ({how})")

        # NYSED school page: by Institution ID, else by the directory link for this name
        slug, page = page_by_inst.get(r["inst_id"], (None, None))
        nysed_url = None
        if page is not None:
            nysed_url = f"https://www.nysed.gov/charter-schools/{slug}"
        else:
            link = dir_links.get(norm_name(r["name"]))
            if link:
                s2 = link.rstrip("/").split("/")[-1]
                if s2 in pages:
                    slug, page, nysed_url = s2, pages[s2], link
        if nysed_url and dir_links.get(norm_name(r["name"])) not in (None, nysed_url):
            # directory link and page found by Institution ID disagree; trust the ID but record
            name_pairs.append(f"{dbn}: directory link {dir_links[norm_name(r['name'])]} vs page by Institution ID {nysed_url}")

        auth_url = None
        if r["authorizer_code"] == "Regents":
            auth_url = nysed_url  # NYSED's Charter School Office is the Regents' authorizing office
        elif page and page["maint_url"] and page["maint_url"] not in GENERIC_LINKS | BROKEN_LINKS:
            want = {"SUNY": "SUNY", "NYCDOE": "DoE"}[r["authorizer_code"]]
            if want in (page["maint_by"] or ""):
                auth_url = page["maint_url"]
            else:
                conflicts.append(f"{dbn} {r['name']}: Excel authorizer {r['authorizer_code']}, but its NYSED page says the school information is maintained by {page['maint_by']} ({page['maint_url']}); authorizer kept from the Excel file, authorizer_url left null")

        m = re.search(r"schools\.nyc\.gov/schools/([MXKQR]\d{3})/?$", auth_url or "")
        if m:
            if "84" + m.group(1) != dbn:
                raise ValueError(f"{r['name']}: DOE link {auth_url} disagrees with crosswalk DBN {dbn}")
            doe_link_checks += 1
        schools[dbn] = {
            "authorizer": AUTHORIZER_LABEL[r["authorizer_code"]],
            "authorizer_code": r["authorizer_code"],
            "year_opened": r["year_opened"],
            "authorizer_url": auth_url,
            "nysed_url": nysed_url,
            "sed_code": sed,
            "nysed_name": r["name"],
            "crosswalk": how,
        }

    if len(schools) < EXPECTED_MIN_MATCHED:
        raise RuntimeError(f"Only {len(schools)} charters matched to DBNs")

    lc_charters = {d for d in lc["ATS System Code"] if d.startswith("84")}
    lc_not_in_nysed = sorted(f"{d} {names_lc[d]}" for d in lc_charters - set(schools))

    out = {
        "key": "charters",
        "title": "Charter school authorizer and opening year",
        "source": "New York State Education Department, NYS Charter School Directory (Excel, as of Sept. 2, 2025) and NYSED charter school pages; DBN crosswalk from NYC DOE LCGMS and NYC Open Data 2019-20 School Locations",
        "source_url": "https://www.nysed.gov/charter-schools/charter-schools-directory",
        "file_url": "https://www.nysed.gov/sites/default/files/programs/charter-schools/nys-charter-school-directory-as-of-09-02-2025.xlsx",
        "vintage": "2025-26 directory, as of 2025-09-02",
        "fetched": "2026-10-07",
        "fields": {
            "authorizer": {
                "label": "Charter authorizer",
                "definition": "The body that granted and oversees the school's charter. Readable label for the directory's Authorizer code: SUNY = SUNY Charter Schools Institute (SUNY trustees), Regents = NYS Board of Regents (through NYSED's Charter School Office), NYCDOE = NYC Department of Education (Chancellor).",
                "source_field": "Authorizer (Sheet1, NYS Charter School Directory xlsx)",
                "unit": "text",
                "direction": "neutral",
            },
            "authorizer_code": {
                "label": "Authorizer (as listed)",
                "definition": "Authorizer exactly as written in NYSED's Excel directory: SUNY, Regents or NYCDOE.",
                "source_field": "Authorizer (Sheet1, NYS Charter School Directory xlsx)",
                "unit": "text",
                "direction": "neutral",
            },
            "year_opened": {
                "label": "Year opened",
                "definition": "Year the school opened, per NYSED. Values of 2026 were listed on NYSED's web page as 'Opening in 2026' (approved but not yet operating when the directory was compiled).",
                "source_field": "Year Opened (Sheet1, NYS Charter School Directory xlsx)",
                "unit": "number",
                "direction": "neutral",
            },
            "authorizer_url": {
                "label": "Authorizer's page for this school",
                "definition": "SUNY and NYC DOE schools: the 'School Information Maintained by ...' link on the school's NYSED page (SUNY school profile or schools.nyc.gov school page). Regents schools: the NYSED school page itself, since NYSED's Charter School Office oversees schools for the Board of Regents. Null when NYSED gives no school-specific link.",
                "source_field": "link text 'School Information Maintained by ...' on https://www.nysed.gov/charter-schools/<school> pages",
                "unit": "text",
                "direction": "neutral",
            },
            "nysed_url": {
                "label": "NYSED charter page",
                "definition": "The school's page in NYSED's Charter Schools Directory (annual reports, financial statements, renewal reports, links to state data).",
                "source_field": "school-name link on https://www.nysed.gov/charter-schools/charter-schools-directory",
                "unit": "text",
                "direction": "neutral",
            },
            "sed_code": {
                "label": "NYSED BEDS code",
                "definition": "NYSED's 12-digit institution code for the school, used to match it to a DOE DBN.",
                "source_field": "SED Code (Sheet1, NYS Charter School Directory xlsx)",
                "unit": "text",
                "direction": "neutral",
            },
            "nysed_name": {
                "label": "Name in NYSED directory",
                "definition": "School name as NYSED lists it (can differ from the DOE name).",
                "source_field": "Charter School Name (Sheet1, NYS Charter School Directory xlsx)",
                "unit": "text",
                "direction": "neutral",
            },
            "crosswalk": {
                "label": "DBN match method",
                "definition": "How the NYSED code was matched to the DBN: lcgms_beds, locations_2019_20_beds, lcgms_charter_number, locations_2019_20_charter_number or manual. See notes.",
                "source_field": "derived",
                "unit": "text",
                "direction": "neutral",
            },
        },
        "notes": [
            "Charter term / renewal end date: NOT included. Neither NYSED's Excel directory nor its web directory gives a term or expiration date. SUNY's school pages show grades and enrollment 'at End of Charter Term' but not the date; NYSED's pages for Regents schools list authorized grades by school year but don't label the end of the term. No bulk source was found.",
            "The Excel file is the current one on NYSED's directory page as of 2026-10-07. NYSED labels it the 2025-2026 directory, as of Sept. 2, 2025; it has not been updated for 2026-27, so schools that opened in fall 2026 may be listed with year 2026 and some may be missing.",
            "Crosswalk counts: " + ", ".join(f"{k} = {v}" for k, v in sorted(method_ct.items())) + f". {len(schools)} of {len(nysed)} NYSED NYC rows matched.",
            "Matches by rules 2-4 where the NYSED and DOE names differ beyond punctuation: " + ("; ".join(name_pairs) if name_pairs else "none") + ". The two Girls Preparatory Bronx schools now run under Bronx Charter School for Excellence names. SUNY's authorizer page for 'Girls Preparatory Charter School of the Bronx' (girls-prep-charter-school-bronx) is now titled 'Bronx Charter School for Excellence 6', which matches DOE's 84X487.",
            "Manual matches: " + "; ".join(f"{s} -> {d}: {why}" for s, (d, why) in MANUAL_MATCHES.items()),
            "Unmatched NYSED NYC rows (no DBN found in LCGMS or 2019-20 School Locations; mostly schools opening in 2025 or 2026): " + "; ".join(unmatched) + ".",
            "DOE LCGMS charter codes with no NYSED NYC directory match: " + ("; ".join(lc_not_in_nysed) if lc_not_in_nysed else "none") + ".",
            "authorizer_url: on 2026-10-07, 206 of the 207 distinct 'School Information Maintained by' links resolved (HTTP 200). One returned 404 and is left null: " + ", ".join(sorted(BROKEN_LINKS)) + ". The generic SUNY link (newyorkcharters.org/charter-schools/) is also left null.",
            "Authorizer conflicts between NYSED's Excel file and its school pages: " + ("; ".join(conflicts) if conflicts else "none") + ".",
            f"Cross-check: for {doe_link_checks} DOE-authorized schools, NYSED's link to schools.nyc.gov/schools/<location code> agrees with the crosswalk DBN ('84' + location code) in every case.",
            "Every school in this file is a charter. The atlas's charter records come from DOE lists, so a few DOE charter DBNs may not appear here.",
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
    print(dict(method_ct))
    print("unmatched:", len(unmatched))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
