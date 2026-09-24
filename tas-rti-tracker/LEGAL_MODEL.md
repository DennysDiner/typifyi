# Tasmanian Right to Information: legal model for the RTI tracker

Prepared: 2026-09-24. Instrument modelled: *Right to Information Act 2009* (Tas) (No. 70 of 2009), "the Act", and the *Right to Information Regulations 2021* (Tas) (SR 2021-036), "the Regulations".

## How to read this document

**Evidence labels** (see `research/AGENT_CONSTRAINTS.md`). Every item carries one of these:

- `snippet_verified`: the fact appeared in WebSearch result text this session.
- `inferred`: I reasoned it out from snippet facts; no search result stated it.
- `memory`: from training knowledge only; no result this session showed it.

**Caveat on `snippet_verified`.** The WebSearch tool returns result titles and URLs plus a model-written digest of the result pages. A `snippet_verified` fact is one that appeared in that digest. The tool does not reliably say which of the listed URLs a sentence came from. So a URL is cited only where the result clearly tied the fact to it. Two digests sometimes put different subsection numbers on the same rule. Where that happened, the item is marked `UNCERTAIN`.

**Network.** No primary source could be read. legislation.tas.gov.au, AustLII, ombudsman.tas.gov.au and archive.org are all blocked by the egress proxy. Every pinpoint in this document must be re-checked against the authorised consolidation; see the Verification checklist at the end.

**Pinpoint convention.** "s 15(1)" means a section and subsection of the Act. "reg" means the Regulations. "Sch" means a Schedule to the Act.

---

## 0. Version currency

| Item | Finding | Evidence |
|---|---|---|
| Authorised consolidations exist on legislation.tas.gov.au | Seen in results: an authorised PDF for 2019-09-18 to 2019-11-13 (`https://www.legislation.tas.gov.au/view/pdf/authorised/2019-09-18%202019-11-13/act-2009-070`), an authorised PDF for 2024-08-30 to 2024-09-06 (`https://www.legislation.tas.gov.au/view/pdf/authorised/2024-08-30%202024-09-06/act-2009-070`), and an in-force version dated 2013-01-01. | snippet_verified (URLs) |
| Act amended by Act No. 28 of 2024 | One result digest said the Act "has been amended by No. 28 of 2024". The same digest mentioned "Schedule 2 amendments … applied on 01 Jul 2026". | snippet_verified, but garbled. **UNCERTAIN**: the digest may be conflating the Act's own Schedule 2 (irrelevant public-interest matters) with an amending schedule. The 2024-08-30 consolidation start date is consistent with a 2024 amendment commencing about 30 Aug 2024 (inferred). What No. 28 of 2024 changed is unknown. The journalist fee-waiver ground (§8) is a candidate. |
| 2025 independent review | "Getting Back On Track", by Prof Tim McCormack and Adj Assoc Prof Rick Snell, commissioned December 2024 and released September 2025 (ABC, 2025-09-23). It made 43 recommendations, including automatic release of Cabinet information, an Information Commissioner, and greater appeal rights. | snippet_verified |
| Government response | Tabled March 2026. The government supports 32 of the 43 recommendations "in full or in principle" and commits to "legislative changes that will modernise the RTI framework". Also announced: proactive release of Cabinet documents after 20 years, and monthly release of final Cabinet decisions from 1 September 2026. The Cabinet-decision release is an **administrative scheme**, not an amendment to the Act. | snippet_verified (premier.tas.gov.au 2026/march and 2026/august pages; ABC 2026-03-17) |
| RTI amendment bill in 2025–2026 | None found. A search of the Parliament's 2025 bills listing returned no "Right to Information Amendment Bill". | snippet_verified (negative result only). **UNCERTAIN**: absence from search results does not prove no bill exists. A bill implementing the March 2026 response could have been introduced between March and September 2026. |
| **Conclusion on currency** | This model reflects the Act **as described by agency and Ombudsman pages current to about mid-2026**, including the 2026-27 fee figure. It does **not** reflect a primary-source reading of any consolidation. | **UNCERTAIN** |

---

## 1. "Public authority" and Ministers (s 5, s 6)

### 1.1 Inclusions (s 5 definition of "public authority")

