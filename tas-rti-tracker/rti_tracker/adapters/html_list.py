"""Generic adapter for disclosure logs published as an HTML list of links / accordion / cards.

Config keys:
  item_selector: CSS selector for each entry (default: heuristics — li/article/div containing a doc link)
  title_selector: within item (default: the link text or heading)
  link_selector: within item (default: all a[href])
  container_selector: restrict search to a region of the page
  date_selector: within item
  min_items: below this the page is considered mis-parsed and no items are returned (default 1)
"""
from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from .base import (
    Adapter,
    ListedItem,
    canon_url,
    dedupe,
    find_date,
    find_reference,
    is_doc_url,
    norm_ws,
    parse_date,
    register,
    stable_key,
)


def _item_from_tag(tag: Tag, base_url: str, config: dict) -> ListedItem | None:
    links = [(canon_url(a["href"], base_url), norm_ws(a.get_text(" ", strip=True))) for a in tag.find_all("a", href=True)]
    if not links:
        return None
    doc_urls = [u for u, _ in links if is_doc_url(u)]
    page_urls = [u for u, _ in links if not is_doc_url(u)]
    if config.get("title_selector"):
        t = tag.select_one(config["title_selector"])
        title = norm_ws(t.get_text(" ", strip=True)) if t else ""
    else:
        heading = tag.find(["h1", "h2", "h3", "h4", "h5", "strong"])
        title = norm_ws(heading.get_text(" ", strip=True)) if heading else ""
        if not title:
            title = max((t for _, t in links), key=len, default="")
    if not title:
        title = norm_ws(tag.get_text(" ", strip=True))[:200]
    text = norm_ws(tag.get_text(" ", strip=True))
    date_txt = None
    if config.get("date_selector"):
        d = tag.select_one(config["date_selector"])
        date_txt = norm_ws(d.get_text(" ", strip=True)) if d else None
    published = parse_date(date_txt) if date_txt else find_date(text)
    reference = find_reference(title, text)
    url = doc_urls[0] if doc_urls else page_urls[0]
    return ListedItem(
        external_key=stable_key(reference or title, url), title=title, url=url, reference=reference,
        published_date=published, fields={"text": text[:1000]}, document_urls=doc_urls,
        page_url=None if doc_urls else url,
    )


@register("html_list")
class HtmlListAdapter(Adapter):
    description = "Disclosure log as an HTML list/accordion/cards of links."

    def parse(self, body: bytes, base_url: str, config: dict) -> list[ListedItem]:
        soup = BeautifulSoup(body, "lxml")
        root: Tag = soup
        if config.get("container_selector"):
            c = soup.select_one(config["container_selector"])
            if c is None:
                return []
            root = c
        if config.get("item_selector"):
            tags = root.select(config["item_selector"])
        else:
            # heuristic: smallest block elements that directly contain a document link
            tags = []
            for a in root.find_all("a", href=True):
                u = canon_url(a["href"], base_url)
                if not is_doc_url(u):
                    continue
                block = a
                while block.parent is not None and block.name not in ("li", "article", "tr", "p", "div", "section", "dd"):
                    block = block.parent
                if block not in tags:
                    tags.append(block)
        items = [it for it in (_item_from_tag(t, base_url, config) for t in tags) if it]
        if len(items) < int(config.get("min_items", 1)):
            return []
        return dedupe(items)

    def next_page(self, body: bytes, base_url: str, config: dict) -> str | None:
        sel = config.get("next_selector")
        if not sel:
            return None
        soup = BeautifulSoup(body, "lxml")
        a = soup.select_one(sel)
        return canon_url(a["href"], base_url) if a and a.has_attr("href") else None
