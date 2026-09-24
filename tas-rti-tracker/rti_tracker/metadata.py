"""LLM metadata pass over extracted document text, with validation against the text.

Fields: request_subject, applicant_type, decision_date, decision_type (full|partial|refused|other),
exemptions_cited (list of normalised section citations), pages_released, pages_withheld, reference.
Each field is stored as its own row with verified=1 only when the model's supporting quote is found in
the document text (or, for exemptions, when the section citation itself appears). Anything else is
stored verified=0 with a verification_note — the UI labels it `unverified`.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .config import settings
from .db import tx, utcnow

FIELDS = ["reference", "request_subject", "applicant_type", "decision_date", "decision_type", "exemptions_cited", "pages_released", "pages_withheld"]

SYSTEM = """You extract structured metadata from Tasmanian Right to Information (RTI) decision letters and
disclosure-log releases. Answer ONLY with a JSON object. For every field give {"value": ..., "quote": "<verbatim
short quote from the text that supports the value, or null>"}. If the text does not support a value, set value
to null. Fields:
- reference: the authority's RTI reference number (e.g. "RTI 2024-25/031").
- request_subject: one sentence describing what was requested.
- applicant_type: one of journalist|member_of_parliament|organisation|individual|unknown, only if stated.
- decision_date: ISO date of the decision letter.
- decision_type: full|partial|refused|other — full release, partial release with exemptions, or refusal.
- exemptions_cited: list of section citations of the Right to Information Act 2009 cited as exemptions, each as
  a string like "s 35" or "s 37(1)(b)". Do not include s 33 (public interest test) as an exemption.
- pages_released: integer if stated. pages_withheld: integer if stated."""

CITE = re.compile(r"\b(?:s|ss|sec|section|sections)\.?\s*(\d{1,2})(\s*\([0-9a-z]+\))*", re.IGNORECASE)
RANGE = re.compile(r"\bss\.?\s*(\d{1,2})\s*(?:-|–|to|and)\s*(\d{1,2})", re.IGNORECASE)


def normalise_citations(text: str, exemption_sections: set[int]) -> list[str]:
    """Normalise citations like 's35', 'section 37(1)(b)', 'ss 36-37' into 's 35', 's 37(1)(b)', ... limited to
    sections listed as exemptions in legal/rules.yaml. s 33 is excluded (public interest test)."""
    out: list[str] = []
    for m in RANGE.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        for n in range(min(a, b), max(a, b) + 1):
            if n in exemption_sections and f"s {n}" not in out:
                out.append(f"s {n}")
    for m in CITE.finditer(text):
        n = int(m.group(1))
        if n not in exemption_sections:
            continue
        sub = re.sub(r"\s+", "", m.group(0)[m.end(1) - m.start():]) if m.group(2) else ""
        cite = f"s {n}{sub}"
        if cite not in out:
            out.append(cite)
    return out


def exemption_sections_from_rules(rules_raw: dict) -> set[int]:
    out = set()
    for e in rules_raw.get("exemptions", []):
        if e.get("is_exemption") is False:
            continue
        m = re.search(r"(\d+)", str(e.get("section", "")))
        if m:
            out.add(int(m.group(1)))
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def validate(field: str, value: Any, quote: str | None, text: str, exemption_sections: set[int]) -> tuple[bool, str]:
    t = _norm(text)
    if value in (None, "", []):
        return False, "no value"
    if field == "exemptions_cited":
        cites = normalise_citations(text, exemption_sections)
        missing = [c for c in value if c.split("(")[0] not in [x.split("(")[0] for x in cites]]
        return (not missing), ("all citations found in text" if not missing else f"not found in text: {missing}")
    if quote and _norm(quote) in t and len(_norm(quote)) >= 8:
        if field in ("pages_released", "pages_withheld") and str(value) not in quote:
            return False, "quote found but does not contain the number"
        if field == "decision_date":
            from .adapters.base import find_date
            if find_date(quote) != value:
                return False, "quote found but its date does not match the value"
        return True, "supporting quote found in text"
    if field == "reference" and _norm(str(value)) in t:
        return True, "reference string found in text"
    return False, "supporting quote not found in text"


def call_llm(text: str, model: str, api_key: str) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model, max_tokens=1500, system=SYSTEM,
        messages=[{"role": "user", "content": f"Document text (truncated to 60k chars):\n\n{text[:60000]}"}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    raw = raw.strip().strip("`")
    raw = raw.removeprefix("json")
    return json.loads(raw)


def run_metadata(conn: sqlite3.Connection, rules_raw: dict, *, limit: int = 20, llm=call_llm, model: str | None = None) -> int:
    st = settings()
    model = model or st.anthropic_model
    if llm is call_llm and not st.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    ex_secs = exemption_sections_from_rules(rules_raw)
    rows = conn.execute(
        "SELECT d.id, t.text FROM documents d JOIN document_text t ON t.document_id=d.id"
        " WHERE d.text_chars > 50 AND NOT EXISTS (SELECT 1 FROM document_metadata m WHERE m.document_id=d.id) ORDER BY d.id LIMIT ?",
        (limit,),
    ).fetchall()
    n = 0
    for r in rows:
        result = llm(r["text"], model, st.anthropic_api_key or "")
        now = utcnow()
        with tx(conn):
            for f in FIELDS:
                entry = result.get(f) or {}
                if not isinstance(entry, dict):
                    entry = {"value": entry, "quote": None}
                value, quote = entry.get("value"), entry.get("quote")
                if f == "exemptions_cited" and isinstance(value, list):
                    value = normalise_citations(" ".join(str(v) for v in value), ex_secs) or value
                ok, note = validate(f, value, quote, r["text"], ex_secs)
                conn.execute(
                    "INSERT INTO document_metadata(document_id,field,value,evidence_quote,verified,verification_note,model,extracted_at)"
                    " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(document_id,field) DO UPDATE SET value=excluded.value, evidence_quote=excluded.evidence_quote,"
                    " verified=excluded.verified, verification_note=excluded.verification_note, model=excluded.model, extracted_at=excluded.extracted_at",
                    (r["id"], f, json.dumps(value) if isinstance(value, (list, dict)) else (None if value is None else str(value)),
                     quote, 1 if ok else 0, note, model, now),
                )
        n += 1
    return n
