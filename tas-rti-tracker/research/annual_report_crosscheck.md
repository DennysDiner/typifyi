# Tasmanian RTI Annual Report: cross-check of what WebSearch could recover

Researched 2026-09-24 under `research/AGENT_CONSTRAINTS.md`. The only channel was the `WebSearch` tool.

## 0. Bottom line (read this first)

- **Per-authority names with numbers recovered from the annual report: 0.** No search result showed the
  PDF's body text, and no per-authority row (such as "Department of Health: N applications") appeared anywhere.
- **Sector-level totals for 2022-23 were recovered** (snippet_verified, from Examiner press coverage of the
  tabled report): departments, councils, other public authorities and ministers. They add up exactly to a separate
  snippet's statewide total of 2165.
- **The verbatim PDF URL was found for only one year: 2014-15.** For 2024-25 the landing page's link text
  ("Right to Information Annual Report 2024-25 (PDF, 681.4 KB)") appeared, but the href did not. No URL
  for 2019-20 through 2023-24 appeared.
- **Only 21 of the planned 40+ searches ran.** The session-wide WebSearch cap (200 calls, shared with other agents)
  was hit on query 22. Queries 22-24 below were refused. One direct WebFetch of the Examiner article returned
  `EGRESS_BLOCKED`. I did not retry it.
- **Caveat on "snippet_verified".** This WebSearch tool returns result titles and URLs plus a *model-written
  summary* of the result text, not raw snippets. Facts marked snippet_verified below appeared in that returned
  text. The summary sometimes misattributes a sentence to the wrong source (see the UNCERTAIN item in section 2.4).
  Treat every number as "seen in search output, needs checking against the PDF".

---

## 1. Report PDF URLs

| Year | URL | Evidence | Notes |
|---|---|---|---|
| Landing page (all years) | https://www.justice.tas.gov.au/about-us/reports-publications/reports/annual-reports/right-to-information-annual-reports | snippet_verified (result URL) | Its text says the reports "contain statistical information on right to information requests for all public authorities" and the data "is taken directly from returns from public authorities on their own activities under the Right to Information Act 2009". |
| 2024-25 | **null** | Link text snippet_verified: "Right to Information Annual Report 2024-25 (PDF, 681.4 KB)". The href was not seen. | The PDF is small (681 KB), so it is probably text-based rather than scanned and should parse with pdfplumber or pdftotext. |
| 2023-24 | **null** | Not seen | Several searches for "Right to Information Annual Report 2023-24" returned only the general DoJ annual report. |
| 2022-23 | **null** | Not seen | A tabled report exists (Examiner: "according to a report tabled in Tasmania's state parliament"). |
| 2021-22 | **null** | Not seen | |
| 2020-21 | **null** | Not seen | |
| 2019-20 | **null** | Not seen | |
| 2014-15 | https://www.justice.tas.gov.au/__data/assets/pdf_file/0011/353756/Right_to_Information_Annual_Report_2014-15.pdf | snippet_verified (result URL) | This shows the old Squiz Matrix `__data/assets/pdf_file/<4-digit>/<assetid>/<name>.pdf` pattern. Asset IDs cannot be predicted, so URLs for other years **cannot be inferred**. Scrape the landing page's `<a href>` values once the network is open. |

Related URLs seen verbatim (all snippet_verified as result URLs). These are useful for the tool but are **not** the RTI annual report:

