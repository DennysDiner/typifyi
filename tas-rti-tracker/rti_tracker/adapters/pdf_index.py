"""Generic adapter for a disclosure log that is itself a PDF (an index document).

Rows are recovered from the text lines; link annotations in the PDF give document URLs where present.
Config keys:
  line_regex: regex with named groups (reference, date, title) applied to each text line
  min_items: default 1
"""
from __future__ import annotations

import io
import re

from pypdf import PdfReader

from .base import Adapter, ListedItem, canon_url, dedupe, find_date, find_reference, norm_ws, register, stable_key

DEFAULT_LINE = re.compile(
    r"^(?P<reference>(?:RTI|FOI)?[\s-]?\d[\d/-]{2,})?\s*(?P<title>.+?)\s+(?P<date>\d{1,2}[/ -](?:\d{1,2}|[A-Za-z]{3,9})[/ -]\d{2,4})\s*$"
)


def pdf_links(reader: PdfReader) -> list[str]:
    urls: list[str] = []
    for page in reader.pages:
        annots = page.get("/Annots") or []
        for a in annots:
            try:
                obj = a.get_object()
                uri = obj.get("/A", {}).get("/URI")
                if uri:
                    urls.append(str(uri))
            except Exception:
                continue
    return urls


@register("pdf_index")
class PdfIndexAdapter(Adapter):
    description = "Disclosure log published as a PDF index document."

    def parse(self, body: bytes, base_url: str, config: dict) -> list[ListedItem]:
        reader = PdfReader(io.BytesIO(body))
        links = [canon_url(u, base_url) for u in pdf_links(reader)]
        pat = re.compile(config["line_regex"]) if config.get("line_regex") else DEFAULT_LINE
        items: list[ListedItem] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = norm_ws(line)
                if len(line) < 8:
                    continue
                m = pat.match(line)
                if not m:
                    continue
                g = m.groupdict()
                title = norm_ws(g.get("title") or line)
                ref = norm_ws(g.get("reference") or "") or find_reference(line)
                date = find_date(g.get("date") or line)
                items.append(ListedItem(
                    external_key=stable_key(ref or title, date), title=title, reference=ref,
                    published_date=date, fields={"line": line}, url=None,
                ))
        # Attach links by order where counts match; otherwise keep as listing-level links.
        if links and len(links) == len(items):
            for it, u in zip(items, links):
                it.url = u
                it.document_urls = [u]
        elif links:
            for it in items:
                it.fields["listing_links"] = links[:50]
        if len(items) < int(config.get("min_items", 1)):
            return []
        return dedupe(items)
