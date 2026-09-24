"""Ombudsman Tasmania published RTI external review decisions.

The decisions page layout has not been observed (network blocked at build time); this adapter uses the
html_list heuristics with a decision-specific reference pattern (e.g. "R2301-012", "O2402-010") and
extracts the authority name from the title ("X and Department of Y"). Verify on first poll and add
`item_selector` to the source config if the heuristics under-parse.
"""
from __future__ import annotations

import re

from .base import ListedItem, register
from .html_list import HtmlListAdapter

REF = re.compile(r"\b([ROD]\d{4}-\d{3})\b")
VS = re.compile(r"^(?P<applicant>.+?)\s+(?:and|v\.?|vs\.?)\s+(?P<authority>.+?)(?:\s*[-–(]|$)", re.IGNORECASE)


@register("ombudsman_decisions")
class OmbudsmanDecisionsAdapter(HtmlListAdapter):
    description = "Ombudsman Tasmania RTI external review decisions listing."

    def parse(self, body: bytes, base_url: str, config: dict) -> list[ListedItem]:
        items = super().parse(body, base_url, {"min_items": 1, **config})
        for it in items:
            m = REF.search(it.title) or REF.search(it.fields.get("text", ""))
            if m:
                it.reference = m.group(1)
                it.external_key = m.group(1)
            v = VS.match(it.title)
            if v:
                it.fields["applicant"] = v.group("applicant").strip()
                it.fields["authority_raw"] = v.group("authority").strip()
            it.fields["kind"] = "ombudsman_decision"
        return items