| # | Inclusion | Pinpoint | Evidence |
|---|---|---|---|
| 1 | An Agency within the meaning of the *State Service Act 2000*, i.e. government departments | s 5 "public authority" (a) | snippet_verified that Agencies are included. The paragraph letter (a) is inferred. One digest wrongly placed the definition in "section 3". |
| 2 | The University of Tasmania | s 5 "public authority" **(ab)** | snippet_verified. The paragraph letter "(ab)" appeared in the result, which suggests UTAS was added by amendment. |
| 3 | The Police Service | s 5 "public authority" (b) | snippet_verified |
| 4 | A council | s 5 "public authority" (c)? | Councils are clearly covered (LGAT and several council RTI pages): snippet_verified. The paragraph letter is inferred. |
| 5 | A statutory authority | s 5 "public authority" (d) | snippet_verified |
| 6 | A body, corporate or unincorporate, established by or under an Act for a public purpose | s 5 "public authority" (e) | snippet_verified |
| 7 | A body whose members, or a majority of whose members, are appointed by the Governor or a Minister | s 5 "public authority" (paragraph unknown) | snippet_verified (text); paragraph letter **UNCERTAIN** |
| 8 | Government Business Enterprises (*Government Business Enterprises Act 1995*) | s 5 "public authority"; s 5 "principal officer" (the GBE's CEO) | snippet_verified |
| 9 | State-owned companies **and council-owned companies**. The Ombudsman's manual notes their express inclusion. "Council-owned company" means a Corporations Act company controlled by one or more councils, or by another company they control. | s 5 "public authority", "council-owned company", "principal officer" | snippet_verified |
| 10 | Bodies "prescribed" by regulation | s 5 "public authority" (catch-all paragraph?) | memory. **UNCERTAIN**: no result showed a "prescribed body" limb or any body prescribed under the Regulations. |

### 1.2 Exclusions and partial carve-outs

| # | Carve-out | Pinpoint | Evidence |
|---|---|---|---|
| 1 | **Parliament** (House of Assembly, Legislative Council) and the **Governor**: RTI applications cannot be made to them | s 5 and/or s 6 | snippet_verified (DPAC page: "Some government roles or bodies cannot be applied to, including the Tasmanian Parliament and the Governor"). The exact provision is **UNCERTAIN**. |
| 2 | **Law Society of Tasmania**: covered **only** for its functions and powers under Parts 8 and 9 of the *Legal Profession Act 1993*, and as a prescribed authority under Part 3.2 of Ch 3 and Ch 5 of the *Legal Profession Act 2007* | s 6 | snippet_verified. The references to the 1993 Act look like legacy text. |
| 3 | Information given to, received by or created by "the council, the commission or a person" for examining or inquiring into a complaint under a named Act is outside the Act | s 6 | snippet_verified (text). Which Act and which "council/commission" is **UNCERTAIN**; possibly the legal-profession complaints bodies. |
| 4 | Courts and tribunals: excluded in their judicial or quasi-judicial functions, covered for administrative functions | s 5/s 6 | memory. **UNCERTAIN**: a targeted search returned no result on courts. |
| 5 | Other s 6 exclusions | s 6 | **UNCERTAIN**. The follow-up search on s 6 was blocked by the search budget. |

### 1.3 Ministers as a distinct category

- The right of access is to information in the possession of **public authorities and Ministers** (s 7; the object in s 3). Evidence: snippet_verified.
- Applications for assessed disclosure may be made to "a public authority or a Minister". Most time limits apply equally to Ministers (s 13, s 15). Evidence: snippet_verified (s 15(4) and third-party wording).
- A **Minister's own decision, or a decision of a principal officer, cannot be internally reviewed**. The applicant goes straight to the Ombudsman under **s 45(1)(a)**. Evidence: snippet_verified.
- Ministerial information has its own exemptions: s 27 (internal briefing information of a Minister) and s 28 (information not relating to official business). Evidence: snippet_verified (headings).
- DPAC keeps a separate log of Ministers' and MPs' releases, at the snippet URL `https://www.dpac.tas.gov.au/rti/disclosure_log_-_mps`. Evidence: snippet_verified (URL only).

### 1.4 Contracted service providers

Whether information held by a contractor counts as "in the possession of" a public authority is unresolved.

- Evidence: memory only. No search on this topic could be run (budget exhausted).
- **UNCERTAIN.**

---

## 2. Application acceptance (s 13, s 16)

| Rule | Pinpoint | Evidence |
|---|---|---|
| The application must be in writing | s 13(2) | snippet_verified |
| It must come with the application fee (25 fee units) or a request to waive it | s 16(1) | snippet_verified |
| "Before an application is accepted … the application fee must be paid or a decision to waive the fee under subsection (2) must be made" | s 16 (probably s 16(3)) | snippet_verified (text); subsection number inferred |
| **Deemed acceptance date:** once the fee is paid or waived, "the application is taken to have been accepted by the public authority when it was received" | s 13 or s 16 (exact subsection **UNCERTAIN**) | snippet_verified (one digest only). **UNCERTAIN** whether acceptance is backdated to receipt when the waiver decision comes later. The engine should use `application_accepted = received_date` when the fee is paid at lodgement. When a waiver is decided later, it should flag the date. |
| Negotiation to refine an application "expeditiously and in any case not later than 10 working days after the receipt of the application" | s 13(7) | snippet_verified |
| Assessed disclosure is the "method of last resort" | s 5 definition; Ombudsman guidance | snippet_verified |

---

## 3. Decision timeframes for assessed disclosure

### 3.1 Core rules

| Rule | Days | Pinpoint | Evidence |
|---|---|---|---|
| Base period: notify the decision "as soon as practicable" and no later than 20 working days after acceptance | 20 wd from acceptance | s 15(1) | snippet_verified |
| **Third-party consultation**: where the authority or Minister has decided to consult a third party under s 36 or s 37, "a further 20 working days in addition to the 20 working days referred to in subsection (1)" is allowed | +20 wd, so 40 wd from acceptance | s 15 (the subsection is **UNCERTAIN**: 15(2) or 15(3)) | snippet_verified for the number. Several agency pages confirm the 40 wd total. |
| Third party's time to respond to consultation | 15 wd from notice; afterwards the authority may decide without the third party's input | s 36, s 37 (exact subsections unknown) | snippet_verified |
| **Negotiation-related period**: one digest said "Where negotiation takes place under section 13(7), that period is extended to 30 working days under section 15(3)" | 30 wd? | s 15(3)? | snippet_verified (single digest). **UNCERTAIN**: this conflicts with the digest that assigns the third-party +20 to the subsection after s 15(1). It is unclear whether "30" counts from receipt (10 wd negotiation + 20 wd) or from acceptance. |
| Extension **by agreement with the applicant** | agreed | s 15(4)(a) | snippet_verified |
| Extension **allowed by the Ombudsman**: "The Ombudsman may allow a public authority or a Minister further time … subject to such conditions as the Ombudsman thinks fit" | set by the Ombudsman | s 15(4)(b)? | snippet_verified (text). The pinpoint is **UNCERTAIN**. One digest said "in accordance with subsection (3)". Whether the Ombudsman route is available only when the applicant refuses to agree is memory. |

### 3.2 Clarification, clock-stopping and refusal to deal

- **Clock stop.** No snippet says the s 15 clock stops during negotiation. Because acceptance is taken to be the receipt date and negotiation must finish within 10 wd of receipt, I infer the clock does **not** stop, subject to the 30 wd point in 3.1. **UNCERTAIN.**
- **s 19, resources**: an application may be refused where the work involved "would substantially and unreasonably divert the resources of the public authority from its other work", or would interfere substantially and unreasonably with a Minister's other functions, having regard to **Schedule 3**. Before refusing, the authority must give the applicant a reasonable opportunity to consult so the application can be reframed. Evidence: snippet_verified. The consultation subsection (s 19(2)?) is inferred.
- **s 20, repeat and vexatious**: (a) the application is the same as or similar to a previous application and discloses no reasonable basis for asking again; (b) it is vexatious, or it "remains lacking in definition after negotiation under section 13(7)". Evidence: snippet_verified.
- The Ombudsman's decisions index has separate categories for s 19 ("Voluminous") and s 20 ("Repeat and vexatious"). Evidence: snippet_verified (URL titles).

### 3.3 Transfers (s 14)

- Where an application is transferred, for the purposes of s 15 the receiving authority or Minister is taken to have received it at the **earlier** of the date of transfer and the end of 10 working days after the original application. Evidence: snippet_verified.
- **UNCERTAIN**: whether the s 15(1) clock runs from this deemed receipt or from the receiver's own acceptance. The two may differ when the fee is handled at the receiving end.

### 3.4 Deemed refusal

- If the applicant has not received notice of the decision within the relevant period, the principal officer or Minister "is taken to have made a decision refusing to grant the application on the last day of the relevant period, for the purpose of enabling an application to be made to the Ombudsman under section 45". The applicant may apply under **s 45(1)(f)**. Evidence: snippet_verified (operative text; s 45(1)(f)).
- **Section containing the deeming rule: UNCERTAIN.** Memory suggests a late subsection of s 15, e.g. s 15(5) or 15(6); not confirmed.
- A deemed refusal goes **directly to the Ombudsman**. No internal review step is shown in any snippet (inferred from s 45(1)(f)).

---

## 4. Internal review (s 43)

| Rule | Pinpoint | Evidence |
|---|---|---|
| Available against a decision of a **delegated officer**. Not available where a Minister or principal officer made the decision; that goes to the Ombudsman under s 45(1)(a) | s 43; s 45(1)(a) | snippet_verified |
| Window: apply "within 20 working days of the day on which the applicant received notice of the decision" | s 43 (subsection unknown) | snippet_verified |
| Who may apply: the applicant; whether a consulted third party may also apply | s 43 | Applicant: snippet_verified. Third party: memory, **UNCERTAIN** |
| **Decision timeframe: 15 or 20 working days?** | s 43 (subsection unknown) | **UNCERTAIN, conflicting.** The Ombudsman's RTI page says both "must be made within 20 working days" and "you can seek external review … if a decision has not been received after 15 working days". The Hobart Community Legal Service result says the reviewer must decide "within 15 working days". Memory also favours 15. The rules file uses **15** with `candidate_values: [15, 20]`. |
| Deemed refusal on internal review: failure to decide in time lets the applicant go to the Ombudsman | s 44(1)(b) or s 45 | snippet_verified that external review is available. The deeming mechanism and pinpoint are **UNCERTAIN**. |

---

## 5. External review by the Ombudsman (ss 44–48)

| Rule | Pinpoint | Evidence |
|---|---|---|
| **After internal review**: a person who has applied for internal review under s 43 may apply to the Ombudsman "within 20 working days of an event referred to in subsection (1)(b)", i.e. notice of the internal review decision | s 44 | snippet_verified. That the (1)(b) events include expiry of the internal review period without a decision is inferred. |
| **Direct applications** where internal review is not available: (a) decision made by a Minister or principal officer; (f) no notice of decision within the time limit (deemed refusal); other paragraphs (b)–(e) not seen | s 45(1) | snippet_verified for (a) and (f). Paragraphs (b)–(e) are **UNCERTAIN** (memory: third-party objectors, fee-waiver refusals and similar). |
| Window for s 45 applications | s 45 | One digest said "applications must be made within 20 working days of an event". **UNCERTAIN**: it is unclear whether this was s 44 or s 45 text, and whether any time limit applies to a deemed refusal. |
| Must internal review be exhausted first? **Yes** for delegated decisions (s 44 route). **No** for Minister or principal-officer decisions and deemed refusals (s 45) | s 44, s 45 | snippet_verified / inferred |
| Ombudsman's timeframe: "as soon as practicable after receipt of the application"; no fixed statutory deadline found. Backlogs have been reported: ABC reports of a "666 years" backlog (2017) and reviews taking over two years (2018). | s 46/47? | snippet_verified (text). Pinpoint **UNCERTAIN**. |
| Effect of the Ombudsman's decision: memory says the Ombudsman makes a decision on review, may direct or recommend release, and the authority must give effect to it | ss 47–48? | memory, **UNCERTAIN** |
| Further avenues: the Ombudsman "is the only and final place you can go for an external review". Judicial review on questions of law (*Judicial Review Act 2000*) is memory only | n/a | "only and final": snippet_verified. Judicial review: memory. |

---

## 6. Publication and disclosure logs: the Act compared with practice

### 6.1 What the Act requires

- **Four types of disclosure** are defined in s 5 and described in ss 10–12: required, routine, active and assessed.
  - *Required disclosure* is information "required to be published by this or any other Act, or … otherwise required by law or enforceable under an agreement".
  - *Routine disclosure* is information the authority "decides may be of interest to the public" but which is not required, assessed or active.
  - *Assessed disclosure* is disclosure "in response to an application in accordance with section 13". Note that **s 13 is the application provision, not a publication duty.**
  - Evidence: snippet_verified (definitions). The section numbers for the types are **UNCERTAIN**. One digest said s 12 is headed "Information to be provided apart from Act" and says the Act "does not prevent and is not intended to discourage" publication otherwise than as required.
- **No statutory disclosure log.** The Department of Health's disclosure-log page says publication of released information "is not a statutory requirement and is at the discretion of the Department". No snippet showed any provision of the Act or the Regulations requiring a disclosure log.
  - Evidence: snippet_verified (agency statement); the negative finding is inferred.
  - **UNCERTAIN** whether s 12 has a subsection saying assessed-disclosure material "should" be routinely disclosed. Memory suggests a soft, non-mandatory provision of that kind.

### 6.2 What happens in practice (policy, not law)

- **48-hour publication policy.** Departments (NRE Tas, Tasmania Police, DECYP, Justice) state that "certain information released in response to Right to Information requests will be published online within 48 hours of being released to the applicant". Personal, commercial and confidential material is excluded. Evidence: snippet_verified.
- **Premier's letter, April 2026.** The Premier wrote to GBEs and state-owned companies asking them to publish RTI releases within 48 hours. The ABC reported on 2026-05-20 that nine did not respond. TasTAFE, Hydro and Sustainable Timber Tasmania already published logs; TasRacing, Aurora Energy and the Public Trustee said they would. Evidence: snippet_verified. **This is a request, not a statutory duty.**
- **Ombudsman guidance on disclosure logs**: memory only. Ombudsman "Guidelines" exist (numbered 1/2010 etc.), but no snippet tied any guideline to disclosure logs. **UNCERTAIN.**
- **Monthly release of final Cabinet decisions from 1 September 2026**: administrative policy. Evidence: snippet_verified.

**Implication for the tracker.** An authority that does not publish a log is not in breach of the Act. It is departing from government policy, which applies to departments and, as a request, to GBEs and SOCs. Flag it as a *policy* non-compliance only.

---

## 7. "Working day" (s 5)

| Question | Answer | Evidence |
|---|---|---|
| Definition text | Memory: "a day other than a Saturday, a Sunday or a statutory holiday". "Statutory holiday" is probably defined by reference to the *Statutory Holidays Act 2000*. **No search result showed the definition.** Three targeted queries failed to surface it. | memory, **UNCERTAIN** |
| Saturdays and Sundays excluded | Yes, per memory. Consistent with every agency page counting "working days". | memory |
| Statewide statutory holidays excluded | Yes, per memory | memory |
| Christmas–New Year shutdown days (non-holiday weekdays) | **Not excluded.** Nothing found suggests the Act excludes them, unlike some other jurisdictions. | memory, **UNCERTAIN** |
| **Regional holidays**: Royal Hobart Regatta (south), Recreation Day (north), Launceston Cup, Burnie Show, King Island Show and similar | Memory: under the *Statutory Holidays Act 2000*, Regatta Day and Recreation Day are holidays only in parts of the State, and local show and cup days are declared for particular areas. Whether they count depends on how the Act's definition picks up "statutory holiday" and whether the location of the authority, the applicant or the State as a whole is the reference point. No evidence found. | **UNCERTAIN** |
| Easter Tuesday | Memory: a holiday for the State Service under the *Statutory Holidays Act 2000* or awards, not a general statutory holiday. It could matter for Agencies. | memory, **UNCERTAIN** |

**Engine recommendation.** Exclude weekends and statewide statutory holidays. Compute regional holidays under **both** the statewide-only and the authority-region readings. Where they differ, surface the deadline as a range and mark it `uncertain`.

---

## 8. Fees (s 16; Fee Units Act 1997)

| Item | Finding | Pinpoint | Evidence |
|---|---|---|---|
| Application fee | **25 fee units** | s 16(1) | snippet_verified |
| Dollar value 2025-26 | Fee unit $1.91 from 1 July 2025, giving **$47.75** | *Fee Units Act 1997* | snippet_verified |
| Dollar value 2026-27 | **$49.00** from 1 July 2026 (DPAC "Making a RTI request", dated 16 April 2026). Implied fee unit **$1.96**. | *Fee Units Act 1997* | $49.00: snippet_verified. $1.96: inferred (49 / 25). |
| Indexation | Fee units indexed on 1 July each year | *Fee Units Act 1997* | snippet_verified |
| Waiver (a) | Applicant is impecunious (financial hardship; evidence such as a Centrelink or DVA payment) | s 16(2)(a) | snippet_verified |
| Waiver (b) | Member of Parliament acting in connection with official duty | s 16(2)(b) | snippet_verified |
| Waiver (ba) | **Journalist acting in connection with professional duties** | s 16(2)(ba)? | snippet_verified that current agency pages list it. **UNCERTAIN** whether it is statutory, and what its paragraph number is. Older pages list only three grounds, and one digest's "(ba)" may be the digest's own label. It may have been inserted by Act No. 28 of 2024. |
| Waiver (c) | Applicant intends to use the information for a purpose "of general public interest or benefit" | s 16(2)(c) | snippet_verified |
| Waiver discretion | Waiver is at the authority's discretion ("may") | s 16(2) | snippet_verified |
| Processing or access charges | Memory: none; the application fee is the only charge. | n/a | memory, **UNCERTAIN** |
| Content of the Regulations 2021 | Not seen. Possibly forms, prescribed matters, or a modified fee. | Regs | **UNCERTAIN** |

---

## 9. Exemptions (Part 3)

Headings are snippet_verified unless marked otherwise. A citation such as "s 37(1)(b)" normalises to its base section, and the subsection is kept as a qualifier.

| Section | Heading | Public-interest test? | Notes | Evidence |
|---|---|---|---|---|
| s 25 | Executive Council information | No (Div 1) | | snippet_verified |
| s 26 | Cabinet information | No | | snippet_verified |
| s 27 | Internal briefing information of a Minister | No | | snippet_verified |
| s 28 | Information not relating to official business | No | | snippet_verified |
| s 29 | Information affecting national or State security, defence or international relations | No | | snippet_verified |
| s 30 | Information relating to enforcement of the law | No | | snippet_verified |
| s 31 | Legal professional privilege | No | | snippet_verified |
| s 32 | Information relating to closed meetings of council | No | | snippet_verified |
| s 33 | *Public interest test*: the operative provision, **not an exemption** | n/a | Information within Div 2 is exempt only if disclosure is contrary to the public interest, considering Sch 1 (relevant matters) and disregarding Sch 2 (irrelevant matters) | snippet_verified |
| s 34 | Information communicated by other jurisdictions | Yes (Div 2) | | snippet_verified |
| s 35 | Internal deliberative information | Yes | Excludes purely factual information. The exemption **ceases after 10 years** from creation. | snippet_verified |
| s 36 | Personal information of person | Yes | Third-party consultation route | snippet_verified |
| s 37 | Information relating to business affairs of third party | Yes | Third-party consultation route | snippet_verified |
| s 38 | Information relating to business affairs of public authority | Yes | | snippet_verified |
| s 39 | Information obtained in confidence | Yes | | snippet_verified |
| s 40 | Information on procedures and criteria used in certain negotiations of public authority | Yes | | snippet_verified |
| s 41 | Information likely to affect State economy | Yes | | snippet_verified |
| s 42 | Information likely to affect cultural, heritage and natural resources of the State | Yes | Content (rare or endangered flora and fauna; sites of scientific, cultural or historical significance) is verified. The heading wording came from my query, not the result. | content: snippet_verified; heading: memory |

**Other refusal and non-exemption provisions** the extractor will meet:

- s 19: resources / voluminous (Sch 3). snippet_verified.
- s 20: repeat or vexatious. snippet_verified.
- s 7: the right to information. snippet_verified.
- Memory suggests further refusal or "information not held / otherwise available" provisions in roughly ss 9–22. **UNCERTAIN**; do not hard-code.

**Parser guidance for the metadata extractor.**

- Accept these forms: `s 35`, `s.35`, `sec 35`, `section 35(1)(a)`, `ss 36 and 37`, `ss 36–37`, `s35`.
- Normalise to `{section: 35, sub: "(1)(a)"}`.
- Map s 33 to `public_interest_test`, not to an exemption.

---

## 10. Annual reporting (s 53)

- s 53 requires the **Secretary of the Department of Justice** to report on the administration of the Act across all public authorities: councils, departments and GBEs. Evidence: snippet_verified.
- A reporting template goes to public authorities around 1 July each year. The report is tabled "as soon as practicable" after the financial year ends. Its statistics come from the authorities' own returns. Evidence: snippet_verified.
- Published at "Right to Information Annual Reports | Department of Justice": `https://www.justice.tas.gov.au/about-us/reports-publications/reports/annual-reports/right-to-information-annual-reports`. Evidence: snippet_verified (URL).
- Whether s 53 also names Ministers as reporters, whether s 54 exists as a separate reporting section, and the tabling Minister are **UNCERTAIN** (memory).
- The Ombudsman publishes RTI review decisions at `https://www.ombudsman.tas.gov.au/right-to-information/reasons-for-decisions`, indexed by section (19, 20, 35, 37, 38, 39, 43–45). Evidence: snippet_verified (URL). Its own annual report: memory.

---

## 11. Amendments, 2024–2026

See §0.

- Act No. 28 of 2024 is referenced. Its content is unknown and it may be the journalist fee-waiver change. **UNCERTAIN.**
- UTAS appears at paragraph "(ab)" of the definition, which points to an inserted paragraph. Date unknown. inferred.
- The March 2026 government response commits to legislative change. No enacted 2025–26 RTI amendment was found. **UNCERTAIN.**

---

## Verification checklist (re-read against the primary source when the network is open)

1. s 5 "working day": exact text; how "statutory holiday" is defined; how regional holidays (Regatta, Recreation Day, show and cup days) and Easter Tuesday are treated.
2. s 5 "public authority": every paragraph letter (a)–(?), including any "prescribed" limb. Also s 5 "principal officer", "council-owned company" and "Minister".
3. s 6: the full list of exclusions and partial applications (courts, tribunals, Parliament, Governor, Law Society, complaint-handling bodies).
4. The Regulations 2021 (SR 2021-036): every regulation, and whether any body is prescribed or any fee is modified.
5. s 13: subsections on writing, the acceptance date and negotiation (s 13(7), 10 wd); whether the clock pauses.
6. s 14: transfer deemed-receipt rule and its interaction with acceptance.
7. s 15: numbering of each subsection. Confirm (1) 20 wd; the third-party +20 wd (2 or 3); the "30 working days" negotiation reading; (4)(a) agreement; (4)(b) Ombudsman extension and its conditions; the deemed-refusal subsection.
8. s 16: fee units (25); waiver paragraphs (a), (b), (ba) journalist, (c); the acceptance precondition subsection.
9. ss 19 and 20, and Sch 3.
10. ss 36 and 37: third-party notice, 15 wd response, and any deferral of release pending third-party review.
11. s 43: window (20 wd from receipt of notice); **decision period, 15 vs 20 wd**; who may apply.
12. s 44: window and the (1)(b) events. s 45: paragraphs (a)–(f) and the time limit, if any, for deemed refusals.
13. ss 46–48 (or whatever they are): the Ombudsman's powers, timeframe and the binding effect of decisions; any appeal or judicial review route.
14. ss 10–12: types of disclosure; any "should publish" language for assessed-disclosure material.
15. s 53 (and s 54?): the annual reporting duty and who tables.
16. The Part 3 headings, especially the exact s 42 heading.
17. Amendment history: Act No. 28 of 2024 and anything enacted after the March 2026 response.
18. The 2026-27 fee-unit value in the Treasurer's Fee Units notice ($1.96 implied).
19. Ombudsman manual (mirror seen at `https://www.flinders.tas.gov.au/client-assets/images/Business/Downloads/Right%20to%20Information%20-%20Manual%20for%20the%20Act.pdf`, snippet_verified URL). Read its chapters on time, acceptance and working days.

---

## Appendix A: URLs seen verbatim in results (snippet_verified)

- Act, current in-force HTML: https://www.legislation.tas.gov.au/view/whole/html/inforce/current/act-2009-070
- Act, as made: https://www.legislation.tas.gov.au/view/whole/html/asmade/act-2009-070
- Act, authorised PDF for 2024-08-30 to 2024-09-06: https://www.legislation.tas.gov.au/view/pdf/authorised/2024-08-30%202024-09-06/act-2009-070
- Act, authorised PDF for 2019-09-18 to 2019-11-13: https://www.legislation.tas.gov.au/view/pdf/authorised/2019-09-18%202019-11-13/act-2009-070
- Regulations 2021: https://www.legislation.tas.gov.au/view/html/inforce/current/sr-2021-036
- AustLII s 5: https://www8.austlii.edu.au/cgi-bin/viewdoc/au/legis/tas/consol_act/rtia2009234/s5.html
- AustLII s 35: http://www8.austlii.edu.au/cgi-bin/viewdoc/au/legis/tas/consol_act/rtia2009234/s35.html
- AustLII s 36: https://classic.austlii.edu.au/au/legis/tas/consol_act/rtia2009234/s36.html
- Ombudsman's manual (Flinders Council mirror): https://www.flinders.tas.gov.au/client-assets/images/Business/Downloads/Right%20to%20Information%20-%20Manual%20for%20the%20Act.pdf
- Ombudsman RTI page: https://www.ombudsman.tas.gov.au/right-to-information
- Ombudsman, "How long does it take": https://www.ombudsman.tas.gov.au/right-to-information/rti/how-long-does-it-take-to-get-a-decision
- Ombudsman, "How much does it cost": https://www.ombudsman.tas.gov.au/right-to-information/rti/how-much-does-it-cost
- Ombudsman, ss 43–45 decisions: https://www.ombudsman.tas.gov.au/right-to-information/reasons-for-decisions/reasons-for-decisions-folder-2016-current/sections-43-45-review-mechanisms
- DPAC, making a request: https://www.dpac.tas.gov.au/government-information/rti/making-a-rti-request
- DPAC, review page: https://www.dpac.tas.gov.au/government-information/rti/review-of-the-right-to-information-framework
- Premier, March 2026: https://www.premier.tas.gov.au/latest-news/2026/march/strengthening-tasmanias-right-to-information-framework
- Premier, August 2026: https://www.premier.tas.gov.au/latest-news/2026/august/monthly-disclosure-of-cabinet-documents-announced
- ABC, 2026-05-20 (GBE disclosure logs): https://www.abc.net.au/news/2026-05-20/tas-government-businesses-defy-premier/106700726
- ABC, 2025-09-23 (review): https://www.abc.net.au/news/2025-09-23/independent-review-recommends-changes-right-to-information/105807010
- ABC, 2026-03-17 (response): https://www.abc.net.au/news/2026-03-17/right-to-information-cabinet-documents-transparency-reforms/106462734
- Justice, RTI annual reports: https://www.justice.tas.gov.au/about-us/reports-publications/reports/annual-reports/right-to-information-annual-reports
- Health, disclosure log ("not a statutory requirement"): https://www.health.tas.gov.au/about/routine-disclosures/right-information
- Hobart Community Legal Service handbook: https://www.hobartlegal.org.au/handbook/government-administration-and-justice/freedom-of-information-and-the-right-to-information-2/tasmania-right-to-information/rights-to-information-in-tasmania/

## Appendix B: Queries run (56 completed; 4 blocked by the session search budget)

1. `"Right to Information Act 2009" Tasmania "section 15" 20 working days`
2. `"Right to Information Act 2009" Tasmania "working day" definition`
3. `"Right to Information Act 2009" Tasmania "deemed" refused decision not made within time`
4. `"Right to Information Regulations 2021" Tasmania application fee "fee units"`
5. `Tasmania right to information application fee "25 fee units" "1 July 2026"`
6. `"Right to Information Act 2009" "section 13(7)" negotiation "30 working days"`
7. `Ombudsman Tasmania RTI manual "working day" Saturday Sunday "statutory holiday"`
8. `"Right to Information Act 2009" "section 6" "public authority" Tasmania does not apply`
9. `"Right to Information Act 2009" Tasmania negotiation "not later than 10 working days" section 13`
10. `"Right to Information" Tasmania "section 15(3)" OR "s 15(3)" third party "further 20 working days"`
11. `"Right to Information Act 2009" "section 15(4)(b)" Ombudsman extension application`
12. `Tasmania RTI "section 15(6)" OR "section 15(5)" "deemed" refusal Ombudsman review`
13. `"Ombudsman may allow a public authority or a Minister further time" Right to Information`
14. `Tasmania RTI internal review "20 working days" decision "15 working days" Ombudsman deemed`
15. `"Right to Information Act 2009" "section 43" internal review "20 working days" Tasmania`
16. `"Right to Information Act 2009" "section 45" Ombudsman review "20 working days" Tasmania application external review`
17. `"internal review" Tasmania "Right to Information" "within 15 working days" decision`
18. `"section 45(1)(f)" Right to Information Tasmania Ombudsman`
19. `"Right to Information Act 2009" Tasmania section 45 "(a)" "(b)" "(c)" grounds application to Ombudsman for review internal review "Minister"`
20. `Tasmania Ombudsman RTI "external review" "within 20 working days" "internal review decision"`
21. `hobartlegal.org.au Tasmania right to information internal review "working days" Ombudsman review time limit`
22. `"Right to Information" Tasmania "section 44" Ombudsman review "20 working days" after "internal review"`
23. `"Right to Information Act 2009" Tasmania "principal officer" "taken to have made a decision refusing" "last day"`
24. `"Right to Information Act 2009" Tasmania "section 19" "unreasonably divert" resources refuse application`
25. `"Right to Information Act 2009" Tasmania "Schedule 2" "Schedule 1" "Schedule 3" public interest matters irrelevant`
26. `"Right to Information Act 2009" Tasmania "section 20" repeat application vexatious refuse`
27. `"Right to Information Act 2009" Tasmania "section 14" transfer application "public authority" time`
28. `"Right to Information Act 2009" Tasmania "section 16" waiver "impecunious" "Member of Parliament" journalist`
29. `Tasmania right to information fee waiver journalist "professional duties" application fee`
30. `"Right to Information Act 2009" "16(2)" waive fee "general public interest or benefit" Tasmania`
31. `"Right to Information Act 2009" Tasmania application "accepted" "application fee must be paid" "section 13"`
32. `Right to Information Amendment Act Tasmania 2024 OR 2025 OR 2026 bill`
33. `Tasmania "Right to Information" amendment journalists fee waiver 2024 Act No. 28 of 2024`
34. `"Right to Information Act 2009" Tasmania amended "1 July 2026"`
35. `Independent Review of Tasmania's Right to Information Framework recommendations government response`
36. `Tasmania parliament "Right to Information Amendment Bill" 2025`
37. `"Strengthening Tasmania's Right to Information Framework" premier March 2026 legislation`
38. `Tasmania right to information bill 2026 Information Commissioner cabinet documents legislation introduced`
39. `"Right to Information Act 2009" Tasmania "Division 1" "not subject to the public interest test" sections 25 to 32`
40. `"Right to Information Act 2009" Tasmania "section 33" OR "s 33" exempt information "public interest test" "Division 2"`
41. `"Right to Information Act 2009" Tasmania "section 34" "Information communicated by other jurisdictions" OR "other governments"`
42. `"Right to Information Act 2009" Tasmania "section 35" "internal deliberative information"`
43. `"Right to Information Act 2009" Tasmania "section 37" "business affairs of third party" "section 38" "business affairs of public authority"`
44. `"Right to Information Act 2009" Tasmania "section 39" "obtained in confidence" "section 40" negotiations "section 41" economy`
45. `"Right to Information Act 2009" Tasmania "section 42" "cultural, heritage and natural resources"`
46. `"Right to Information Act 2009" Tasmania "section 36" "personal information" "section 36(2)" consult third party "section 37(2)"`
47. `"Right to Information Act 2009" Tasmania "section 12" routine disclosure "disclosure log" required`
48. `Ombudsman Tasmania "disclosure log" guideline "Right to Information" publish released information 48 hours`
49. `Tasmanian Government "disclosure log" policy agencies "48 hours" right to information Premier direction`
50. `"Right to Information Act 2009" "12(3)" OR "section 12(3)" routine disclosure assessed disclosure "should be" published`
51. `"Right to Information Act 2009" Tasmania "section 11" "required disclosure" "section 10" types of disclosure`
52. `"Right to Information Act 2009" Tasmania "section 53" annual report Minister information "public authority" provide`
53. `"Right to Information Act 2009" Tasmania "public authority means" Agency council "Government Business Enterprise" "State-owned company"`
54. `"Right to Information Act 2009" Tasmania "does not apply" Governor court "judicial functions" Parliament Legislative Council House of Assembly`
55. `"Right to Information Act 2009" Tasmania public authority "University of Tasmania" "Tasmania Police" "body or authority" established "for a public purpose"`
56. `"Right to Information Act 2009" Tasmania Minister "official business" "Minister" distinct from public authority application to Minister "Ministerial office"`

Blocked, not run (session WebSearch budget of 200 exhausted). Re-run these first:

- B1. `"Right to Information Act 2009" Tasmania section 6 "Act does not apply" "Law Society" "Legal Profession Act" court "in relation to"`
- B2. `"Right to Information Act 2009" Tasmania "public authority" "(c) a council" "(f)" "State-owned company" "council-owned company" definition paragraphs`
- B3. `Ombudsman manual Tasmania "public authority" "excluded" courts "administrative" functions "Right to Information Act" section 6 exclusions list`
- B4. `"Right to Information Act 2009" Tasmania "contracted service provider" OR "contractor" information "possession" public authority "section 7"`

Also still to run: the exact "working day" definition; `"Statutory Holidays Act 2000" "Right to Information"`; `"Right to Information Act 2009" "section 46"` / `"section 47"` / `"section 48"`; the Regulations 2021 regulation list; the content of Act No. 28 of 2024.
