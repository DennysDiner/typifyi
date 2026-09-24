"""Command-line interface: `rti <group> <command>`."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import click

from . import db as dbm
from .archive import Archive
from .config import CONFIG_DIR, LEGAL_DIR, REGISTRY_DIR, load_yaml, settings


def _conn():
    st = settings()
    conn = dbm.connect(st.db_path)
    dbm.migrate(conn)
    return conn


def _archive(conn):
    return Archive(conn, settings().archive_dir)


def _fetcher(conn):
    from .fetch import Fetcher
    st = settings()
    return Fetcher(conn, _archive(conn), st.user_agent)


@click.group()
def main() -> None:
    """Tasmanian RTI tracker."""


@main.command()
def init() -> None:
    """Create/migrate the database, sync registry, watchlist and holidays."""
    conn = _conn()
    from . import holidays_cal, registry, watchlist
    click.echo(f"db: {settings().db_path}")
    click.echo(f"registry: {registry.sync(conn)}")
    click.echo(f"watchlist campaigns: {watchlist.sync(conn, settings().watchlist)}")
    y = date.today().year
    click.echo(f"holidays rows: {holidays_cal.sync_to_db(conn, list(range(y - 2, y + 3)))}")


# ---- registry ----------------------------------------------------------------------------------
@main.group()
def registry() -> None:
    """Authority registry commands."""


@registry.command("merge")
def registry_merge() -> None:
    """Rebuild registry/authorities.yaml from the research slices + overrides."""
    import runpy
    runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts" / "merge_registry.py"), run_name="__main__")


@registry.command("validate")
def registry_validate() -> None:
    from .registry import load_registry, validate
    errs = validate(load_registry())
    for e in errs:
        click.echo(e)
    click.echo("OK" if not errs else f"{len(errs)} errors")
    sys.exit(1 if errs else 0)


@registry.command("sync")
def registry_sync() -> None:
    from .registry import sync
    click.echo(json.dumps(sync(_conn())))


@registry.command("coverage")
@click.option("--csv", "as_csv", is_flag=True)
@click.option("--out", type=click.Path(), default=None)
def registry_coverage(as_csv: bool, out: str | None) -> None:
    """Write coverage_report.md (authorities with no discoverable disclosure log — a finding in itself)."""
    from .registry import coverage_report, export_coverage_csv, load_registry
    data = load_registry()
    conn = _conn()
    text = export_coverage_csv(data) if as_csv else coverage_report(data, conn)
    if out:
        Path(out).write_text(text)
        click.echo(f"wrote {out}")
    else:
        click.echo(text)


@registry.command("suggest-formats")
def registry_suggest_formats() -> None:
    """Print formats detected by the auto adapter so they can be written into the registry."""
    conn = _conn()
    for r in conn.execute("SELECT authority_id, config FROM sources WHERE adapter='auto'"):
        cfg = json.loads(r["config"] or "{}")
        if cfg.get("detected_format"):
            click.echo(f"{r['authority_id']}: {cfg['detected_format']}")


# ---- polling -----------------------------------------------------------------------------------
@main.command()
@click.option("--tier", type=int, default=None)
@click.option("--authority", default=None)
@click.option("--force", is_flag=True, help="Poll even if not due / unchanged.")
@click.option("--limit", type=int, default=None)
@click.option("--loop", is_flag=True)
def poll(tier: int | None, authority: str | None, force: bool, limit: int | None, loop: bool) -> None:
    """Poll due sources (scheduler); use --authority to poll one."""
    from .monitor import Monitor
    from .scheduler import SchedulerConfig, run_due, schedule_next
    from .scheduler import loop as run_loop
    conn = _conn()
    mon = Monitor(conn, _fetcher(conn))
    cfg = SchedulerConfig.from_dict(settings().scheduler)
    if authority:
        rows = conn.execute("SELECT id FROM sources WHERE authority_id=? AND enabled=1", (authority,)).fetchall()
        for r in rows:
            rep = mon.poll(int(r["id"]), force=True)
            schedule_next(conn, cfg, int(r["id"]), rep)
            click.echo(json.dumps(rep.__dict__, default=str))
        return
    if loop:
        run_loop(conn, mon, cfg, after_tick=lambda reps: [click.echo(json.dumps(r.__dict__, default=str)) for r in reps])
        return
    for rep in run_due(conn, mon, cfg, tier=tier, limit=limit, force=force):
        click.echo(json.dumps(rep.__dict__, default=str))


@main.command()
def health() -> None:
    """Per-authority freshness report."""
    from .health import format_table, health_rows, summary
    rows = health_rows(_conn())
    click.echo(format_table(rows))
    click.echo(json.dumps(summary(rows)))


@main.command()
@click.option("--limit", type=int, default=50)
@click.option("--no-ocr", is_flag=True)
def extract(limit: int, no_ocr: bool) -> None:
    """Extract text (and OCR) for documents without text."""
    from .extract import extract_pending
    conn = _conn()
    click.echo(f"extracted {extract_pending(conn, _archive(conn), limit=limit, allow_ocr=not no_ocr)}")


@main.command()
@click.option("--limit", type=int, default=20)
def metadata(limit: int) -> None:
    """Run the LLM metadata pass over extracted documents (needs ANTHROPIC_API_KEY)."""
    from .metadata import run_metadata
    import yaml
    rules = yaml.safe_load((LEGAL_DIR / "rules.yaml").read_text())
    click.echo(f"processed {run_metadata(_conn(), rules, limit=limit)}")


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--digest", is_flag=True, help="Send the daily digest.")
def alerts(dry_run: bool, digest: bool) -> None:
    """Send immediate alerts (and deadline alerts); --digest sends the daily digest."""
    from .alerts import process_changes, send_deadline_alerts, send_digest
    conn = _conn()
    click.echo(json.dumps(process_changes(conn, dry_run=dry_run)))
    click.echo(f"deadline alerts: {send_deadline_alerts(conn, dry_run=dry_run)}")
    if digest:
        click.echo(f"digest changes: {send_digest(conn, dry_run=dry_run)}")


@main.command()
def run() -> None:
    """One scheduler tick: poll due sources, extract, alerts. Intended for cron every 5–10 minutes."""
    from .alerts import process_changes, send_deadline_alerts
    from .extract import extract_pending
    from .monitor import Monitor
    from .scheduler import SchedulerConfig, run_due
    conn = _conn()
    mon = Monitor(conn, _fetcher(conn))
    reps = run_due(conn, mon, SchedulerConfig.from_dict(settings().scheduler))
    changed = [r for r in reps if r.status == "changed"]
    click.echo(f"polled {len(reps)}; changed {len(changed)}; errors {sum(1 for r in reps if r.status in ('error','blocked'))}")
    click.echo(f"extracted {extract_pending(conn, _archive(conn))}")
    from .applications import link_releases
    link_releases(conn)
    click.echo(json.dumps(process_changes(conn)))
    click.echo(f"deadline alerts {send_deadline_alerts(conn)}")


# ---- archive -----------------------------------------------------------------------------------
@main.group()
def archive() -> None:
    """Archive integrity."""


@archive.command("verify")
def archive_verify() -> None:
    conn = _conn()
    a = _archive(conn)
    bad = [r["sha256"] for r in conn.execute("SELECT sha256 FROM blobs") if not a.verify(r["sha256"])]
    click.echo(f"blobs: {conn.execute('SELECT count(*) FROM blobs').fetchone()[0]}, corrupt/missing: {len(bad)}")
    for b in bad:
        click.echo(b)


# ---- applications ------------------------------------------------------------------------------
@main.group()
def app() -> None:
    """Kurt's own applications."""


