"""Private web UI: FastAPI + Jinja2 + htmx. Binds to localhost; HTTP basic auth when RTI_WEB_USER/PASSWORD
are set. Datasette (see datasette_metadata.yaml) provides faceted search over the same DB.

NOTHING here is deployed publicly without Kurt's sign-off (brief §4)."""
from __future__ import annotations

import html
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from .. import db as dbm
from ..archive import Archive
from ..config import settings
from ..health import health_rows, summary

app = FastAPI(title="Tas RTI tracker (private)")
# Host header pinning defeats DNS-rebinding reads of the private pages (audit #56). Extend via RTI_WEB_HOSTS.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", *[h for h in os.environ.get("RTI_WEB_HOSTS", "").split(",") if h]])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic(auto_error=False)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if not request.url.path.startswith("/archive/"):
        resp.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'")
    return resp


def auth(creds: HTTPBasicCredentials | None = Depends(security)) -> None:  # noqa: B008
    """Fail closed: if a user is configured, a password must be configured too and both must match.
    With no user configured the app relies on binding to localhost only (README)."""
    st = settings()
    if not st.web_auth_user:
        return
    if not st.web_auth_password:
        raise HTTPException(status_code=503, detail="RTI_WEB_USER is set but RTI_WEB_PASSWORD is empty; refusing to serve")
    ok = creds is not None and secrets.compare_digest(creds.username, st.web_auth_user) and secrets.compare_digest(creds.password, st.web_auth_password)
    if not ok:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})


def same_origin(request: Request) -> None:
    """CSRF guard for state-changing POSTs: Origin/Referer must match the request host (audit #56)."""
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        raise HTTPException(status_code=403, detail="missing Origin/Referer")
    if urlsplit(origin).netloc.lower() != (request.headers.get("host") or "").lower():
        raise HTTPException(status_code=403, detail="cross-origin POST rejected")


def conn():
    c = dbm.connect(settings().db_path)
    dbm.migrate(c)
    return c


def render(request: Request, name: str, **ctx):
    ctx.setdefault("hx", request.headers.get("HX-Request") == "true")
    return templates.TemplateResponse(request, name, ctx)


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
def feed(request: Request, authority: str = "", type_: str = "", portfolio: str = "", since: str = "", exemption: str = "", q: str = "", page: int = 1):
    c = conn()
    where, args = ["i.status='active'"], []
    if authority:
        where.append("i.authority_id=?"); args.append(authority)
    if type_:
        where.append("a.type=?"); args.append(type_)
    if portfolio:
        where.append("a.portfolio_minister LIKE ?"); args.append(f"%{portfolio}%")
    if since:
        where.append("COALESCE(i.published_date, substr(i.first_seen_at,1,10)) >= ?"); args.append(since)
    if exemption:
        where.append("EXISTS (SELECT 1 FROM documents d JOIN document_metadata m ON m.document_id=d.id WHERE d.item_id=i.id AND m.field='exemptions_cited' AND m.value LIKE ?)"); args.append(f"%{exemption}%")
    if q:
        where.append("(i.title LIKE ? OR i.fields LIKE ?)"); args += [f"%{q}%", f"%{q}%"]
    rows = c.execute(
        f"SELECT i.*, a.name AS authority_name, a.type AS atype, a.portfolio_minister, (SELECT count(*) FROM documents d WHERE d.item_id=i.id) AS ndocs"
        f" FROM items i LEFT JOIN authorities a ON a.id=i.authority_id WHERE {' AND '.join(where)} ORDER BY i.first_seen_at DESC LIMIT 50 OFFSET ?",
        (*args, (page - 1) * 50)).fetchall()
    auths = c.execute("SELECT id, name FROM authorities WHERE active=1 ORDER BY name").fetchall()
    return render(request, "feed.html", rows=rows, auths=auths, page=page, filters={"authority": authority, "type_": type_, "portfolio": portfolio, "since": since, "exemption": exemption, "q": q})


@app.get("/authorities", response_class=HTMLResponse, dependencies=[Depends(auth)])
def authorities(request: Request):
    rows = health_rows(conn())
    return render(request, "authorities.html", rows=rows, summary=summary(rows))


