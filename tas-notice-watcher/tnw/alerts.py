"""Alert rendering and dispatch (§2.5).

One issue per run that produced changes; separate FAILURE issues for anything
that broke. Every alerted item carries title, source, *stated* publication date,
URL, matched entities and the archive path, so that a reader can go straight
from the alert to the evidence. Nothing here summarises or characterises: the
tool surfaces and matches, analysis stays human (§8).
"""

from __future__ import annotations

from dataclasses import dataclass

from .diff import CHANGED, NEW, REMOVED, Change
from .github import IssueClient, IssueRef
from .models import FLAG_PUBLISHED_AT_MISSING
from .report import Failure, RunReport
from .watchlist import Watchlist

LABEL_ROOT = "tnw"
LABEL_FAILURE = "tnw:failure"
FINGERPRINT_PREFIX = "tnw-fingerprint:"

_KIND_HEADINGS = {NEW: "New", CHANGED: "Changed", REMOVED: "Removed"}
_MAX_ITEMS_IN_BODY = 120
# GitHub rejects issue bodies over 65,536 characters, so the rendered body is
# capped well short of that and says what it dropped.
_MAX_BODY_CHARS = 60_000


def fingerprint_marker(fingerprint: str) -> str:
    return f"<!-- {FINGERPRINT_PREFIX} {fingerprint} -->"


def _published_line(change: Change) -> str:
    if change.item is not None:
        if change.item.published_at:
            return change.item.published_at
        return "**not stated by source** (never inferred from the fetch date)"
    if change.previous is not None and change.previous.published_at:
        return change.previous.published_at
    return "**not stated by source**"


def _entity_line(change: Change, watchlist: Watchlist | None) -> str:
    entities = list(change.item.entities) if change.item else []
    if not entities:
        return "none"
    if watchlist is None:
        return ", ".join(entities)
    return ", ".join(f"{name} (T{watchlist.tier_of(name)})" for name in entities)


def render_change_item(change: Change, watchlist: Watchlist | None) -> str:
    item = change.item
    archive = (item.archive_path if item else None) or (
        change.previous.archive_path if change.previous else None
    ) or "none (item was seen in a listing only)"
    lines = [
        f"- **{change.title or '(untitled)'}**",
        f"  - id: `{change.id}`",
        f"  - source: `{change.source}`",
        f"  - stated publication date: {_published_line(change)}",
        f"  - url: {change.url or '(none)'}",
        f"  - matched entities: {_entity_line(change, watchlist)}",
        f"  - archive: `{archive}`",
    ]
    if item is not None:
        lines.append(f"  - content hash: `{item.content_hash}`")
        lines.append(f"  - fetched at: {item.fetched_at}")
        if item.source_notes:
            lines.append(f"  - parser notes: {item.source_notes}")
        if FLAG_PUBLISHED_AT_MISSING in item.flags:
            lines.append("  - flag: `published_at_missing`")
    if change.field_changes:
        lines.append(f"  - changed: {'; '.join(change.field_changes)}")
    if change.notes:
        lines.append(f"  - note: {change.notes}")
    return "\n".join(lines)


def priority_entities(report: RunReport, watchlist: Watchlist | None, tier: int = 1) -> list[str]:
    names: list[str] = []
    for change in report.all_changes:
        if change.item is None:
            continue
        for name in change.item.entities:
            if name in names:
                continue
            if watchlist is None or watchlist.tier_of(name) <= tier:
                names.append(name)
    return names


