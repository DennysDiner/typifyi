"""The pipeline (§2.3).

    fetch → archive raw → normalise → extract items → hash → diff vs state
          → match watchlist → alert → commit state

Each source is isolated: one adapter blowing up records a failure and the run
continues, because a broken tenders parser must not hide a new gazette. Every
failure path ends in an alert; nothing here can fail quietly.
"""

from __future__ import annotations

import logging
import time
import traceback
from typing import Iterable, Sequence

from adapters import Adapter, all_adapters
from adapters.base import AdapterContext, AdapterError, AdapterParseError

from .archive import ArchiveWriter
from .diff import CHANGED, NEW, REMOVED, Change, diff_items
from .fetcher import Fetcher, RobotsDisallowed, StructuralFetchError, TransientFetchError
from .github import IssueClient
from .heartbeat import Expectation, canary_failure, drift_warning, evaluate_health, health_failures, write_heartbeat
from .models import NOTE_BODY_PENDING, Item, validate_record
from .records import NearMissWriter, append_items
from .report import FETCH, INTERNAL, PARSE, ROBOTS, SCHEMA, Failure, RunReport, SourceReport
from .schedule import decide, load_runs, manual_slot, record_run, save_runs
from .state import ItemState, SourceState, load_state, save_state
from .timeutil import utcnow_iso
from .watchlist import Watchlist

LOG = logging.getLogger("tnw.runner")


def _failure_for(source: str, exc: BaseException) -> Failure:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:]
    if isinstance(exc, StructuralFetchError):
        return Failure(source, FETCH, f"structural fetch failure: {exc}", detail)
    if isinstance(exc, RobotsDisallowed):
        return Failure(source, ROBOTS, f"robots.txt blocked the fetch: {exc}", detail)
    if isinstance(exc, TransientFetchError):
        return Failure(source, FETCH, f"fetch failed after retries: {exc}", detail)
    if isinstance(exc, AdapterParseError):
        return Failure(source, PARSE, f"parse failure: {exc}", detail)
    if isinstance(exc, AdapterError):
        return Failure(source, PARSE, str(exc), detail)
    return Failure(source, INTERNAL, f"unhandled {type(exc).__name__}: {exc}", detail)