@app.get("/authority/{aid}", response_class=HTMLResponse, dependencies=[Depends(auth)])
def authority(request: Request, aid: str):
    c = conn()
    a = c.execute("SELECT * FROM authorities WHERE id=?", (aid,)).fetchone()
    if not a:
        raise HTTPException(404)
    items = c.execute("SELECT * FROM items WHERE authority_id=? ORDER BY COALESCE(published_date, first_seen_at) DESC LIMIT 200", (aid,)).fetchall()
    sources = c.execute("SELECT * FROM sources WHERE authority_id=?", (aid,)).fetchall()
    stats = c.execute("SELECT report_year, metric, value FROM annual_stats WHERE authority_id=? ORDER BY report_year", (aid,)).fetchall()
    series: dict[str, dict[str, float]] = {}
    for s in stats:
        series.setdefault(s["metric"], {})[s["report_year"]] = s["value"]
    years = sorted({s["report_year"] for s in stats})
    refusal = {y: (series.get("refused", {}).get(y, 0) / series["applications_decided"][y] if series.get("applications_decided", {}).get(y) else None) for y in years}
    timeliness = {y: (series.get("decided_within_20wd", {}).get(y, 0) / series["applications_decided"][y] if series.get("applications_decided", {}).get(y) else None) for y in years}
    names = c.execute("SELECT * FROM authority_names WHERE authority_id=?", (aid,)).fetchall()
    changes = c.execute("SELECT * FROM changes WHERE authority_id=? ORDER BY id DESC LIMIT 50", (aid,)).fetchall()
    raw = json.loads(a["raw"] or "{}")
    return render(request, "authority.html", a=a, raw=raw, items=items, sources=sources, series=series, years=years, refusal=refusal, timeliness=timeliness, names=names, changes=changes)


@app.get("/item/{item_id}", response_class=HTMLResponse, dependencies=[Depends(auth)])
def item(request: Request, item_id: int):
    c = conn()
    it = c.execute("SELECT i.*, a.name AS authority_name FROM items i LEFT JOIN authorities a ON a.id=i.authority_id WHERE i.id=?", (item_id,)).fetchone()
    if not it:
        raise HTTPException(404)
    docs = c.execute("SELECT d.*, c.retrieved_at, c.http_status, c.final_url, c.headers, c.chain_hash, b.path FROM documents d JOIN captures c ON c.id=d.capture_id JOIN blobs b ON b.sha256=d.sha256 WHERE d.item_id=? ORDER BY d.id", (item_id,)).fetchall()
    listing_caps = c.execute("SELECT c.id, c.url, c.final_url, c.retrieved_at, c.sha256, c.http_status FROM captures c WHERE c.id IN (SELECT last_capture_id FROM items WHERE id=?) OR c.id IN (SELECT json_extract(detail,'$.listing_capture_id') FROM changes WHERE item_id=? AND kind='new_item')", (item_id, item_id)).fetchall()
    meta = {d["id"]: c.execute("SELECT * FROM document_metadata WHERE document_id=?", (d["id"],)).fetchall() for d in docs}
    versions = c.execute("SELECT * FROM item_versions WHERE item_id=? ORDER BY id", (item_id,)).fetchall()
    tags = c.execute("SELECT ct.*, cp.name FROM campaign_tags ct JOIN campaigns cp ON cp.id=ct.campaign_id WHERE ct.item_id=? OR ct.document_id IN (SELECT id FROM documents WHERE item_id=?)", (item_id, item_id)).fetchall()
    campaigns = c.execute("SELECT id, name FROM campaigns ORDER BY name").fetchall()
    removal = c.execute("SELECT detail FROM changes WHERE item_id=? AND kind='item_removed' ORDER BY id DESC LIMIT 1", (item_id,)).fetchone()
    return render(request, "item.html", it=it, docs=docs, meta=meta, versions=versions, tags=tags, campaigns=campaigns, fields=json.loads(it["fields"] or "{}"),
                  listing_caps=listing_caps, removal=json.loads(removal["detail"]) if removal else None)


@app.post("/item/{item_id}/tag", dependencies=[Depends(auth), Depends(same_origin)])
def tag(item_id: int, campaign_id: str = Form(...), note: str = Form("")):
    from ..watchlist import tag_item
    tag_item(conn(), campaign_id, item_id=item_id, by="kurt", note=note or None)
    return RedirectResponse(f"/item/{item_id}", status_code=303)


@app.get("/archive/{sha}", dependencies=[Depends(auth)])
def archive_file(sha: str):
    c = conn()
    a = Archive(c, settings().archive_dir)
    try:
        p = a.open_path(sha)
    except FileNotFoundError:
        raise HTTPException(404)
    # Never render captured third-party HTML in this origin: download only, sandboxed, no sniffing (audit #55).
    return FileResponse(p, filename=p.name, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{p.name}"', "Content-Security-Policy": "sandbox",
                                 "X-Content-Type-Options": "nosniff"})