def render_change_issue(
    report: RunReport, watchlist: Watchlist | None = None
) -> tuple[str, str, list[str]]:
    changes = report.all_changes
    sources = sorted({c.source for c in changes})
    priority = priority_entities(report, watchlist)
    total = len(changes)
    headline = f"[tnw] {total} change{'s' if total != 1 else ''}"
    if priority:
        headline += " — P1: " + ", ".join(priority[:4])
        if len(priority) > 4:
            headline += f" (+{len(priority) - 4} more)"
    headline += f" [{', '.join(sources)}]"

    body: list[str] = [
        f"Run {report.started_at} → {report.finished_at} (slot: `{report.slot}`, "
        f"{report.duration_s:.1f}s).",
        "",
        "| source | new | changed | removed | items seen |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for source_report in report.sources:
        counts = source_report.change_counts
        body.append(
            f"| {source_report.source} | {counts[NEW]} | {counts[CHANGED]} | "
            f"{counts[REMOVED]} | {source_report.item_count} |"
        )
    body.append("")

    shown = 0
    for source_report in report.sources:
        source_changes = source_report.alertable_changes
        if not source_changes:
            continue
        body.append(f"## {source_report.source}")
        for kind in (NEW, CHANGED, REMOVED):
            selected = [c for c in source_changes if c.kind == kind]
            if not selected:
                continue
            body.append(f"### {_KIND_HEADINGS[kind]} ({len(selected)})")
            for change in selected:
                if shown >= _MAX_ITEMS_IN_BODY:
                    body.append(
                        f"- … {len(source_changes) - shown} further items omitted; "
                        "see the records file for the full list."
                    )
                    break
                body.append(render_change_item(change, watchlist))
                shown += 1
            body.append("")

    if report.all_failures:
        body.append("## Failures in this run")
        for failure in report.all_failures:
            body.append(f"- `{failure.source}` **{failure.kind}**: {failure.message}")
        body.append("")

    body.append("---")
    body.append(
        "Provenance: every item above is traceable to the archived artefact at the "
        "listed path (gzipped, content-addressed by sha256). Publication dates are "
        "as stated by the source; where a source states none the field is null and "
        "flagged. No text in this issue is machine-summarised."
    )

    labels = [LABEL_ROOT] + [f"{LABEL_ROOT}:source:{s}" for s in sources]
    if priority:
        labels.append(f"{LABEL_ROOT}:priority:1")

    rendered = "\n".join(body)
    if len(rendered) > _MAX_BODY_CHARS:
        rendered = (
            rendered[:_MAX_BODY_CHARS]
            + "\n\n… body truncated to fit GitHub's issue size limit. "
            "The full set of changes is in the records files for this run."
        )
    return headline[:250], rendered, labels


def render_failure_issue(failure: Failure, report: RunReport) -> tuple[str, str, list[str]]:
    title = f"[tnw] FAILURE ({failure.kind}) — {failure.source}: {failure.message}"[:250]
    body = "\n".join(
        [
            f"**Source:** `{failure.source}`",
            f"**Kind:** `{failure.kind}`",
            f"**Run:** {report.started_at} (slot `{report.slot}`)",
            "",
            f"**Message:** {failure.message}",
            "",
            "```",
            failure.detail.strip()[:6000] or "(no further detail)",
            "```",
            "",
            "Absence of alerts is not evidence of absence of events: this issue "
            "exists so a silent scraper failure cannot be mistaken for a quiet week. "
            "Close it once the source has been re-checked by hand.",
            "",
            fingerprint_marker(failure.fingerprint),
        ]
    )
    labels = [LABEL_ROOT, LABEL_FAILURE, f"{LABEL_ROOT}:source:{failure.source}"]
    return title, body, labels


@dataclass
class DispatchResult:
    change_issue: IssueRef | None = None
    failure_issues: list[IssueRef] = None  # type: ignore[assignment]
    failure_comments: list[int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.failure_issues = self.failure_issues or []
        self.failure_comments = self.failure_comments or []


def dispatch(
    report: RunReport,
    client: IssueClient,
    *,
    watchlist: Watchlist | None = None,
    create_labels: bool = True,
) -> DispatchResult:
    """Post the run's alerts. A recurring failure comments on its open issue."""
    result = DispatchResult()

    if report.all_changes:
        title, body, labels = render_change_issue(report, watchlist)
        if create_labels:
            client.ensure_labels(labels)
        result.change_issue = client.create_issue(title, body, labels)

    for failure in report.all_failures:
        title, body, labels = render_failure_issue(failure, report)
        existing = client.find_open_issue(LABEL_FAILURE, failure.fingerprint)
        if existing is not None:
            client.comment(
                existing.number,
                f"Still failing as at {report.started_at} (slot `{report.slot}`): "
                f"{failure.message}\n\n```\n{failure.detail.strip()[:2000]}\n```",
            )
            result.failure_comments.append(existing.number)
            continue
        if create_labels:
            client.ensure_labels(labels)
        result.failure_issues.append(client.create_issue(title, body, labels))

    return result