- https://www.justice.tas.gov.au/about-us/access-to-information (DoJ "Access to information" page. Search summaries say it also links the RTI Annual Report 2024-25.)
- https://www.justice.tas.gov.au/about-us/reports-publications/reports/annual-reports (index of annual reports)
- https://www.justice.tas.gov.au/__data/assets/pdf_file/0007/833425/Department-of-Justice-Annual-Report-2024-25_web-accessible.pdf (the DoJ's own annual report, not the whole-of-government RTI report)
- https://www.justice.tas.gov.au/__data/assets/pdf_file/0007/784591/Department-of-Justice-Annual-Report-2023-24_accessible.pdf
- https://www.justice.tas.gov.au/__data/assets/pdf_file/0010/728569/Department-of-Justice-Annual-Report-2022-23-web-compressed.pdf
- https://www.justice.tas.gov.au/__data/assets/pdf_file/0010/682057/Department-of-Justice-Annual-Report-2021-22-PART-1-Report.pdf
- https://www.dpac.tas.gov.au/__data/assets/pdf_file/0025/509713/Independent-Review-Tasmania-RTI-Framework.pdf (McCormack and Snell review, "Getting Back on Track", 2025. Probably quotes annual-report statistics.)
- https://www.dpac.tas.gov.au/__data/assets/pdf_file/0030/461487/1748c7a3440218219251b2c878e1e78c399a7a06.pdf (titled "Independent Review of Tasmania's Right to Information Framework". It may be the interim report or another version. UNCERTAIN which one.)
- https://www.dpac.tas.gov.au/government-information/rti/review-of-the-right-to-information-framework
- https://www.edo.org.au/wp-content/uploads/2023/07/EDO_RTI_Act_report_web.pdf (EDO Tasmania, "Lutruwita/Tasmania's ineffective right to information system". Likely has per-authority analysis of the annual reports.)
- https://www.dpac.tas.gov.au/__data/assets/pdf_file/0031/448519/EDO-Submission.pdf and https://www.dpac.tas.gov.au/__data/assets/pdf_file/0031/445585/David-Killick-Submission.pdf (review submissions)
- https://www.ombudsman.tas.gov.au/publications/annual-reports (the Ombudsman AR 2024-25 is a 14.8 MB PDF with external-review statistics)
- https://www.examiner.com.au/story/8632212/right-to-information-requests-soar-in-tasmania/ (the 2022-23 figures in section 2.1. The domain is egress-blocked.)
- https://www.abc.net.au/news/2022-04-01/tasmania-right-to-information-delays-analysis/100955744
- https://www.abc.net.au/news/2020-11-18/tas-right-to-information-secretive-state/12897316
- https://www.abc.net.au/news/2025-07-10/unredacted-watch-house-document-insight-into-tasmanian-rti-laws/105464632
- https://www.abc.net.au/news/2026-05-20/tas-government-businesses-defy-premier/106700726 (GBEs and disclosure logs)
- https://www.parliament.tas.gov.au/house-of-assembly/tabled-papers/house-of-assemblytabled-papershouse-of-assembly-tabled-papers-2025/TP52-1-133.pdf. It was returned for the query "Right to Information Annual Report 2024-25", but its title was only "Annual Report Annual Report 2024-25". **UNCERTAIN** which body's report it is; do not assume it is the RTI report. The tabled-papers folder is still worth scanning, because the RTI report is tabled in Parliament.

---

## 2. What could be established about authorities and numbers

### 2.1 Statewide and sector totals

