"""Run summaries for the Actions job summary and the console (§5)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .diff import CHANGED, NEW, REMOVED
from .heartbeat import SourceHealth
from .report import RunReport

_STATUS_ICON = {"ok": "🟢", "failed": "🔴", "skipped": "⚪", "stale": "🟠", "never_run": "⚪"}


def render_summary(report: RunReport, healths: Iterable[SourceHealth] = ()) -> str:
    lines = [
        "# tas-notice-watcher run",
        "",
        f"- slot: `{report.slot}`",
        f"- started: `{report.started_at}`  finished: `{report.finished_at}`  "
        f"({report.duration_s:.1f}s)",
        f"- changes: **{len(report.all_changes)}**   failures: **{len(report.all_failures)}**"
        + ("   (dry run)" if report.dry_run else ""),
        "",
        "| source | status | items | new | changed | removed | records | requests | bytes | endpoint |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for source in report.sources:
        counts = source.change_counts
        icon = _STATUS_ICON.get(source.status, "❔")
        lines.append(
            f"| {source.source} | {icon} {source.status} | {source.item_count} | "
            f"{counts[NEW]} | {counts[CHANGED]} | {counts[REMOVED]} | "
            f"{source.records_written} | {source.requests} | {source.page_bytes} | "
            f"{source.endpoint or '—'} |"
        )

    healths = list(healths)
    if healths:
        lines += [
            "",
            "## Heartbeat",
            "",
            "| source | status | last success | age (h) | expected every (h) | last items |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        ]
        for health in healths:
            icon = _STATUS_ICON.get(health.status, "❔")
            age = "—" if health.hours_since_success is None else f"{health.hours_since_success:.1f}"
            lines.append(
                f"| {health.source} | {icon} {health.status} | {health.last_success_at or '—'} | "
                f"{age} | {health.expected_interval_hours:.0f} | {health.last_item_count} |"
            )

    warnings = [(s.source, w) for s in report.sources for w in s.warnings]
    if warnings:
        lines += ["", "## Warnings", ""]
        lines += [f"- `{source}`: {warning}" for source, warning in warnings]

    if report.all_failures:
        lines += ["", "## Failures", ""]
        for failure in report.all_failures:
            lines.append(f"- `{failure.source}` **{failure.kind}**: {failure.message}")

    notes = [(s.source, n) for s in report.sources for n in s.notes]
    if notes:
        lines += ["", "## Notes", ""]
        lines += [f"- `{source}`: {note}" for source, note in notes]

    return "\n".join(lines) + "\n"


def write_job_summary(text: str) -> Path | None:
    """Append to the GitHub Actions job summary when running in CI."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return None
    path = Path(target)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
    return path
