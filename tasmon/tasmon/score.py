"""Ranking: watchlist match x source tier x recency x political salience."""

import re
from datetime import datetime, timezone

from tasmon.config import Config, compile_terms


class Scorer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        # watchlist: list of {entity, weight, patterns}
        self.watchlist = []
        for entry in cfg.watchlist:
            terms = [entry["entity"]] + entry.get("aliases", [])
            self.watchlist.append({
                "entity": entry["entity"],
                "weight": float(entry.get("weight", 3.0)),
                "patterns": compile_terms(terms),
            })
        self.salience = [
            (term, float(weight), compile_terms([term])[0])
            for term, weight in cfg.salience_terms.items()
        ]

    def match_watchlist(self, text: str) -> list[dict]:
        hits = []
        for entry in self.watchlist:
            if any(p.search(text) for p in entry["patterns"]):
                hits.append({"entity": entry["entity"], "weight": entry["weight"]})
        return hits

    def match_salience(self, text: str) -> list[dict]:
        hits = []
        for term, weight, pattern in self.salience:
            if pattern.search(text):
                hits.append({"term": term, "weight": weight})
        return hits

    def recency_factor(self, published_at: str | None, now: datetime = None) -> float:
        now = now or datetime.now(timezone.utc)
        if not published_at:
            return 1.0
        try:
            dt = datetime.fromisoformat(published_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return 1.0
        age_hours = max(0.0, (now - dt).total_seconds() / 3600)
        return 0.5 ** (age_hours / self.cfg.recency_half_life_hours)

    def score(self, title: str, text: str | None, tier: int,
              published_at: str | None) -> tuple[float, list, list]:
        haystack = title + "\n" + (text or "")
        wl = self.match_watchlist(haystack)
        sal = self.match_salience(haystack)
        tier_w = self.cfg.tier_weights.get(tier, 0.5)
        wl_sum = sum(h["weight"] for h in wl)
        sal_sum = sum(h["weight"] for h in sal)
        score = tier_w * self.recency_factor(published_at) * (1 + wl_sum) * (1 + sal_sum)
        return score, wl, sal


_WORD_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "the", "a", "an", "to", "of", "in", "on", "for", "and", "as", "at", "by",
    "with", "over", "after", "amid", "says", "say", "new", "tas", "tasmania",
    "tasmanian", "hobart",
}


def title_tokens(title: str) -> set:
    return {w for w in _WORD_RE.findall(title.lower()) if w not in STOPWORDS}


def title_similarity(a: str, b: str) -> float:
    """Jaccard similarity of title token sets — catches wire-copy republishes."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_near_duplicate(conn, title: str, threshold: float, days: int = 3):
    """Return the id of an existing recent item with a near-identical title."""
    rows = conn.execute(
        "SELECT id, title FROM items WHERE duplicate_of IS NULL AND title IS NOT NULL "
        "AND fetched_at >= datetime('now', ?)", (f"-{days} days",)).fetchall()
    for row in rows:
        if title_similarity(title, row["title"]) >= threshold:
            return row["id"]
    return None