| Year | Metric | Value | Source | Evidence |
|---|---|---|---|---|
| 2022-23 | Applications to **departments** | 1753 | Examiner, "Massive rise in RTI requests to state government departments" | snippet_verified |
| 2020-21 | Applications to **departments** | 1108 | same | snippet_verified |
| 2022-23 | Applications to **councils** | 171 ("up slightly from the preceding two years") | same | snippet_verified |
| 2022-23 | Applications to **other public authorities** | 190 | same | snippet_verified |
| 2022-23 | Applications to **ministers** (ministers' offices) | 51 | same | snippet_verified |
| 2020-21 | Applications to **ministers** | 16 | same | snippet_verified |
| 2022-23 | **Total** applications | 2165 | search summary citing the Independent Review / DPAC result set | snippet_verified |
| 2022-23 | Growth | +10.6% on 2021-22, +55% on 2020-21 | same | snippet_verified |
| 2022-23 | Check: 1753 + 171 + 190 + 51 | = 2165, which matches the total exactly | arithmetic | inferred (consistency check) |
| 2021-22 | Implied total | about 1958 (2165 / 1.106) | arithmetic | inferred |
| 2020-21 | Implied total | about 1397 (2165 / 1.55). With departments at 1108, non-departments were about 289. | arithmetic | inferred |
| 2022-23 | Refused outright | "close to one-fifth" of all applications | Examiner | snippet_verified |
| 2022-23 | Exemptions applied | "more than half of the applications that were determined" | Examiner | snippet_verified |
| 2022-23 | Released in full | "one-quarter" / "about one-quarter" | Examiner | snippet_verified |
| 2022-23 | Timeliness | 61% determined within 20 working days | Examiner | snippet_verified |
| 2019-20 | Refused in full | "more than 21 per cent" (Queensland next highest at 16%) | ABC 2022-04-01 | snippet_verified |
| 2019-20 | Late | "more than 25 per cent of requests took too long to be decided" | ABC 2022-04-01 | snippet_verified |
| year UNCERTAIN (probably 2018-19) | Refused entirely | "almost one-third" | ABC 2020-11-18 and Mercury coverage | snippet_verified (the year is UNCERTAIN) |
| year UNCERTAIN (the "past two years" before a 2024-2026 article) | External reviews | decisions set aside or changed in at least 80% of cases | ABC | snippet_verified (the year is UNCERTAIN) |

**No 2023-24 or 2024-25 figures were recovered.** Searches for those years returned only the fact that the reports exist.

### 2.2 Per-authority figures

**None recovered.** Searches naming Department of Health, Tasmania Police and Hydro Tasmania returned those bodies'
own RTI pages, not annual-report rows.

### 2.3 Bodies known to be RTI "public authorities" (NOT recovered from the annual report)

These names come from search-result URLs of each body's own RTI page, or from Ombudsman decisions. They are
likely to appear in the annual report's tables, but **that is not verified**. Use them only as a seed list for
fuzzy-matching the parser output.

- Department of Justice, Department of Premier and Cabinet, Department for Education, Children and Young People,
  Department of Health, Tasmania Police (Department of Police, Fire and Emergency Management),
  Department of State Growth, Department of Natural Resources and Environment Tasmania,
  Department of Treasury and Finance, Communities Tasmania (former department): snippet_verified as bodies with RTI pages
- Audit Tasmania (Tasmanian Audit Office), Public Trustee, Local Government Association of Tasmania (LGAT),
  Hydro Tasmania, Tasmanian Community Fund (tascomfund.org), Ombudsman Tasmania, Tasmanian Irrigation: snippet_verified as bodies with RTI pages or annual reports in results
- City of Hobart, Meander Valley Council, Flinders Council: snippet_verified as respondents in Ombudsman RTI decisions (2023/2024)
- University of Tasmania: snippet_verified as an RTI respondent (ABC 2022)

### 2.4 Items marked UNCERTAIN

- Several search summaries said "Section 53 of the Right to Information Act 2009 requires **Audit Tasmania** to prepare
  a report for each financial year". The text came from the audit.tas.gov.au/rti/ result. **UNCERTAIN / probably a
  misattribution by the summariser.** From memory, s 53 places the reporting duty on the responsible Minister, using returns
  from each public authority, and the Department of Justice compiles and publishes the report. Audit Tasmania is a
  public authority that *contributes* a return. Check this against the Act (legislation.tas.gov.au act-2009-070)
  once reachable.
- The total of 2165 was attributed in the search summary to the Independent Review. It is also consistent with the
  Examiner sector figures. Two independent paths agree, so confidence is high, but the attribution is still UNCERTAIN.

---

## 3. Report structure (to guide a PDF parser)

Evidence-backed points:

- The data comes from **returns submitted by each public authority** about its own activity (snippet_verified, landing page).
  So the report should contain one row per authority.
- Figures are aggregated into at least **four sector groupings**: *departments*, *councils*, *other public authorities*,
  and *ministers* (snippet_verified, Examiner 2022-23). The four sector numbers sum exactly to the statewide total, which
  suggests each sector table has a subtotal row that the parser can use as a checksum.
- The report carries **multi-year comparisons**: the Examiner compared 2020-21, 2021-22 and 2022-23 for departments,
  councils and ministers. There may be a trend table over three or more years.
- Outcome categories exist for **released in full**, **released in part / exemptions applied**, and **refused in full**
  (snippet_verified, from the Examiner's fractions).
- A **timeliness** metric exists: "determined within 20 working days" (snippet_verified, 61% in 2022-23).
- The 2024-25 PDF is **681.4 KB** (snippet_verified), so it is probably a text layer with tables, not scanned images.

From memory only (unverified; do not rely on this without checking the PDF):

- The report is organised around the s 53 reporting items. Per authority, the columns are roughly: applications received
  (assessed disclosure); applications accepted; transferred (in/out); withdrawn; determined/decided; outcomes (full release /
  partial / refused); refusals under s 10 / s 19 / s 20 (e.g. unreasonable diversion of resources, repeat or vexatious
  requests); counts of each exemption section applied (ss 25-37, split into s 30-type "not subject to public interest test" and
  public-interest-test exemptions); timeliness (within 20 working days, extended by agreement or by the Ombudsman, out of time);
  internal reviews (received, upheld/varied); external reviews to the Ombudsman; and possibly fees and charges waived. (memory)
- Tables may be printed landscape, with long authority names wrapping across two lines. Councils are probably listed
  alphabetically, all 29. GBEs and state-owned companies (Hydro Tasmania, TasNetworks, TasPorts, TasRail, Sustainable
  Timber Tasmania, Tasmanian Irrigation, TasWater and so on) and statutory bodies probably fall under "other public
  authorities". (memory)
- Authorities with no activity may appear as rows of zeros or be omitted. (memory; UNCERTAIN)

Parser recommendations:
1. Fetch the landing page and collect every `<a href$=".pdf">` whose text matches `Right to Information Annual Report \d{4}-\d{2}`.
2. Run `pdfplumber` table extraction page by page. Detect sector headings (Departments / Councils / Local Government /
   Other public authorities / Ministers).
3. Validate each sector's subtotal against the sum of its rows, and the four-sector sum against the statewide total.
   For 2022-23 the expected values are 1753 / 171 / 190 / 51 / 2165.
4. Carry authority names through a normalisation map, because departments were renamed across 2019-2025
   (e.g. Communities Tasmania was absorbed, DoE became DECYP, and DPIPWE became NRE Tas).

---

## 4. Queries run

The WebSearch tool ran queries 1-21. For queries 13 and 20 it also ran internal follow-up searches whose query text
was not shown to me. Queries 22-24 were **refused** because the session search budget was exhausted.

1. `"Right to Information" "Annual Report" Tasmania 2024-25 "public authorities" applications received`
2. `site:justice.tas.gov.au right to information annual report`
3. `"Right to Information Act 2009" annual report statistics "Hydro Tasmania" applications`
4. `"Right_to_Information_Annual_Report" justice.tas.gov.au pdf`
5. `"Right to Information Annual Report 2024-25" Tasmania`
6. `"Right to Information Annual Report 2023-24" Tasmania Department of Justice pdf`
7. `Tasmania right to information annual report "applications received" "public authorities" 2023-24 total`
8. `"assessed disclosure" applications 2023-24 Tasmania statistics council`
9. `Tasmania RTI annual report "number of applications" "Department of Health"`
10. `Ombudsman Tasmania annual report 2024-25 "right to information" external review statistics`
11. `Tasmania right to information applications refused annual report ABC news secrecy`
12. `"right to information" Tasmania annual report figures Mercury "applications" departments refused in full 2024`
13. `abc.net.au 2022 Tasmania right to information delays analysis annual report applications per agency`
14. `"Right to Information" annual report Tasmania "Tasmania Police" most applications received year` (with internal follow-ups)
15. `"Right to Information Annual Report 2022-23" Tasmania`
16. `"Independent Review of Tasmania's Right to Information Framework" statistics applications received annual report public authorities`
17. `Tasmania RTI annual report 2023-24 "applications" "refused" "per cent" news` (with internal follow-ups)
18. `"Right to Information" Tasmania annual report "within the statutory timeframe" percentage 2024-25`
19. `Examiner "Massive rise in RTI requests to state government departments"`
20. `"2165" RTI applications Tasmania 2022-23 "10.6 per cent"`
21. `Hobart Mercury "STATE'S POOR SECRECY RECORD" right to information`
22. REFUSED (budget): `examiner.com.au right to information requests soar Tasmania departments Health Police Natural Resources applications`
23. REFUSED (budget): `Tasmania RTI annual report tabled parliament 2024 applications departments councils ministers "other public authorities"`
24. REFUSED (budget): `Tasmania "right to information" report tabled 2023-24 applications departments rose councils ministers`

Other attempt: `WebFetch https://www.examiner.com.au/story/8632212/right-to-information-requests-soar-in-tasmania/` returned EGRESS_BLOCKED (one attempt, not retried).

### Suggested queries for a re-run (not yet executed)
- `"Right to Information Annual Report 2019-20"` and the same for each year through 2023-24, one per query
- `site:parliament.tas.gov.au "Right to Information" annual report tabled`
- `EDO "ineffective right to information system" Tasmania departments refusal rate table`
- `"Getting Back on Track" RTI review Tasmania applications 2023-24 departments`
- Examiner / Mercury / Pulse Tasmania / Tasmanian Inquirer: `RTI annual report 2023-24 Tasmania applications`, `RTI annual report 2024-25 Tasmania applications`
- Press coverage naming top authorities: `"right to information" Tasmania "most applications" department 2024`
- Hansard/Estimates: `Estimates "right to information" applications "Department of Health" Tasmania 2025`
