"""Contract disclosure adapter (awarded contracts).

See NOTES.md — this is the highest-value and messiest of the four sources.

One trap is deliberately avoided here: the *date awarded* is not the publication
date. Publishing behaviour against the disclosure deadline is itself a finding
(§9.4), so the awarded date is captured as a field inside ``body_text`` and
``published_at`` stays null unless the source states a publication date.
"""

from __future__ import annotations

import re

from ..base import AdapterContext
from ..listing import FieldSpec, ListingAdapter, ListingConfig

BASE = "https://www.tenders.tas.gov.au"


class ContractsAdapter(ListingAdapter):
    name = "contracts"
    label = "Tasmanian Government contract disclosures (awarded contracts)"
    expected_interval_hours = 12.0
    grace_hours = 48.0
    min_expected_items = 1
    # Awarded-contract listings are ordered by award date and paginate; the view
    # we walk is a window, not the whole register, so a disappearance is more
    # likely to be paging than a withdrawal. Removals are therefore not emitted.
    supports_removals = False

    listing_urls = (
        f"{BASE}/ContractAwarded/List/DateAwarded",
        f"{BASE}/contractawarded/list",
        f"{BASE}/ContractAwarded/List",
        f"{BASE}/PurchaseOrder/List",
    )

    config = ListingConfig(
        detail_link_pattern=re.compile(
            r"(?i)/(?:contractawarded|contract|purchaseorder)/(?:view|details?|display)(?:[/?]|$)"
        ),
        id_patterns=(
            re.compile(
                r"(?i)/(?:contractawarded|contract|purchaseorder)/(?:view|details?|display)/"
                r"(?P<id>[A-Za-z0-9_.-]+)"
            ),
            re.compile(r"(?i)[?&]id=(?P<id>[A-Za-z0-9_.-]+)"),
            re.compile(
                r"(?i)\bcontract\s*(?:no\.?|number|id)?\s*[:#]\s*"
                r"(?P<id>[A-Z0-9][A-Z0-9/_.-]{3,})"
            ),
        ),
        fields=(
            FieldSpec("contract_id", ("Contract ID", "Contract Number", "Contract No", "Reference")),
            FieldSpec("agency", ("Agency", "Department", "Organisation", "Business Unit", "Buyer")),
            FieldSpec("supplier", ("Supplier", "Contractor", "Awarded To", "Successful Tenderer", "Vendor")),
            FieldSpec("value", ("Value", "Contract Value", "Amount", "Total Value", "Price")),
            FieldSpec("date_awarded", ("Date Awarded", "Awarded", "Award Date", "Contract Start"), is_date=True),
            FieldSpec("end_date", ("End Date", "Expiry", "Contract End", "Completion Date"), is_date=True),
        ),
        # Only a stated *publication* date counts here. "Date awarded" is
        # captured as a field, never promoted into published_at.
        published_labels=("Date Published", "Published", "Publication Date", "Disclosed", "Date Disclosed"),
        max_list_pages=3,
    )

    def candidate_urls(self, ctx: AdapterContext) -> list[str]:
        return list(self.listing_urls)