@app.command("new")
@click.option("--authority", required=True, help="registry id or free-text name")
@click.option("--lodged", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--accepted", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--scope", required=True)
@click.option("--reference", default=None)
@click.option("--fee", type=float, default=None)
@click.option("--waiver", default=None)
@click.option("--notes", default=None)
def app_new(authority, lodged, accepted, scope, reference, fee, waiver, notes) -> None:
    from .applications import create
    from .registry import resolve_authority
    conn = _conn()
    aid = authority if conn.execute("SELECT 1 FROM authorities WHERE id=?", (authority,)).fetchone() else resolve_authority(conn, authority)
    app_id = create(conn, authority_id=aid, authority_name=authority if not aid else None, lodged=lodged.date(), scope=scope,
                    reference=reference, fee_amount=fee, fee_waiver=waiver, accepted=accepted.date() if accepted else None, notes=notes)
    click.echo(f"application #{app_id} (authority_id={aid})")


@app.command("event")
@click.argument("app_id", type=int)
@click.argument("event")
@click.argument("when", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--detail", default="{}", help="JSON, e.g. '{\"decision_maker\": \"minister\", \"outcome\": \"partial\"}' or '{\"new_due_date\": \"2026-10-01\"}'")
def app_event(app_id, event, when, detail) -> None:
    from .applications import add_event
    add_event(_conn(), app_id, event, when.date(), json.loads(detail))
    click.echo("ok")


@app.command("attach")
@click.argument("app_id", type=int)
@click.argument("path", type=click.Path(exists=True))
@click.option("--description", default=None)
def app_attach(app_id, path, description) -> None:
    from .applications import add_attachment
    conn = _conn()
    click.echo(add_attachment(conn, _archive(conn), app_id, Path(path), description))


@app.command("status")
@click.argument("app_id", type=int, required=False)
@click.option("--today", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
def app_status(app_id, today) -> None:
    from .applications import status_for
    from .deadlines import DeadlineEngine
    conn = _conn()
    eng = DeadlineEngine(today=today.date() if today else None)
    ids = [app_id] if app_id else [r["id"] for r in conn.execute("SELECT id FROM applications ORDER BY id")]
    for i in ids:
        a = conn.execute("SELECT * FROM applications WHERE id=?", (i,)).fetchone()
        st = status_for(conn, i, eng)
        click.echo(f"#{i} {a['authority_name'] or a['authority_id']} — {a['reference'] or ''}\n  state: {st.state} ({st.state_section}) — {st.state_note}")
        for d in st.deadlines:
            click.echo(f"  {'PASSED ' if d.passed else ''}{d.display()}")
        click.echo("  what you can do next:")
        for s in st.next_steps:
            click.echo(f"   - {s['title']} [{s['section']}]" + (f" by {s['deadline']}" if s["deadline"] else ""))
        for w in st.warnings:
            click.echo(f"  ! {w}")


@app.command("link")
@click.argument("app_id", type=int, required=False)
def app_link(app_id) -> None:
    from .applications import link_releases
    for p in link_releases(_conn(), app_id):
        click.echo(json.dumps(p))


@app.command("events")
def app_events() -> None:
    from .deadlines import ALL_EVENTS
    click.echo("\n".join(ALL_EVENTS))


# ---- holidays ----------------------------------------------------------------------------------
@main.group()
def holidays() -> None:
    """Public-holiday calendar."""


@holidays.command("show")
@click.option("--year", type=int, default=None)
@click.option("--include-unverified", is_flag=True)
def holidays_show(year, include_unverified) -> None:
    from .holidays_cal import build_calendar
    y = year or date.today().year
    cal = build_calendar([y], include_unverified)
    for d, n in sorted(cal.statewide.items()):
        click.echo(f"{d} statewide  {n}")
    for reg, days in cal.regional.items():
        for d, n in sorted(days.items()):
            click.echo(f"{d} {reg:10} {n}")
    click.echo("sources: " + "; ".join(cal.sources))


@holidays.command("import-csv")
@click.argument("path", type=click.Path(exists=True))
@click.option("--source-url", required=True)
def holidays_import(path, source_url) -> None:
    from .holidays_cal import import_csv
    click.echo(f"added {import_csv(Path(path), source_url)}")


# ---- campaigns ---------------------------------------------------------------------------------
@main.group()
def campaign() -> None:
    """Campaign tags and citation packs."""


@campaign.command("sync")
def campaign_sync() -> None:
    from .watchlist import sync
    click.echo(sync(_conn(), settings().watchlist))


@campaign.command("tag")
@click.argument("campaign_id")
@click.option("--document", type=int, default=None)
@click.option("--item", type=int, default=None)
@click.option("--note", default=None)
def campaign_tag(campaign_id, document, item, note) -> None:
    from .watchlist import tag_item
    click.echo(tag_item(_conn(), campaign_id, document_id=document, item_id=item, by="kurt", note=note))


@campaign.command("pack")
@click.argument("campaign_id")
@click.option("--format", "fmt", type=click.Choice(["json", "csv", "md"]), default="md")
def campaign_pack(campaign_id, fmt) -> None:
    from .watchlist import citation_pack
    rows = citation_pack(_conn(), campaign_id)
    if fmt == "json":
        click.echo(json.dumps(rows, indent=2))
    elif fmt == "csv":
        import csv
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()) if rows else ["authority"])
        w.writeheader()
        w.writerows(rows)
    else:
        for r in rows:
            click.echo(f"- **{r['authority']}** — {r['title']} ({r['published_date']})\n  source: {r['source_url']}\n  retrieved: {r['retrieved_at']}  sha256: {r['sha256']}\n  archived: {r['archive_path']}")


