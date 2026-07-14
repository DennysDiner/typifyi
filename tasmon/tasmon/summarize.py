"""Optional Anthropic API pass: 2-3 sentence relevance notes for high-ranking
Tier 1 items. Off by default; daily item cap for cost control."""

from datetime import datetime, timezone

from tasmon.config import Config
from tasmon.ingest import now_iso


def summarize_new_items(cfg: Config, conn) -> int:
    sconf = cfg.summarization
    if not sconf.get("enabled"):
        return 0
    try:
        import anthropic
    except ImportError:
        print("!! summarization enabled but `anthropic` package not installed "
              "(pip install anthropic)")
        return 0

    cap = int(sconf.get("daily_cap", 15))
    today = datetime.now(timezone.utc).date().isoformat()
    used = conn.execute(
        "SELECT COUNT(*) FROM items WHERE summarized_at LIKE ?",
        (today + "%",)).fetchone()[0]
    budget = max(0, cap - used)
    if budget == 0:
        return 0

    rows = conn.execute(
        "SELECT id, title, fulltext FROM items WHERE tier = 1 AND summary IS NULL "
        "AND duplicate_of IS NULL AND fulltext IS NOT NULL "
        "AND length(fulltext) > 400 AND fetched_at >= datetime('now', '-1 day') "
        "ORDER BY score DESC LIMIT ?", (budget,)).fetchall()
    if not rows:
        return 0

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    model = sconf.get("model", "claude-haiku-4-5")
    context = sconf.get(
        "context",
        "The reader is a Tasmanian policy analyst briefing Legislative Council "
        "crossbench members.")
    done = 0
    for row in rows:
        prompt = (
            f"{context}\n\nIn 2-3 sentences, state what this article reports and "
            f"why (or whether) it matters for that briefing context. Be concrete; "
            f"no preamble.\n\nTITLE: {row['title']}\n\n"
            f"ARTICLE:\n{row['fulltext'][:6000]}")
        try:
            resp = client.messages.create(
                model=model, max_tokens=300,
                messages=[{"role": "user", "content": prompt}])
            if resp.stop_reason == "refusal" or not resp.content:
                continue
            text = next((b.text for b in resp.content if b.type == "text"), "").strip()
            if text:
                conn.execute(
                    "UPDATE items SET summary = ?, summarized_at = ? WHERE id = ?",
                    (text, now_iso(), row["id"]))
                conn.commit()
                done += 1
        except Exception as e:  # noqa: BLE001 — a dead API must not kill the run
            print(f"!! summarization failed for item {row['id']}: {e}")
            break
    return done
