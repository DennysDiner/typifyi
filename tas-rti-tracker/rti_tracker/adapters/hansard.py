"""Hansard / Estimates mentions of "right to information" — STUB (brief §2 allows stubbing).

The Parliament of Tasmania Hansard search endpoint was not reachable at build time. This adapter parses
a search-results page with the html_list heuristics when a working URL is configured
(config: {search_url_template: "...{term}...", terms: [...]}) and otherwise returns no items and records
a note. Enable in config/scheduler.yaml once the endpoint is confirmed.
"""
from __future__ import annotations

from .base import ListedItem, register
from .html_list import HtmlListAdapter


@register("hansard")
class HansardAdapter(HtmlListAdapter):
    description = "Hansard search results for RTI-related terms (stub until endpoint confirmed)."

    def parse(self, body: bytes, base_url: str, config: dict) -> list[ListedItem]:
        if not config.get("search_url_template"):
            return []
        items = super().parse(body, base_url, {**config, "min_items": 1})
        for it in items:
            it.fields["kind"] = "hansard"
        return items