# ---- annual report / adjacent ------------------------------------------------------------------
@main.group()
def annual() -> None:
    """Annual RTI statistical report."""


@annual.command("import")
@click.argument("pdf", type=click.Path(exists=True))
@click.option("--year", required=True, help="e.g. 2024-25")
@click.option("--source-url", default=None)
@click.option("--columns", default=None, help="comma-separated metric names in table column order")
def annual_import(pdf, year, source_url, columns) -> None:
    from .adapters.annual_report import import_report
    from .registry import resolve_authority
    conn = _conn()
    data = Path(pdf).read_bytes()
    cap = _archive(conn).store(data, url=source_url or f"file://{Path(pdf).name}", content_type="application/pdf", headers={}, http_status=None, kind="document")
    res = import_report(conn, data, year, source_url, cap.sha256, columns.split(",") if columns else None, resolve=lambda n: resolve_authority(conn, n))
    click.echo(json.dumps({k: v for k, v in res.items() if k != "unmatched"}))
    for u in res["unmatched"][:200]:
        click.echo("UNMATCHED " + u)


@annual.command("crosscheck")
@click.option("--year", default=None)
def annual_crosscheck(year) -> None:
    """Diff annual-report authority names against the registry: every reporting authority must resolve."""
    from .registry import resolve_authority
    conn = _conn()
    q = "SELECT DISTINCT report_year, authority_raw, authority_id FROM annual_stats" + (" WHERE report_year=?" if year else "")
    rows = conn.execute(q, (year,) if year else ()).fetchall()
    missing = []
    for r in rows:
        aid = r["authority_id"] or resolve_authority(conn, r["authority_raw"])
        if not aid:
            missing.append((r["report_year"], r["authority_raw"]))
    click.echo(f"reporting authorities: {len(rows)}; unresolved: {len(missing)}")
    for m in missing:
        click.echo(f"MISSING {m[0]}: {m[1]}")
    if not rows:
        click.echo("No annual_stats loaded. Run `rti annual import <pdf> --year ...` first (PDF not fetchable at build time).")