@app.get("/private/{app_id}/{sha}", dependencies=[Depends(auth)])
def private_attachment(app_id: int, sha: str):
    c = conn()
    r = c.execute("SELECT path, filename FROM application_attachments WHERE application_id=? AND sha256=?", (app_id, sha)).fetchone()
    if not r or not r["path"] or not Path(r["path"]).exists():
        raise HTTPException(404)
    return FileResponse(r["path"], filename=r["filename"], media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{r["filename"]}"', "Content-Security-Policy": "sandbox"})


@app.get("/search", response_class=HTMLResponse, dependencies=[Depends(auth)])
def search(request: Request, q: str = ""):
    c = conn()
    rows = []
    if q:
        raw = c.execute(
            "SELECT d.id AS document_id, d.item_id, d.url, d.sha256, i.title, a.name AS authority_name, snippet(document_fts, 0, '\x01', '\x02', ' … ', 24) AS snip"
            " FROM document_fts f JOIN documents d ON d.id=f.rowid LEFT JOIN items i ON i.id=d.item_id LEFT JOIN authorities a ON a.id=d.authority_id"
            " WHERE document_fts MATCH ? ORDER BY rank LIMIT 100", (q,)).fetchall()
        # escape document text (untrusted third-party content), then restore the highlight markers only
        rows = [dict(r, snip=html.escape(r["snip"] or "").replace("\x01", "<mark>").replace("\x02", "</mark>")) for r in raw]
    return render(request, "search.html", q=q, rows=rows)


@app.get("/applications", response_class=HTMLResponse, dependencies=[Depends(auth)])
def applications(request: Request):
    from ..applications import status_for
    from ..deadlines import DeadlineEngine
    c = conn()
    eng = DeadlineEngine()
    apps = []
    for a in c.execute("SELECT * FROM applications ORDER BY lodged_date DESC"):
        st = status_for(c, int(a["id"]), eng)
        upcoming = [d for d in st.deadlines if not d.passed and "ALTERNATIVE" not in d.label]
        nxt = min(upcoming, key=lambda d: d.due) if upcoming else None
        days = eng.cal.working_days_between(eng.today, nxt.due) if nxt else None
        links = c.execute("SELECT l.*, i.title FROM application_links l JOIN items i ON i.id=l.item_id WHERE l.application_id=?", (a["id"],)).fetchall()
        apps.append({"a": a, "st": st, "next": nxt, "days": days, "links": links})
    return render(request, "applications.html", apps=apps, today=eng.today)


@app.get("/applications/{app_id}", response_class=HTMLResponse, dependencies=[Depends(auth)])
def application(request: Request, app_id: int):
    from ..applications import status_for
    from ..deadlines import ALL_EVENTS, DeadlineEngine
    c = conn()
    a = c.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    if not a:
        raise HTTPException(404)
    eng = DeadlineEngine()
    st = status_for(c, app_id, eng)
    events = c.execute("SELECT * FROM application_events WHERE application_id=? ORDER BY event_date, id", (app_id,)).fetchall()
    atts = c.execute("SELECT * FROM application_attachments WHERE application_id=?", (app_id,)).fetchall()
    links = c.execute("SELECT l.*, i.title, i.url FROM application_links l JOIN items i ON i.id=l.item_id WHERE l.application_id=?", (app_id,)).fetchall()
    return render(request, "application.html", a=a, st=st, events=events, atts=atts, links=links, all_events=ALL_EVENTS, today=eng.today)


@app.post("/applications/{app_id}/event", dependencies=[Depends(auth), Depends(same_origin)])
def application_event(app_id: int, event: str = Form(...), when: str = Form(...), detail: str = Form("{}")):
    from datetime import date

    from ..applications import add_event
    add_event(conn(), app_id, event, date.fromisoformat(when), json.loads(detail or "{}"))
    return RedirectResponse(f"/applications/{app_id}", status_code=303)


@app.get("/changes", response_class=HTMLResponse, dependencies=[Depends(auth)])
def changes(request: Request, kind: str = ""):
    c = conn()
    rows = c.execute("SELECT ch.*, a.name AS authority_name FROM changes ch LEFT JOIN authorities a ON a.id=ch.authority_id" + (" WHERE ch.kind=?" if kind else "") + " ORDER BY ch.id DESC LIMIT 300", (kind,) if kind else ()).fetchall()
    kinds = [r[0] for r in c.execute("SELECT DISTINCT kind FROM changes ORDER BY kind")]
    return render(request, "changes.html", rows=[dict(r, detail_obj=json.loads(r["detail"] or "{}")) for r in rows], kinds=kinds, kind=kind)


@app.get("/campaigns", response_class=HTMLResponse, dependencies=[Depends(auth)])
def campaigns(request: Request):
    c = conn()
    rows = c.execute("SELECT cp.*, (SELECT count(*) FROM campaign_tags t WHERE t.campaign_id=cp.id) AS n FROM campaigns cp ORDER BY name").fetchall()
    return render(request, "campaigns.html", rows=rows)


@app.get("/campaigns/{cid}/pack.{fmt}", dependencies=[Depends(auth)])
def pack(cid: str, fmt: str, request: Request):
    from ..watchlist import citation_pack
    rows = citation_pack(conn(), cid, base_url=str(request.base_url).rstrip("/"))
    if fmt == "json":
        return PlainTextResponse(json.dumps(rows, indent=2), media_type="application/json")
    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["authority"])
        w.writeheader(); w.writerows(rows)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")
    md = "\n".join(f"- **{r['authority']}** — {r['title']} ({r['published_date']})\n  source: {r['source_url']}\n  retrieved: {r['retrieved_at']}  sha256: {r['sha256']}\n  archived copy: {r['archived_copy']}" for r in rows)
    return PlainTextResponse(md or "(no tagged documents)", media_type="text/markdown")


@app.get("/health.json", dependencies=[Depends(auth)])
def health_json():
    rows = health_rows(conn())
    return {"summary": summary(rows), "rows": rows}
