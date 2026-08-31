"""Shared HTML extraction helpers.

Extraction keys on *URL shape and labelled text*, not on CSS classes: government
sites rewrite their markup far more often than they rewrite their routes, and a
class-based selector fails silently the day a theme changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from tnw.normalise import canonical_url, normalise_text, strip_volatile_html

ROW_TAGS = ("tr", "li", "article", "section", "div", "td", "p")


@dataclass
class LinkHit:
    url: str
    text: str
    element: Tag

    @property
    def row(self) -> Tag:
        return row_container(self.element)


def parse(html: str) -> BeautifulSoup:
    return strip_volatile_html(html)


def find_links(
    soup: BeautifulSoup,
    base_url: str,
    pattern: re.Pattern[str],
    *,
    match_text: bool = False,
) -> list[LinkHit]:
    """All anchors whose resolved href (or text) matches ``pattern``."""
    hits: list[LinkHit] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        resolved = canonical_url(urljoin(base_url, href))
        text = " ".join(anchor.get_text(" ").split())
        target = f"{resolved}\n{text}" if match_text else resolved
        if not pattern.search(target):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        hits.append(LinkHit(url=resolved, text=text, element=anchor))
    return hits


def row_container(element: Tag) -> Tag:
    """The nearest ancestor that looks like a record row."""
    best = element
    for parent in element.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name in ("body", "html", "[document]"):
            break
        best = parent
        if parent.name in ("tr", "li", "article"):
            return parent
        text = parent.get_text(" ", strip=True)
        if len(text) > 40:
            return parent
    return best


def row_text(element: Tag) -> str:
    """Normalised text of a row, with cell boundaries preserved as ' | '."""
    if element.name == "tr":
        cells = element.find_all(["td", "th"], recursive=False) or element.find_all(["td", "th"])
        if cells:
            return " | ".join(
                " ".join(cell.get_text(" ").split()) for cell in cells
            ).strip()
    return normalise_text(element.get_text("\n")).replace("\n", " | ")


def table_cells(row: Tag) -> dict[str, str]:
    """Map a table row's cells to their column headers.

    Listings are usually tables whose rows carry no labels at all — the labels
    live once, in the header row — so a label-based extractor has to look there.
    """
    if row.name != "tr":
        return {}
    table = row.find_parent("table")
    if table is None:
        return {}
    header_cells: list[Tag] = []
    head = table.find("thead")
    if head is not None:
        header_row = head.find("tr")
        if header_row is not None:
            header_cells = header_row.find_all(["th", "td"])
    if not header_cells:
        for candidate in table.find_all("tr"):
            cells = candidate.find_all(["th", "td"])
            if cells and all(cell.name == "th" for cell in cells):
                header_cells = cells
                break
    if not header_cells:
        return {}
    headers = [" ".join(cell.get_text(" ").split()).strip(" :") for cell in header_cells]
    values = row.find_all(["td", "th"])
    mapping: dict[str, str] = {}
    for index, header in enumerate(headers):
        if not header or index >= len(values):
            continue
        value = " ".join(values[index].get_text(" ").split()).strip()
        if value:
            mapping[header.lower()] = value
    return mapping


def value_from_cells(cells: dict[str, str], labels: Sequence[str]) -> str | None:
    """Look a label up in a header->value map, exactly then by prefix."""
    if not cells:
        return None
    lowered = {label.lower(): label for label in labels}
    for label in lowered:
        if label in cells:
            return cells[label]
    for header, value in cells.items():
        for label in lowered:
            if header.startswith(label) or label.startswith(header):
                return value
    return None


def labelled_value(text: str, labels: Sequence[str]) -> str | None:
    """Pull ``Label: value`` (or ``Label | value``) out of a row of text."""
    for label in labels:
        pattern = re.compile(
            r"(?i)(?:^|\||\n)\s*" + re.escape(label) + r"\s*(?:[:\-–]|\|)\s*([^|\n]{1,200})"
        )
        match = pattern.search(text)
        if match:
            value = match.group(1).strip(" .;")
            if value:
                return value
    return None


def cell_after_header(soup: BeautifulSoup, labels: Sequence[str]) -> str | None:
    """Value from a definition list or two-column table keyed by a header cell."""
    lowered = {label.lower() for label in labels}
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            key = " ".join(cells[0].get_text(" ").split()).strip(" :").lower()
            if key in lowered:
                value = " ".join(cells[1].get_text(" ").split()).strip()
                if value:
                    return value
    for term in soup.find_all("dt"):
        key = " ".join(term.get_text(" ").split()).strip(" :").lower()
        if key in lowered:
            definition = term.find_next_sibling("dd")
            if definition is not None:
                value = " ".join(definition.get_text(" ").split()).strip()
                if value:
                    return value
    return None


def field_block(fields: dict[str, str | None]) -> str:
    """Render extracted fields as a deterministic ``key: value`` block.

    The Item schema is fixed (§2.4), so per-source structured fields ride at the
    head of ``body_text`` in a stable, greppable form rather than as ad-hoc
    columns. Values are exactly as stated by the source.
    """
    lines = [f"{key}: {value}" for key, value in fields.items() if value]
    return "\n".join(lines)


def page_text(html: str) -> str:
    soup = parse(html)
    return normalise_text(soup.get_text("\n"))


def compile_any(patterns: Iterable[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
