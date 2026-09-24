"""Generic adapter for logs where each release has its own HTML page (index → page → documents).

The index is parsed with the html_list rules (config keys pass through). Each new item's page is
fetched by `expand()` and document links (config: doc_link_selector, default a[href] ending in a
document extension) become document_urls. The release page itself is also archived by the monitor.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from .base import Adapter, ListedItem, canon_url, find_date, is_doc_url, norm_ws, register
from .html_list import HtmlListAdapter


@register("per_release_pages")
class PerReleasePagesAdapter(Adapter):
    description = "Index of per-release pages; each page links to the released documents."

    def parse(self, body: bytes, base_url: str, config: dict) -> list[ListedItem]:
        items = HtmlListAdapter().parse(body, base_url, {**config, "item_selector": config.get("item_selector")} if config.get("item_selector") else config)
        if not items and not config.get("item_selector"):
            # fall back: every link inside container that looks like a release page
            soup = BeautifulSoup(body, "lxml")
            root = soup.select_one(config["container_selector"]) if config.get("container_selector") else soup
            if root is None:
                return []
            pat = config.get("page_url_contains", "")
            for a in root.find_all("a", href=True):
                u = canon_url(a["href"], base_url)
                t = norm_ws(a.get_text(" ", strip=True))
                if pat and pat not in u:
                    continue
                if not t or is_doc_url(u):
                    continue
                items.append(ListedItem(external_key=u, title=t, url=u, page_url=u,
                                        published_date=find_date(t)))
        for it in items:
            if not it.document_urls:
                it.page_url = it.page_url or it.url
        return items

    def next_page(self, body: bytes, base_url: str, config: dict) -> str | None:
        return HtmlListAdapter().next_page(body, base_url, config)
