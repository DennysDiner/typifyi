"""Auto-detecting adapter for logs whose format is still `unknown` in the registry.

Tries html_table, html_list and per_release_pages (and pdf_index when the body is a PDF) and uses the
parser that yields the most plausible items. The winning format is recorded in the source's config
(`detected_format`) so `rti registry suggest-formats` can write it back into the registry for review.
"""
from __future__ import annotations

from .base import Adapter, ListedItem, register
from .html_list import HtmlListAdapter
from .html_table import HtmlTableAdapter
from .pdf_index import PdfIndexAdapter
from .per_release_pages import PerReleasePagesAdapter


@register("auto")
class AutoAdapter(Adapter):
    description = "Try each generic adapter and keep the one that parses the most items."

    def __init__(self) -> None:
        self.detected: str | None = None

    def parse(self, body: bytes, base_url: str, config: dict) -> list[ListedItem]:
        pinned = config.get("pinned_format")
        if pinned and pinned != "pdf_index" and body[:5] != b"%PDF-":
            table = {"html_table": HtmlTableAdapter, "html_list": HtmlListAdapter, "per_release_pages": PerReleasePagesAdapter}
            if pinned in table:
                items = table[pinned]().parse(body, base_url, config)
                if items:
                    self.detected = pinned
                    config["detected_format"] = pinned
                    return items
                # pinned parser found nothing: fall through to re-detection (monitor alerts on a switch)
        if body[:5] == b"%PDF-":
            self.detected = "pdf_index"
            return PdfIndexAdapter().parse(body, base_url, config)
        candidates = [("html_table", HtmlTableAdapter()), ("html_list", HtmlListAdapter()), ("per_release_pages", PerReleasePagesAdapter())]
        best_name, best_items = None, []
        for name, ad in candidates:
            try:
                items = ad.parse(body, base_url, config)
            except Exception:  # noqa: BLE001
                items = []
            score = sum(1 for it in items if it.document_urls or it.page_url) + 0.1 * len(items)
            best_score = sum(1 for it in best_items if it.document_urls or it.page_url) + 0.1 * len(best_items)
            if score > best_score:
                best_name, best_items = name, items
        self.detected = best_name
        config["detected_format"] = best_name
        return best_items

    def next_page(self, body: bytes, base_url: str, config: dict) -> str | None:
        return HtmlListAdapter().next_page(body, base_url, config)