@main.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", type=int, default=8765)
def web(host, port) -> None:
    """Run the private web UI (FastAPI + htmx). Binds to localhost by default."""
    import uvicorn
    uvicorn.run("rti_tracker.web.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()


# ---- fixtures ----------------------------------------------------------------------------------
@main.group()
def fixtures() -> None:
    """Record live listing pages as adapter test fixtures (needs network)."""


@fixtures.command("record")
@click.argument("authority_id")
@click.option("--out", type=click.Path(), default="tests/fixtures/recorded")
def fixtures_record(authority_id, out) -> None:
    """Fetch the authority's disclosure log and save body + headers + parse result under tests/fixtures/recorded/<id>/."""
    from .adapters.base import get_adapter
    conn = _conn()
    src = conn.execute("SELECT * FROM sources WHERE authority_id=? AND kind='disclosure_log' AND enabled=1", (authority_id,)).fetchone()
    if not src:
        raise click.ClickException(f"no enabled disclosure_log source for {authority_id}")
    res = _fetcher(conn).get(src["url"], source_id=src["id"], kind="listing")
    d = Path(out) / authority_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "listing.body").write_bytes(res.body)
    (d / "meta.json").write_text(json.dumps({"url": src["url"], "final_url": res.final_url, "retrieved_at": res.retrieved_at, "status": res.status,
                                             "headers": res.headers, "sha256": res.capture.sha256 if res.capture else None, "adapter": src["adapter"],
                                             "config": json.loads(src["config"] or "{}")}, indent=1))
    cfg = json.loads(src["config"] or "{}")
    items = get_adapter(src["adapter"]).parse(res.body, res.final_url, cfg)
    (d / "expected.json").write_text(json.dumps([it.__dict__ for it in items], indent=1, default=str))
    click.echo(f"recorded {len(res.body)} bytes, parsed {len(items)} items (adapter={src['adapter']}, detected={cfg.get('detected_format')}) -> {d}")
