"""Tasmanian Government tenders adapter (open procurement opportunities).

See NOTES.md. The tenders site is an ASP.NET-style application whose routes
(``/Tender/...``, ``/ContractAwarded/...``, ``/PurchaseOrder/...``) are far more
stable than its markup, so extraction keys on those routes.
"""

from __future__ import annotations

import re

from ..base import AdapterContext
from ..listing import FieldSpec, ListingAdapter, ListingConfig

BASE = "https://www.tenders.tas.gov.au"


class TendersAdapter(ListingAdapter):
    name = "tenders"
    label = "Tasmanian Government tenders (open opportunities)"
    expected_interval_hours = 12.0
    grace_hours = 24.0
    min_expected_items = 1
    # The current-tenders listing is a complete view of what is open, so an item
    # dropping out of it is meaningful: a withdrawn tender is a story (§2.3).
    supports_removals = True

    listing_urls = (
        f"{BASE}/tender/list",
        f"{BASE}/Tender/List",
        f"{BASE}/tender/search",
        f"{BASE}/",
    )

    config = ListingConfig(
        detail_link_pattern=re.compile(r"(?i)/tender/(?:view|details?|display)(?:[/?]|$)"),
        id_patterns=(
            re.compile(r"(?i)/tender/(?:view|details?|display)/(?P<id>[A-Za-z0-9_.-]+)"),
            re.compile(r"(?i)[?&]id=(?P<id>[A-Za-z0-9_.-]+)"),
            # A colon or hash is required here: without it, "tenders.tas.gov.au"
            # in the URL itself reads as a tender number.
            re.compile(
                r"(?i)\b(?:tender|rft|rfq|rfp)\s*(?:no\.?|number|id)?\s*[:#]\s*"
                r"(?P<id>[A-Z0-9][A-Z0-9/_.-]{3,})"
            ),
        ),
        fields=(
            FieldSpec("tender_id", ("Tender ID", "Tender Number", "Tender No", "Reference", "RFT No")),
            FieldSpec("agency", ("Agency", "Department", "Organisation", "Business Unit", "Buyer")),
            FieldSpec("category", ("Category", "Categories", "UNSPSC", "Classification")),
            FieldSpec("closing_date", ("Closing Date", "Closes", "Closing", "Close Date"), is_date=True),
            FieldSpec("status", ("Status",)),
        ),
        published_labels=("Published", "Advertised", "Release Date", "Released", "Date Published", "Issued"),
    )

    def candidate_urls(self, ctx: AdapterContext) -> list[str]:
        return list(self.listing_urls)

    def _native_id(self, url: str, link_text: str, row: str) -> str:
        native = super()._native_id(url, link_text, row)
        # ``/Tender/View/12345`` and ``/tender/view/12345`` are the same tender.
        return native.lower() if native.startswith("url:") else native
