# Contract disclosure adapter notes

**Source:** Tasmanian Government awarded-contract disclosures
**Status:** route identified; **markup, pagination and field labels unverified**
(see `../DISCOVERY.md`). This is the highest analytical value of the four
sources and the messiest to parse.

## What is established

| Fact | Basis | Verified against the live page? |
| --- | --- | --- |
| Awarded contracts are listed at `www.tenders.tas.gov.au/ContractAwarded/List/DateAwarded` | indexed page | no |
| A purchase-order listing exists at `/PurchaseOrder/List` | indexed page | no |
| Agencies must report contracts valued ≥ $50,000 on the tenders site | Treasury/purchasing guidance | no |
| Procurement thresholds: $50k disclosure, $100k–$250k three written quotes, $250k+ public tender | procurement guidance summaries | no |
| Non-procurement contracts over $2 million are disclosed on **each agency's own** website under TI C-1 / the Crown Contracts Confidentiality Policy | Treasury and agency pages (DPAC, Tasmania Police, Health, TasTAFE all publish such a page) | no |

## How the adapter reads it

Candidate listings, tried in order:

1. `/ContractAwarded/List/DateAwarded`
2. `/contractawarded/list`
3. `/ContractAwarded/List`
4. `/PurchaseOrder/List`

Rows come from anchors matching
`/(contractawarded|contract|purchaseorder)/(view|details|display)/…`. Fields
extracted by label: contract id, agency, supplier, value, date awarded, end
date.

**`published_at` is null unless the page states a publication date.** The date
awarded is captured as a field inside `body_text`, never promoted into
`published_at`. This is deliberate: the gap between when a contract was awarded
and when it was disclosed is itself a finding (§9.4), and conflating the two
would destroy the ability to measure it.

Removals are **not** emitted: this listing is ordered by award date and
paginates, so an item leaving the first pages means paging, not withdrawal.

## Open questions (§9)

* **What is the actual publication deadline?** Not established. TI C-1 and the
  Crown Contracts Confidentiality Policy are the documents to read
  (`https://www.treasury.tas.gov.au/Documents/C---1-Disclosure-and-Confidentiality-in-Government-Contracting.PDF`,
  and the combined procurement TIs at purchasing.tas.gov.au). Record the finding
  here, then compare it against observed `date_awarded` → first-seen gaps, which
  the records make measurable.
* Does the listing expose the contract value in the row, or only on the detail
  page? Value is the field most worth having in the alert.
* Agency-level $2m non-procurement disclosure pages are **not** covered by this
  adapter. They are per-agency HTML pages; adding them is a phase-2 job and
  should be a separate adapter with its own NOTES.
* Does the listing paginate by query parameter, and how far back does it go?

## Failure expectations

* `min_expected_items = 1`; raise once the steady-state page size is known.
* Grace is 48 h rather than 24 h: award disclosures are lumpier than tenders.
