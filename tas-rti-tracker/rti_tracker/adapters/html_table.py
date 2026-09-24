"""Generic adapter for disclosure logs published as an HTML table.

Config keys (all optional, from the authority's `adapter_config`):
  table_selector: CSS selector for the table (default: the first table whose header mentions a keyword)
  header_keywords: words expected in the header row (default: ["date", "title", "subject", "description", "reference", "document"])
  columns: explicit mapping {title: 1, date: 0, reference: 2, decision: 3} by 0-based index or header text
  key_columns: which logical columns form the stable key (default: reference if present, else title+url)
  date_from_title: bool — extract date from the title text if no date column
"""
from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from .base import (
    Adapter,
    ListedItem,
    canon_url,
    dedupe,
    find_date,
    find_next_page,
    find_reference,
    is_doc_url,
    norm_ws,
    parse_date,
    register,
    stable_key,
)

DEFAULT_HEADER_KEYWORDS = ["date", "title", "subject", "description", "reference", "document", "decision", "release"]
LOGICAL = {
    "date": ["date", "released", "published", "decision date", "date of decision", "date released"],
    "title": ["title", "subject", "description", "information requested", "request", "summary", "details", "topic"],
    "reference": ["reference", "ref", "rti no", "number", "id", "file"],
    "decision": ["decision", "outcome", "result", "status"],
    "exemptions": ["exemption", "exemptions", "sections", "section"],
    "applicant": ["applicant", "applicant type"],
}


def _cell_text(td: Tag) -> str:
    return norm_ws(td.get_text(" ", strip=True))


def _match_logical(header: str) -> str | None:
    h = header.lower().strip()
    for logical, names in LOGICAL.items():
        for n in names:
            if h == n or h.startswith(n) or n in h:
                return logical
    return None


def select_table(soup: BeautifulSoup, config: dict) -> Tag | None:
    if config.get("table_selector"):
        return soup.select_one(config["table_selector"])
    kws = [k.lower() for k in config.get("header_keywords", DEFAULT_HEADER_KEYWORDS)]
    best, best_score = None, 0
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        text = header.get_text(" ", strip=True).lower()
        score = sum(1 for k in kws if k in text) + min(len(table.find_all("tr")), 50) / 50
        if score > best_score:
            best, best_score = table, score
    return best


@register("html_table")
class HtmlTableAdapter(Adapter):
    description = "Disclosure log as an HTML table; one row per release."

    def parse(self, body: bytes, base_url: str, config: dict) -> list[ListedItem]:
        soup = BeautifulSoup(body, "lxml")
        table = select_table(soup, config)
        if table is None:
            return []
        rows = table.find_all("tr")
        if not rows:
            return []
        header_cells = [_cell_text(c) for c in rows[0].find_all(["th", "td"])]
        has_header = any(rows[0].find_all("th")) or any(_match_logical(h) for h in header_cells)
        col_map: dict[str, int] = {}
        explicit = config.get("columns") or {}
        for logical, spec in explicit.items():
            if isinstance(spec, int):
                col_map[logical] = spec
            else:
                for i, h in enumerate(header_cells):
                    if str(spec).lower() in h.lower():
                        col_map[logical] = i
        if has_header:
            for i, h in enumerate(header_cells):
                lg = _match_logical(h)
                if lg and lg not in col_map:
                    col_map[lg] = i
        body_rows = rows[1:] if has_header else rows
        items: list[ListedItem] = []
        for tr in body_rows:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            texts = [_cell_text(c) for c in cells]
            if not any(texts):
                continue
            links = [canon_url(a["href"], base_url) for a in tr.find_all("a", href=True)]
            doc_urls = [u for u in links if is_doc_url(u)]
            page_urls = [u for u in links if not is_doc_url(u)]
            def col(name: str, texts=texts) -> str | None:
                i = col_map.get(name)
                return texts[i] if i is not None and i < len(texts) else None
            title = col("title") or max(texts, key=len)
            reference = col("reference") or find_reference(title, " ".join(texts))
            date_txt = col("date")
            published = parse_date(date_txt) if date_txt else None
            if not published:
                published = find_date(" ".join(texts))
            fields = {h if h else f"col{i}": t for i, (h, t) in enumerate(zip(header_cells + [""] * len(texts), texts))}
            for lg in ("decision", "exemptions", "applicant"):
                v = col(lg)
                if v:
                    fields[lg] = v
            url = doc_urls[0] if doc_urls else (page_urls[0] if page_urls else None)
            key_cols = config.get("key_columns") or (["reference", "title"] if reference else ["title", "url"])
            key_src = [reference if k == "reference" else url if k == "url" else title if k == "title" else col(k) for k in key_cols]
            if not any(key_src):
                key_src = [title, url]
            items.append(ListedItem(
                external_key=stable_key(*key_src), title=title, url=url, reference=reference,
                published_date=published, decision_date=parse_date(col("decision_date") or "") if col_map.get("decision_date") else None,
                fields=fields, document_urls=doc_urls, page_url=page_urls[0] if (page_urls and not doc_urls) else None,
            ))
        return dedupe(items)

    def next_page(self, body: bytes, base_url: str, config: dict) -> str | None:
        soup = BeautifulSoup(body, "lxml")
        sel = config.get("next_selector")
        if sel:
            a = soup.select_one(sel)
            return canon_url(a["href"], base_url) if a and a.has_attr("href") else None
        return None if config.get("no_pagination") else find_next_page(soup, base_url)