class Runner:
    def __init__(
        self,
        config,
        *,
        adapters: Sequence[Adapter] | None = None,
        fetcher: Fetcher | None = None,
        archive: ArchiveWriter | None = None,
        watchlist: Watchlist | None = None,
        issue_client: IssueClient | None = None,
        clock=time.monotonic,
    ) -> None:
        self.config = config
        self.adapters = list(adapters) if adapters is not None else all_adapters()
        self.fetcher = fetcher or config.fetcher()
        self.archive = archive or config.archive_writer()
        self.watchlist = watchlist if watchlist is not None else Watchlist.load(config.watchlist_file)
        self.issue_client = issue_client
        self._clock = clock

    # -- public API ---------------------------------------------------------

    def run(
        self,
        *,
        sources: Iterable[str] | None = None,
        force: bool = False,
        respect_schedule: bool = True,
        dry_run: bool = False,
        now: str | None = None,
    ) -> tuple[RunReport, str]:
        now = now or utcnow_iso()
        runs = load_runs(self.config.runs_file)
        if respect_schedule:
            should_run, slot, reason = decide(runs, now_iso=now, force=force)
        else:
            should_run, slot, reason = True, manual_slot(now), "schedule check skipped"

        report = RunReport(started_at=now, slot=slot.key, dry_run=dry_run)
        if not should_run:
            report.finished_at = utcnow_iso()
            return report, reason

        started = self._clock()
        selected = self._select(sources)
        for adapter in selected:
            report.sources.append(self._run_source(adapter, now=now, dry_run=dry_run))

        # Heartbeat runs over *all* adapters, not just the selected ones: a
        # source that was skipped is exactly the one most likely to go stale.
        states = {
            adapter.name: load_state(self.config.state_path, adapter.name)
            for adapter in self.adapters
        }
        expectations: dict[str, Expectation] = {a.name: a.expectation for a in self.adapters}
        healths = evaluate_health(states, expectations, now=now)
        # A source that already failed in this run has an alert of its own; a
        # second "stale" issue for it would be noise, not information.
        failed_now = {s.source for s in report.sources if s.failures}
        report.global_failures.extend(
            failure for failure in health_failures(healths) if failure.source not in failed_now
        )

        report.finished_at = utcnow_iso()
        report.duration_s = self._clock() - started
        if not dry_run:
            write_heartbeat(self.config.heartbeat_file, report, healths)

        if not dry_run and self.issue_client is not None:
            from .alerts import dispatch

            dispatch(report, self.issue_client, watchlist=self.watchlist,
                     create_labels=self.config.labels_enabled)

        if not dry_run:
            status = "completed" if report.ok else "completed_with_failures"
            save_runs(self.config.runs_file, record_run(runs, slot, status=status, now_iso=now))
        return report, reason

    # -- internals ----------------------------------------------------------

    def _select(self, sources: Iterable[str] | None) -> list[Adapter]:
        if not sources:
            return self.adapters
        wanted = {name for name in sources}
        selected = [a for a in self.adapters if a.name in wanted]
        unknown = wanted - {a.name for a in self.adapters}
        if unknown:
            raise KeyError(f"unknown source(s): {sorted(unknown)}")
        return selected

    def _run_source(self, adapter: Adapter, *, now: str, dry_run: bool) -> SourceReport:
        report = SourceReport(source=adapter.name, started_at=now)
        started = self._clock()
        state = load_state(self.config.state_path, adapter.name)
        state.last_attempt_at = now
        requests_before = self.fetcher.request_count

        ctx = AdapterContext(
            fetcher=self.fetcher,
            archive=self.archive,
            state=state,
            now=now,
            limits=self.config.limits(),
            logger=LOG.getChild(adapter.name),
        )

        try:
            result = adapter.collect(ctx)
        except BaseException as exc:  # noqa: BLE001 - every failure must alert
            LOG.exception("%s: collection failed", adapter.name)
            report.status = "failed"
            report.failures.append(_failure_for(adapter.name, exc))
            state.last_status = "failed"
            state.last_error = f"{type(exc).__name__}: {exc}"
            state.consecutive_failures += 1
            state.record_history(item_count=0, page_bytes=0, status="failed", run_at=now)
            if not dry_run:
                save_state(self.config.state_path, state)
            report.duration_s = self._clock() - started
            report.requests = self.fetcher.request_count - requests_before
            return report

        report.endpoint = result.endpoint or state.endpoint
        report.page_bytes = result.page_bytes
        report.warnings.extend(result.warnings)
        report.notes.extend(result.notes)

        if result.listing_unchanged and not result.items:
            report.status = "ok"
            report.item_count = len([i for i in state.items.values() if not i.removed_at])
            report.notes.append("listing unchanged (HTTP 304); nothing to diff")
            state.last_status = "ok"
            state.last_success_at = now
            state.last_error = None
            state.consecutive_failures = 0
            state.record_history(
                item_count=report.item_count, page_bytes=0, status="ok", run_at=now
            )
            if not dry_run:
                save_state(self.config.state_path, state)
            report.duration_s = self._clock() - started
            report.requests = self.fetcher.request_count - requests_before
            return report

        items = result.items
        report.item_count = len(items)

        # Canary: a successful fetch that yields too few items is a parse
        # failure, not an empty week.
        canary = canary_failure(adapter.name, len(items), adapter.expectation, report.endpoint or "")
        if canary is not None:
            report.status = "failed"
            report.failures.append(canary)
            state.last_status = "failed"
            state.last_error = canary.message
            state.consecutive_failures += 1
            state.record_history(
                item_count=len(items), page_bytes=result.page_bytes, status="failed", run_at=now
            )
            if not dry_run:
                save_state(self.config.state_path, state)
            report.duration_s = self._clock() - started
            report.requests = self.fetcher.request_count - requests_before
            return report

        warning = drift_warning(state, item_count=len(items), page_bytes=result.page_bytes)
        if warning:
            report.warnings.append(warning)

        # Schema validation: reject bad records rather than writing partial rows.
        valid: list[Item] = []
        for item in items:
            errors = validate_record(item.to_record())
            if errors:
                report.failures.append(
                    Failure(
                        adapter.name,
                        SCHEMA,
                        f"record failed schema validation: {item.id}",
                        "\n".join(errors),
                    )
                )
                continue
            valid.append(item)

        # Watchlist matching runs over the full text, before records truncate
        # it. Matched entities are attached to the item but never hashed: the
        # watchlist changing must not look like the source changing.
        near_miss_rows: list[dict] = []
        for item in valid:
            matches = self.watchlist.match_item(item.title, item.body_text)
            item.entities = self.watchlist.entity_names(matches)

        changes = diff_items(
            state.items,
            valid,
            source=adapter.name,
            detect_removals=adapter.supports_removals,
        )
        report.changes = changes

        changed_items = [
            change.item
            for change in changes
            if change.kind in (NEW, CHANGED) and change.item is not None
        ]
        for item in changed_items:
            for near in self.watchlist.near_misses(
                f"{item.title}\n{item.body_text}", exclude=item.entities
            ):
                near_miss_rows.append(
                    {
                        "logged_at": now,
                        "source": adapter.name,
                        "item_id": item.id,
                        "url": item.url,
                        "entity": near.entity,
                        "tier": near.tier,
                        "pattern": near.pattern,
                        "candidate": near.candidate,
                        "ratio": near.ratio,
                        "context": near.context,
                    }
                )

        if not dry_run:
            written, record_errors = append_items(
                self.config.records_path,
                adapter.name,
                changed_items,
                max_body_chars=self.config.max_body_chars,
            )
            report.records_written = written
            for error in record_errors:
                report.failures.append(
                    Failure(adapter.name, SCHEMA, f"record rejected: {error.item_id}",
                            "\n".join(error.errors))
                )
            if near_miss_rows:
                writer = NearMissWriter(self.config.review_path / "near-misses.ndjson")
                report.near_miss_count = writer.append(near_miss_rows)
        else:
            report.records_written = 0
            report.near_miss_count = len(near_miss_rows)

        self._update_state(state, valid, changes, result.listing_hashes, now=now)
        state.endpoint = report.endpoint
        state.last_status = "ok" if not report.failures else "failed"
        if not report.failures:
            state.last_success_at = now
            state.last_error = None
            state.consecutive_failures = 0
        else:
            state.consecutive_failures += 1
        state.record_history(
            item_count=len(valid), page_bytes=result.page_bytes,
            status=state.last_status, run_at=now,
        )
        state.prune_removed()
        if not dry_run:
            save_state(self.config.state_path, state)

        report.status = "ok" if not report.failures else "failed"
        report.duration_s = self._clock() - started
        report.requests = self.fetcher.request_count - requests_before
        return report

    def _update_state(
        self,
        state: SourceState,
        items: Sequence[Item],
        changes: Sequence[Change],
        listing_hashes: dict[str, str],
        *,
        now: str,
    ) -> None:
        for item in items:
            previous = state.items.get(item.id)
            state.items[item.id] = ItemState(
                content_hash=item.content_hash,
                title=item.title,
                url=item.url,
                published_at=item.published_at,
                archive_path=item.archive_path or (previous.archive_path if previous else None),
                first_seen_at=(previous.first_seen_at if previous and previous.first_seen_at else now),
                last_seen_at=now,
                removed_at=None,
                body_pending=item.has_note(NOTE_BODY_PENDING),
                listing_hash=listing_hashes.get(
                    item.id, previous.listing_hash if previous else ""
                ),
            )
        for change in changes:
            if change.kind == REMOVED and change.id in state.items:
                state.items[change.id].removed_at = now
