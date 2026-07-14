"""Daily digest: dated markdown file + terminal output.

Sections:
  1. Watchlist alerts
  2. Parliament & official publications
  3. General political news, clustered by portfolio
  4. Paywalled headlines flagged for manual follow-up
  5. Source health (silent feed rot is the enemy)
"""

import json
import os
from datetime import datetime, timedelta, timezone

from tasmon import db
from tasmon.config import Config, compile_terms

OFFICIAL_CATEGORIES = {"parliament", "government", "agency", "gbe"}


def build_digest(cfg: Config, conn, for_date: str = None) -> tuple[str, str]:
    """Return (markdown, path). Covers items fetched in the last 24h up to
    end of for_date (default: now)."""
    if for_date:
        end = datetime.fromisoformat(for_date).replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc)
        date_label = for_date
    else:
        end = datetime.now(timezone.utc)
        date_label = end.date().isoformat()
    start = end - timedelta(hours=24)

    rows = conn.execute(
        "SELECT * FROM items WHERE duplicate_of IS NULL AND fetched_at > ? "
        "AND fetched_at <= ? ORDER BY score DESC",
        (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
    ).fetchall()
    items = [dict(r) for r in rows]
    for it in items:
        it["watchlist"] = json.loads(it.get("watchlist_hits") or "[]")

    watchlist_items = [i for i in items if i["watchlist"]]
    paywalled = [i for i in items if i["paywalled"] and i not in watchlist_items]
    official = [i for i in items if i["category"] in OFFICIAL_CATEGORIES
                and not i["paywalled"] and i not in watchlist_items]
    general = [i for i in items
               if i not in watchlist_items and i not in official
               and not i["paywalled"]]

    portfolio_res = {
        name: compile_terms(terms) for name, terms in cfg.portfolios.items()
    }

    def cluster(item) -> str:
        text = (item["title"] or "") + " " + (item["fulltext"] or "")[:2000]
        for name, patterns in portfolio_res.items():
            if any(p.search(text) for p in patterns):
                return name
        return "Other & general"

    clusters: dict[str, list] = {}
    for item in general:
        clusters.setdefault(cluster(item), []).append(item)

    lines = [f"# Tasmania monitor — {date_label}", ""]
    lines.append(f"_{len(items)} new items in the last 24h "
                 f"({len(watchlist_items)} watchlist, {len(official)} official, "
                 f"{len(paywalled)} paywalled)._")
    lines.append("")

    def render(item, show_summary=True):
        bits = [f"- **[{item['title']}]({item['url']})** — {item['source_name']}"]
        when = (item["published_at"] or item["fetched_at"] or "")[:16].replace("T", " ")
        meta = [when]
        if item["watchlist"]:
            meta.append("watchlist: " + ", ".join(h["entity"] for h in item["watchlist"]))
        bits.append(f"  <br>_{' · '.join(m for m in meta if m)}_ "
                    f"(score {item['score']:.1f})")
        if show_summary and item.get("summary"):
            bits.append(f"  <br>{item['summary']}")
        return "\n".join(bits)

    lines.append("## 1. Watchlist")
    if watchlist_items:
        lines += [render(i) for i in watchlist_items]
    else:
        lines.append("_Nothing new touching the watchlist._")
    lines.append("")

    lines.append("## 2. Parliament & official publications")
    if official:
        lines += [render(i) for i in official]
    else:
        lines.append("_No new official publications detected._")
    lines.append("")

    lines.append("## 3. General political news")
    if clusters:
        # Config order first, leftovers (incl. Other) after
        order = list(cfg.portfolios.keys()) + ["Other & general"]
        for name in order:
            if name in clusters:
                lines.append(f"### {name}")
                lines += [render(i) for i in clusters.pop(name)]
                lines.append("")
        for name, cluster_items in clusters.items():
            lines.append(f"### {name}")
            lines += [render(i) for i in cluster_items]
            lines.append("")
    else:
        lines.append("_No new general items._")
        lines.append("")

    lines.append("## 4. Paywalled — flagged for manual reading")
    if paywalled:
        lines += [render(i, show_summary=False) for i in paywalled]
    else:
        lines.append("_No new paywalled headlines._")
    lines.append("")

    lines.append("## 5. Source health")
    lines += source_health_section(cfg, conn)
    lines.append("")

    markdown = "\n".join(lines)
    os.makedirs(cfg.digest_dir, exist_ok=True)
    path = os.path.join(cfg.digest_dir, f"{date_label}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return markdown, path


def source_health_section(cfg: Config, conn) -> list[str]:
    health = {h["source_id"]: h for h in db.source_health(conn)}
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.source_stale_days)
    problems, ok_count = [], 0
    for source in cfg.sources:
        h = health.get(source["id"])
        name = source.get("name", source["id"])
        if not h or not h["last_attempt"]:
            problems.append(f"- ⚠️ **{name}**: never fetched")
            continue
        last_success = h["last_success"]
        if not last_success:
            problems.append(
                f"- ⚠️ **{name}**: no successful fetch yet "
                f"(last error: {h['last_error'] or 'unknown'})")
        elif datetime.fromisoformat(last_success) < stale_cutoff:
            problems.append(
                f"- ⚠️ **{name}**: unreachable since {last_success[:10]} "
                f"(last error: {h['last_error'] or 'unknown'})")
        elif not h["last_ok"]:
            problems.append(
                f"- ⚠️ **{name}**: most recent fetch failed "
                f"({h['last_error'] or 'unknown'}); last success {last_success[:16]}")
        else:
            ok_count += 1
    lines = problems if problems else []
    lines.append(f"- ✅ {ok_count} source(s) healthy.")
    return lines
