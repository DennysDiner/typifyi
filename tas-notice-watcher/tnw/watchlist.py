"""Watchlist loading, matching and near-miss logging (§4).

Matching is deterministic: literal patterns are compiled to word-boundary
anchored, case-insensitive regexes with flexible internal whitespace, and
explicit regexes are used as written. Near misses — candidates that score close
to a pattern but do not match it — are logged to a low-priority review list
rather than discarded, because corporate entities rename themselves and trade
through special-purpose vehicles.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

DEFAULT_NEAR_MISS_THRESHOLD = 0.86
MAX_TEXT_CHARS_FOR_NEAR_MISS = 400_000
MAX_WINDOW_EVALUATIONS = 60_000

_WORD_RE = re.compile(r"[A-Za-z0-9&'’\-\.]+")


class WatchlistError(ValueError):
    """Raised when watchlist.yml is malformed."""


@dataclass(frozen=True)
class Pattern:
    raw: str
    regex: re.Pattern[str]
    kind: str  # "literal" or "regex"


@dataclass
class Entity:
    name: str
    tier: int
    patterns: list[Pattern] = field(default_factory=list)
    notes: str = ""

    @property
    def literals(self) -> list[str]:
        return [p.raw for p in self.patterns if p.kind == "literal"]


@dataclass(frozen=True)
class Match:
    entity: str
    tier: int
    pattern: str
    matched_text: str
    where: str  # "title" or "body"
    offset: int


@dataclass(frozen=True)
class NearMiss:
    entity: str
    tier: int
    pattern: str
    candidate: str
    ratio: float
    context: str


def literal_to_regex(literal: str) -> re.Pattern[str]:
    """Compile a literal pattern with word-boundary anchoring.

    Internal whitespace matches any run of whitespace (including a line break,
    which PDF extraction inserts mid-name). Leading/trailing boundaries use
    lookarounds so that patterns starting or ending with punctuation still work.
    """
    tokens = [re.escape(token) for token in literal.split()]
    if not tokens:
        raise WatchlistError("empty pattern")
    core = r"\s+".join(tokens)
    prefix = r"(?<![\w])" if re.match(r"\w", literal[0]) else ""
    suffix = r"(?![\w])" if re.search(r"\w$", literal) else ""
    return re.compile(prefix + core + suffix, re.IGNORECASE)


def _coerce_patterns(entity_name: str, raw: dict[str, Any]) -> list[Pattern]:
    patterns: list[Pattern] = []
    for literal in raw.get("patterns") or []:
        if not isinstance(literal, str) or not literal.strip():
            raise WatchlistError(f"{entity_name}: patterns must be non-empty strings")
        patterns.append(Pattern(raw=literal, regex=literal_to_regex(literal.strip()), kind="literal"))
    for expression in raw.get("regexes") or []:
        if not isinstance(expression, str) or not expression.strip():
            raise WatchlistError(f"{entity_name}: regexes must be non-empty strings")
        try:
            compiled = re.compile(expression, re.IGNORECASE)
        except re.error as exc:
            raise WatchlistError(f"{entity_name}: invalid regex {expression!r}: {exc}") from exc
        patterns.append(Pattern(raw=expression, regex=compiled, kind="regex"))
    if not patterns:
        raise WatchlistError(f"{entity_name}: needs at least one pattern or regex")
    return patterns


class Watchlist:
    def __init__(self, entities: Sequence[Entity], *, near_miss_threshold: float = DEFAULT_NEAR_MISS_THRESHOLD) -> None:
        self.entities = list(entities)
        self.near_miss_threshold = near_miss_threshold

    # -- loading ------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Watchlist":
        if not isinstance(data, dict):
            raise WatchlistError("watchlist must be a mapping")
        raw_entities = data.get("entities")
        if not isinstance(raw_entities, list) or not raw_entities:
            raise WatchlistError("watchlist needs a non-empty 'entities' list")
        settings = data.get("settings") or {}
        threshold = float(settings.get("near_miss_threshold", DEFAULT_NEAR_MISS_THRESHOLD))
        if not 0.5 <= threshold < 1.0:
            raise WatchlistError("near_miss_threshold must be >= 0.5 and < 1.0")

        entities: list[Entity] = []
        seen: set[str] = set()
        for raw in raw_entities:
            if not isinstance(raw, dict):
                raise WatchlistError("each entity must be a mapping")
            name = str(raw.get("name", "")).strip()
            if not name:
                raise WatchlistError("entity is missing 'name'")
            if name.lower() in seen:
                raise WatchlistError(f"duplicate entity name: {name}")
            seen.add(name.lower())
            try:
                tier = int(raw.get("tier", 3))
            except (TypeError, ValueError) as exc:
                raise WatchlistError(f"{name}: tier must be an integer") from exc
            if tier not in (1, 2, 3):
                raise WatchlistError(f"{name}: tier must be 1, 2 or 3")
            entities.append(
                Entity(name=name, tier=tier, patterns=_coerce_patterns(name, raw),
                       notes=str(raw.get("notes", "")))
            )
        return cls(entities, near_miss_threshold=threshold)

    @classmethod
    def load(cls, path: Path | str) -> "Watchlist":
        path = Path(path)
        if not path.exists():
            raise WatchlistError(f"watchlist not found: {path}")
        return cls.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    # -- matching -----------------------------------------------------------

    def match_text(self, text: str, *, where: str = "body") -> list[Match]:
        matches: list[Match] = []
        if not text:
            return matches
        for entity in self.entities:
            for pattern in entity.patterns:
                found = pattern.regex.search(text)
                if found:
                    matches.append(
                        Match(
                            entity=entity.name,
                            tier=entity.tier,
                            pattern=pattern.raw,
                            matched_text=found.group(0).strip(),
                            where=where,
                            offset=found.start(),
                        )
                    )
                    break  # one match per entity per field is enough
        return matches

    def match_item(self, title: str, body_text: str) -> list[Match]:
        matches = self.match_text(title or "", where="title")
        already = {m.entity for m in matches}
        matches.extend(
            m for m in self.match_text(body_text or "", where="body") if m.entity not in already
        )
        matches.sort(key=lambda m: (m.tier, m.entity))
        return matches

    def entity_names(self, matches: Iterable[Match]) -> list[str]:
        seen: list[str] = []
        for match in matches:
            if match.entity not in seen:
                seen.append(match.entity)
        return seen

    def tier_of(self, name: str) -> int:
        for entity in self.entities:
            if entity.name == name:
                return entity.tier
        return 3

    # -- near misses --------------------------------------------------------

    def near_misses(self, text: str, *, exclude: Iterable[str] = ()) -> list[NearMiss]:
        """Find candidates that *nearly* match a literal pattern.

        Deliberately cheap: a prefix pre-filter picks candidate windows, and only
        those are scored with difflib. Anything at or above the threshold — but
        not an exact match — is a near miss.
        """
        if not text:
            return []
        excluded = {name.lower() for name in exclude}
        haystack = text[:MAX_TEXT_CHARS_FOR_NEAR_MISS]
        tokens = [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(haystack)]
        if not tokens:
            return []

        results: dict[tuple[str, str], NearMiss] = {}
        evaluations = 0
        for entity in self.entities:
            if entity.name.lower() in excluded:
                continue
            for pattern in entity.patterns:
                if pattern.kind != "literal":
                    continue
                target = pattern.raw.lower()
                target_words = target.split()
                width = len(target_words)
                if len(target) < 5:
                    continue  # too short to score meaningfully
                head = target_words[0][:2]
                for index in range(0, max(0, len(tokens) - width + 1)):
                    if tokens[index][0][:2].lower() != head:
                        continue
                    if evaluations >= MAX_WINDOW_EVALUATIONS:
                        return sorted(results.values(), key=lambda n: -n.ratio)
                    evaluations += 1
                    window = tokens[index : index + width]
                    candidate_text = haystack[window[0][1] : window[-1][2]]
                    candidate = " ".join(candidate_text.split()).lower()
                    if candidate == target:
                        continue  # exact match: reported by match_text, not here
                    ratio = difflib.SequenceMatcher(None, candidate, target).ratio()
                    if ratio < self.near_miss_threshold:
                        continue
                    key = (entity.name, candidate)
                    if key in results and results[key].ratio >= ratio:
                        continue
                    start = max(0, window[0][1] - 60)
                    end = min(len(haystack), window[-1][2] + 60)
                    results[key] = NearMiss(
                        entity=entity.name,
                        tier=entity.tier,
                        pattern=pattern.raw,
                        candidate=candidate_text.strip(),
                        ratio=round(ratio, 4),
                        context=" ".join(haystack[start:end].split()),
                    )
        return sorted(results.values(), key=lambda n: (-n.ratio, n.entity))
