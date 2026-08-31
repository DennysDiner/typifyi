"""Register of Lobbyists adapter.

See NOTES.md. Two findings shape this adapter:

* the register moved from DPAC to the Integrity Commission on 1 July 2022, so
  the brief's expected surface is out of date and both hosts are tried;
* the register publishes *current state only*. Nothing on the site shows what a
  lobbyist's client list said last month, which makes our archive the only
  record of prior states — and raises its evidentiary value considerably.

Detail pages are therefore fetched every run (cheaply, via conditional GET):
a client list changes without the listing page changing at all.
"""

from __future__ import annotations

import re

from ..base import AdapterContext
from ..listing import FieldSpec, ListingAdapter, ListingConfig

INTEGRITY = "https://lobbyists.integrity.tas.gov.au"
DPAC = "https://lobbyists.dpac.tas.gov.au"


class LobbyistsAdapter(ListingAdapter):
    name = "lobbyists"
    label = "Tasmanian Register of Lobbyists"
    expected_interval_hours = 12.0
    grace_hours = 36.0
    min_expected_items = 3
    # The register is a complete list of registered lobbyists: a name leaving it
    # is a deregistration, which matters (§2.3).
    supports_removals = True

    listing_urls = (
        f"{INTEGRITY}/register",
        f"{INTEGRITY}/",
        f"{DPAC}/",
    )

    config = ListingConfig(
        detail_link_pattern=re.compile(r"(?i)/lobbyists?/[a-z0-9][a-z0-9_%.-]+/?$"),
        id_patterns=(
            re.compile(r"(?i)/lobbyists?/(?P<id>[a-z0-9][a-z0-9_%.-]+?)/?$"),
        ),
        fields=(
            FieldSpec("trading_name", ("Trading name", "Business name", "Trading as", "Name")),
            FieldSpec("abn", ("ABN", "ACN", "Business registration")),
            FieldSpec("address", ("Address", "Business address", "Registered address")),
            FieldSpec("owners", ("Owners", "Office holders", "Directors", "Partners")),
            FieldSpec("clients", ("Clients", "Client list", "Client")),
            FieldSpec("employees", ("Employees", "Persons engaged", "Registered lobbyists")),
        ),
        published_labels=("Date registered", "Registered", "Registration date", "Last updated", "Updated"),
        follow_next=False,
        # A client list changes on the detail page while the register index is
        # byte-identical, so the detail pages are what must be watched.
        always_fetch_detail=True,
    )

    def candidate_urls(self, ctx: AdapterContext) -> list[str]:
        return list(self.listing_urls)

    def _native_id(self, url: str, link_text: str, row: str) -> str:
        native = super()._native_id(url, link_text, row)
        return native.lower()
