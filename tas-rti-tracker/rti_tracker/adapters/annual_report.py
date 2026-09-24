"""Annual RTI statistical report (Department of Justice, s 53).

Listing adapter: the annual-reports page lists one PDF per year. Each PDF becomes an item/document.
`parse_report_pdf()` turns the PDF's per-authority tables into `annual_stats` rows. The table layout has
not been observed (network blocked at build time; see research/annual_report_crosscheck.md), so the parser
is heuristic: it scans text lines for "<authority name> <int> <int> ..." patterns and records the raw
line; `rti annual-report import <pdf>` prints unmatched lines for manual mapping.
"""
from __future__ import annotations

import io
import re
import sqlite3

from pypdf import PdfReader

from ..db import tx, utcnow
from .base import ListedItem, canon_url, find_date, is_doc_url, norm_ws, register, stable_key
from .html_list import HtmlListAdapter

YEAR = re.compile(r"(20\d{2})\s*[-–/]\s*(\d{2,4})")
ROW = re.compile(r"^(?P<name>[A-Z][A-Za-z&,'()./ -]{4,80}?)\s+(?P<nums>(?:\d[\d,]*\s+){1,12}\d[\d,]*)\s*$")
SECTORS = ("department", "council", "minister", "other public authorit", "government business", "state-owned", "total")


@register("annual_report")
class AnnualReportAdapter(HtmlListAdapter):
    description = "Department of Justice RTI annual report listing (one PDF per year)."

    def parse(self, body: bytes, base_url: str, config: dict) -> list[ListedItem]:
        items = super().parse(body, base_url, config)
        out = []
        for it in items:
            m = YEAR.search(it.title) or YEAR.search(it.url or "")
            if not m:
                continue
            year = f"{m.group(1)}-{m.group(2)[-2:]}"
            it.external_key = f"annual_report_{year}"
            it.fields["report_year"] = year
            it.fields["kind"] = "annual_report"
            out.append(it)
        return out


def parse_report_pdf(data: bytes) -> tuple[list[dict], list[str]]:
    """Return (rows, unmatched_lines). Row: {authority_raw, values:[...], page, sector_hint}."""
    reader = PdfReader(io.BytesIO(data))
    rows: list[dict] = []
    unmatched: list[str] = []
    sector = None
    for pno, page in enumerate(reader.pages, start=1):
        for raw in (page.extract_text() or "").splitlines():
            line = norm_ws(raw)
            low = line.lower()
            for s in SECTORS:
                if low.startswith(s) and len(line) < 60:
                    sector = s
            m = ROW.match(line)
            if m:
                nums = [int(n.replace(",", "")) for n in m.group("nums").split()]
                rows.append({"authority_raw": m.group("name").strip(), "values": nums, "page": pno, "sector_hint": sector})
            elif any(ch.isdigit() for ch in line) and len(line) > 12:
                unmatched.append(f"p{pno}: {line}")
    return rows, unmatched


DEFAULT_COLUMNS = ["applications_received", "applications_decided", "released_full", "released_part", "refused", "decided_within_20wd"]


def import_report(conn: sqlite3.Connection, data: bytes, report_year: str, source_url: str | None, sha256: str | None,
                  columns: list[str] | None = None, resolve=None) -> dict:
    """Persist parsed rows as annual_stats. `columns` names the numeric columns in order (layout is
    unverified — pass the real header order once the PDF has been inspected)."""
    columns = columns or DEFAULT_COLUMNS
    rows, unmatched = parse_report_pdf(data)
    now = utcnow()
    n = 0
    with tx(conn):
        for r in rows:
            aid = resolve(r["authority_raw"]) if resolve else None
            for metric, val in zip(columns, r["values"]):
                conn.execute(
                    "INSERT INTO annual_stats(report_year,authority_id,authority_raw,metric,value,source_url,sha256,page,extracted_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(report_year,authority_raw,metric) DO UPDATE SET value=excluded.value,"
                    " authority_id=COALESCE(excluded.authority_id, annual_stats.authority_id), extracted_at=excluded.extracted_at",
                    (report_year, aid, r["authority_raw"], metric, val, source_url, sha256, r["page"], now),
                )
                n += 1
    return {"rows": len(rows), "stats": n, "unmatched": unmatched}
