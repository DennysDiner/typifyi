"""Authority registry: load registry/authorities.yaml, validate, and sync into the DB.

The YAML is the source of truth for the registry; `rti registry sync` upserts it into `entities`,
`authorities`, `authority_names`, `authority_urls`, `minister_portfolios`, `mog_changes` and creates/updates
`sources` rows for every authority that has a disclosure log URL. Historic names and URLs are never deleted.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import CONFIG_DIR, REGISTRY_DIR, load_yaml
from .db import j, tx, utcnow

TYPES = {"agency", "minister", "gbe", "soc", "subsidiary", "statutory", "council", "council_entity", "university", "other", "business_unit"}
RTI_STATUS = {"full", "partial", "excluded", "UNCERTAIN", "via_parent"}
FORMATS = {"html_table", "html_list", "pdf_index", "per_release_pages", "none", "unknown"}


@dataclass
class ValidationError(Exception):
    errors: list[str]

    def __str__(self) -> str:
        return "\n".join(self.errors)


def load_registry(path: Path | None = None) -> dict:
    path = path or (REGISTRY_DIR / "authorities.yaml")
    data = load_yaml(path)
    data.setdefault("authorities", [])
    data.setdefault("minister_portfolios", [])
    data.setdefault("mog_changes", [])
    data.setdefault("name_history", [])
    return data


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    for a in data["authorities"]:
        aid = a.get("id")
        if not aid or not isinstance(aid, str) or not all(c.islower() or c.isdigit() or c == "_" for c in aid):
            errors.append(f"bad id: {aid!r}")
        if aid in ids:
            errors.append(f"duplicate id: {aid}")
        ids.add(aid)
        if not a.get("name"):
            errors.append(f"{aid}: missing name")
        if a.get("type") not in TYPES:
            errors.append(f"{aid}: bad type {a.get('type')!r}")
        if a.get("rti_status") not in RTI_STATUS:
            errors.append(f"{aid}: bad rti_status {a.get('rti_status')!r}")
        if a.get("disclosure_log_format", "unknown") not in FORMATS:
            errors.append(f"{aid}: bad disclosure_log_format {a.get('disclosure_log_format')!r}")
        if a.get("disclosure_log_url") and a.get("disclosure_log_format") in (None, "none"):
            errors.append(f"{aid}: has disclosure_log_url but format is none")
        if a.get("tier") not in (None, 1, 2):
            errors.append(f"{aid}: tier must be 1 or 2")
    for a in data["authorities"]:
        p = a.get("parent_id")
        if p and p not in ids:
            errors.append(f"{a['id']}: parent_id {p} not in registry")
    return errors


def tier_for(authority: dict, scheduler_cfg: dict) -> int:
    if authority.get("tier") in (1, 2):
        return int(authority["tier"])
    tier1 = set(scheduler_cfg.get("tier1_authorities", []))
    if authority["id"] in tier1:
        return 1
    if authority.get("type") == "minister" and authority.get("campaign_relevant"):
        return 1
    return 2


def sync(conn: sqlite3.Connection, data: dict | None = None, scheduler_cfg: dict | None = None) -> dict:
    data = data or load_registry()
    scheduler_cfg = scheduler_cfg if scheduler_cfg is not None else load_yaml(CONFIG_DIR / "scheduler.yaml")
    errs = validate(data)
    if errs:
        raise ValidationError(errs)
    now = utcnow()
    stats = {"authorities": 0, "sources_created": 0, "sources_updated": 0, "sources_disabled": 0}
    with tx(conn):
        for a in data["authorities"]:
            aid = a["id"]
            aliases = a.get("aliases") or []
            conn.execute(
                "INSERT INTO entities(id,kind,name,aliases,external_ids,created_at,updated_at) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name, aliases=excluded.aliases, updated_at=excluded.updated_at",
                (aid, "minister" if a["type"] == "minister" else "authority", a["name"], j(aliases), j(a.get("external_ids") or {}), now, now),
            )
            tier = tier_for(a, scheduler_cfg)
            conn.execute(
                "INSERT INTO authorities(id,name,type,rti_status,rti_status_basis,portfolio_minister,parent_id,region,rti_page_url,"
                "disclosure_log_url,disclosure_log_format,rti_contact_email,annual_report_url,website,tier,active,verification_status,"
                "last_verified,source_of_listing,notes,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name,type=excluded.type,rti_status=excluded.rti_status,"
                "rti_status_basis=excluded.rti_status_basis,portfolio_minister=excluded.portfolio_minister,parent_id=excluded.parent_id,"
                "region=excluded.region,rti_page_url=excluded.rti_page_url,disclosure_log_url=excluded.disclosure_log_url,"
                "disclosure_log_format=excluded.disclosure_log_format,rti_contact_email=excluded.rti_contact_email,"
                "annual_report_url=excluded.annual_report_url,website=excluded.website,tier=excluded.tier,active=excluded.active,"
                "verification_status=excluded.verification_status,last_verified=excluded.last_verified,"
                "source_of_listing=excluded.source_of_listing,notes=excluded.notes,raw=excluded.raw",
                (aid, a["name"], a["type"], a["rti_status"], a.get("rti_status_basis"), a.get("portfolio_minister"),
                 None, a.get("region"), a.get("rti_page_url"), a.get("disclosure_log_url"),
                 a.get("disclosure_log_format") or "unknown", a.get("rti_contact_email"), a.get("annual_report_url"),
                 a.get("website"), tier, 0 if a.get("active") is False else 1, a.get("verification_status"),
                 str(a.get("last_verified")) if a.get("last_verified") else None, j(a.get("source_of_listing") or []),
                 a.get("notes"), j(a)),
            )
            stats["authorities"] += 1
            # names (current + aliases + history) — insert if absent, never delete
            for nm in [a["name"], *aliases]:
                if not conn.execute("SELECT 1 FROM authority_names WHERE authority_id=? AND name=?", (aid, nm)).fetchone():
                    conn.execute("INSERT INTO authority_names(authority_id,name,effective_from,effective_to,source) VALUES (?,?,?,?,?)",
                                 (aid, nm, None, None, "registry"))
            for kind in ("website", "rti_page_url", "disclosure_log_url", "annual_report_url"):
                u = a.get(kind)
                if u and not conn.execute("SELECT 1 FROM authority_urls WHERE authority_id=? AND url=? AND kind=?", (aid, u, kind)).fetchone():
                    conn.execute("INSERT INTO authority_urls(authority_id,url,kind,effective_from,source) VALUES (?,?,?,?,?)",
                                 (aid, u, kind, None, "registry"))
            # sources
            log_url = a.get("disclosure_log_url")
            fmt = a.get("disclosure_log_format") or "unknown"
            adapter = a.get("adapter") or (fmt if fmt in ("html_table", "html_list", "pdf_index", "per_release_pages") else ("auto" if fmt == "unknown" else None))
            inactive = a.get("active") is False
            if log_url and adapter and not a.get("shares_source_with") and not inactive:
                cfg = j(a.get("adapter_config") or {})
                row = conn.execute("SELECT id, enabled FROM sources WHERE authority_id=? AND kind='disclosure_log' AND url=?", (aid, log_url)).fetchone()
                if row:
                    conn.execute("UPDATE sources SET adapter=?, tier=?, config=?, enabled=1 WHERE id=?", (adapter, tier, cfg, row["id"]))
                    stats["sources_updated"] += 1
                else:
                    conn.execute("INSERT INTO sources(authority_id,kind,adapter,url,tier,enabled,config) VALUES (?,?,?,?,?,1,?)",
                                 (aid, "disclosure_log", adapter, log_url, tier, cfg))
                    stats["sources_created"] += 1
                # disable other disclosure_log sources for this authority whose URL changed (keep history)
                n = conn.execute("UPDATE sources SET enabled=0 WHERE authority_id=? AND kind='disclosure_log' AND url<>? AND enabled=1",
                                 (aid, log_url)).rowcount
                stats["sources_disabled"] += n
            else:
                # no log URL, shared source, or inactive authority: any leftover disclosure_log source is switched off (audit #7, #14)
                n = conn.execute("UPDATE sources SET enabled=0 WHERE authority_id=? AND kind='disclosure_log' AND enabled=1", (aid,)).rowcount
                stats["sources_disabled"] += n
            for extra in a.get("extra_sources") or []:
                row = conn.execute("SELECT id FROM sources WHERE authority_id=? AND kind=? AND url=?", (aid, extra["kind"], extra["url"])).fetchone()
                if not row:
                    conn.execute("INSERT INTO sources(authority_id,kind,adapter,url,tier,enabled,config) VALUES (?,?,?,?,?,1,?)",
                                 (aid, extra["kind"], extra["adapter"], extra["url"], tier, j(extra.get("config") or {})))
                    stats["sources_created"] += 1
        for a in data["authorities"]:
            if a.get("parent_id"):
                conn.execute("UPDATE authorities SET parent_id=? WHERE id=?", (a["parent_id"], a["id"]))
        for h in data.get("name_history", []):
            if not conn.execute("SELECT 1 FROM authority_names WHERE authority_id=? AND name=?", (h["id"], h["former_name"])).fetchone():
                conn.execute("INSERT INTO authority_names(authority_id,name,effective_from,effective_to,source) VALUES (?,?,?,?,?)",
                             (h["id"], h["former_name"], str(h.get("effective_from") or "") or None, str(h.get("effective_to") or "") or None, h.get("evidence")))
        conn.execute("DELETE FROM minister_portfolios")
        for m in data.get("minister_portfolios", []):
            conn.execute("INSERT INTO minister_portfolios(portfolio,minister,department_ids,effective_from,effective_to,evidence,campaign_relevant)"
                         " VALUES (?,?,?,?,?,?,?)",
                         (m["portfolio"], m["minister"], j(m.get("department_ids") or []), str(m.get("effective_from") or "") or None,
                          str(m.get("effective_to") or "") or None, m.get("evidence"), 1 if m.get("campaign_relevant") else 0))
        conn.execute("DELETE FROM mog_changes")
        for c in data.get("mog_changes", []):
            conn.execute("INSERT INTO mog_changes(date,change,from_ids,to_ids,evidence) VALUES (?,?,?,?,?)",
                         (str(c["date"]), c["change"], j(c.get("from_ids") or []), j(c.get("to_ids") or []), c.get("evidence")))
        # adjacent (non-authority) sources from config
        for s in scheduler_cfg.get("adjacent_sources", []):
            row = conn.execute("SELECT id FROM sources WHERE kind=? AND url=?", (s["kind"], s["url"])).fetchone()
            if not row:
                conn.execute("INSERT INTO sources(authority_id,kind,adapter,url,tier,enabled,config) VALUES (?,?,?,?,?,?,?)",
                             (s.get("authority_id"), s["kind"], s["adapter"], s["url"], int(s.get("tier", 2)), 1 if s.get("enabled", True) else 0, j(s.get("config") or {})))
                stats["sources_created"] += 1
    return stats


def resolve_authority(conn: sqlite3.Connection, name: str, *, candidates: bool = False):
    """Map an authority name (current, historical or alias) to an id by EXACT match only (audit #12: loose
    substring matching hid registry gaps). With candidates=True, return up to 5 fuzzy suggestions instead."""
    n = " ".join(name.lower().split()).strip(" .,")
    row = conn.execute("SELECT authority_id FROM authority_names WHERE lower(name)=? LIMIT 1", (n,)).fetchone()
    if row and not candidates:
        return row[0]
    if row and candidates:
        return [row[0]]
    if not candidates:
        return None
    import difflib
    names = {r["name"]: r["authority_id"] for r in conn.execute("SELECT name, authority_id FROM authority_names")}
    close = difflib.get_close_matches(name, list(names), n=5, cutoff=0.5)
    return [f"{names[c]} ({c})" for c in close]


def coverage_report(data: dict, conn: sqlite3.Connection | None = None) -> str:
    """Markdown: authorities with no discoverable disclosure log, grouped by type. This gap is a finding."""
    all_active = [a for a in data["authorities"] if a.get("active", True) is not False]
    units = [a for a in all_active if a.get("rti_status") == "via_parent" or a.get("type") == "business_unit"]
    auths = [a for a in all_active if a not in units]
    by_type: dict[str, list[dict]] = {}
    for a in auths:
        by_type.setdefault(a["type"], []).append(a)
    lines = ["# Coverage report", "", f"Generated {utcnow()} from registry/authorities.yaml.", "",
             "**Read before quoting any number here.** The registry was researched under a network policy that blocked every",
             "primary source and a search budget that ran out part-way (DECISIONS.md D3). 'No log found' therefore means one of two",
             "different things, and the tables below keep them apart: *searched, none found* (a log-specific search was run and",
             "returned nothing) versus *not yet searched*. Only the first is a finding, and even that is provisional until the",
             "authority's RTI page has been fetched and read (README: verification pass).", ""]
    total = len(auths)
    with_log = [a for a in auths if a.get("disclosure_log_url")]
    verified_log = [a for a in with_log if (a.get("disclosure_log_url_evidence") or "") == "snippet_verified"]
    no_log = [a for a in auths if not a.get("disclosure_log_url")]
    searched = [a for a in no_log if search_status(a) == "searched_none_found"]
    unsearched = [a for a in no_log if search_status(a) != "searched_none_found"]
    lines += [
        "| Metric | Count |", "|---|---|",
        f"| Active public authorities in registry (business units of departments excluded: {len(units)}) | {total} |",
        f"| With a disclosure log URL recorded | {len(with_log)} |",
        f"| … of which URL was seen in a search result (snippet_verified) | {len(verified_log)} |",
        f"| No log URL — log-specific search run, none found (provisional finding) | {len(searched)} |",
        f"| No log URL — NOT yet searched (not a finding) | {len(unsearched)} |",
        f"| rti_status UNCERTAIN | {sum(1 for a in auths if a.get('rti_status') == 'UNCERTAIN')} |",
        f"| Excluded / partial | {sum(1 for a in auths if a.get('rti_status') in ('excluded', 'partial'))} |",
        "",
    ]
    if conn is not None:
        rows = conn.execute("SELECT authority_id, last_success_at, last_change_at, consecutive_failures, blocked FROM sources WHERE kind='disclosure_log' AND enabled=1").fetchall()
        lines += ["## Log health (from DB)", "", "| Authority | Last success | Last change | Failures | Blocked |", "|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['authority_id']} | {r['last_success_at'] or '-'} | {r['last_change_at'] or '-'} | {r['consecutive_failures']} | {'yes' if r['blocked'] else ''} |")
        lines.append("")
    for heading, bucket, blurb in [
        ("Searched, no log found (provisional findings)", searched,
         "A log-specific search was run for each of these and returned nothing. Confirm by reading the RTI page before citing."),
        ("Not yet searched (NOT findings)", unsearched,
         "No log-specific search was run (search budget exhausted). These rows say nothing about whether a log exists."),
    ]:
        lines += [f"## {heading}", "", blurb, ""]
        for t in sorted(by_type):
            rows = [a for a in by_type[t] if a in bucket]
            if not rows:
                continue
            lines += [f"### {t} ({len(rows)} of {len(by_type[t])})", "", "| id | Name | RTI page | Status | Notes |", "|---|---|---|---|---|"]
            for a in sorted(rows, key=lambda x: x["name"]):
                lines.append(f"| {a['id']} | {a['name']} | {a.get('rti_page_url') or '-'} | {a.get('rti_status')} | {(a.get('notes') or '')[:120].replace('|', '/')} |")
            lines.append("")
    lines += ["## Authorities with a disclosure log", "", "| id | Name | Format | URL | Evidence |", "|---|---|---|---|---|"]
    for a in sorted(with_log, key=lambda x: x["name"]):
        lines.append(f"| {a['id']} | {a['name']} | {a.get('disclosure_log_format')} | {a['disclosure_log_url']} | {a.get('disclosure_log_url_evidence') or '-'} |")
    lines.append("")
    return "\n".join(lines)


def search_status(a: dict) -> str:
    """Whether a log-specific search was actually run for this record (from the research slices' `queries`)."""
    qs = [q.lower() for q in (a.get("queries") or [])]
    if any("disclosure log" in q or "disclosure" in q or "rti" in q for q in qs):
        return "searched_none_found" if not a.get("disclosure_log_url") else "searched_found"
    return "not_searched"


def export_coverage_csv(data: dict) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["id", "name", "type", "rti_status", "portfolio_minister", "rti_page_url", "disclosure_log_url", "disclosure_log_format", "disclosure_log_url_evidence", "verification_status", "notes"]
    w.writerow(cols + ["search_status"])
    for a in data["authorities"]:
        w.writerow([a.get(k) for k in cols] + [search_status(a)])
    return buf.getvalue()
