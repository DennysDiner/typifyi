"""Command line interface.

Run from the project directory (or point ``--root`` at it):

    tnw run --dry-run          # full pipeline, no writes, no issues
    tnw discover               # confirm endpoints before trusting a selector
    tnw check                  # heartbeat only
    tnw digest --days 7        # weekly digest issue
    tnw feed                   # static Atom feed
    tnw export --since 2026-08-01T00:00:00Z
    tnw validate               # records, state and watchlist
    tnw match --text "..."     # try the watchlist against some text
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

from .config import Config
from .github import DryRunIssueClient, GitHubIssueClient
from .heartbeat import evaluate_health, health_failures, write_heartbeat
from .models import validate_record
from .outputs import export_ndjson, recent_records, render_digest, write_feed
from .records import read_records
from .report import RunReport
from .runner import Runner
from .state import load_state
from .summary import render_summary, write_job_summary
from .timeutil import parse_iso, utcnow, utcnow_iso
from .watchlist import Watchlist, WatchlistError

LOG = logging.getLogger("tnw")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _split_sources(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _issue_client(dry_run: bool, no_alert: bool):
    if dry_run or no_alert:
        return DryRunIssueClient()
    if not os.environ.get("GITHUB_TOKEN") or not os.environ.get("GITHUB_REPOSITORY"):
        LOG.warning(
            "GITHUB_TOKEN/GITHUB_REPOSITORY are not set: alerts will be printed, not posted"
        )
        return DryRunIssueClient()
    return GitHubIssueClient()


# -- commands ---------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    config = Config.from_env(args.root)
    client = _issue_client(args.dry_run, args.no_alert)
    runner = Runner(config, issue_client=client)
    report, reason = runner.run(
        sources=_split_sources(args.sources),
        force=args.force,
        respect_schedule=not args.ignore_schedule,
        dry_run=args.dry_run,
        now=args.now,
    )
    if not report.sources and not report.all_failures:
        print(f"skipped: {reason}")
        write_job_summary(f"# tas-notice-watcher\n\nSkipped: {reason}\n")
        return 0

    states = {a.name: load_state(config.state_path, a.name) for a in runner.adapters}
    healths = evaluate_health(states, {a.name: a.expectation for a in runner.adapters},
                              now=report.finished_at or utcnow_iso())
    summary = render_summary(report, healths)
    print(summary)
    write_job_summary(summary)

    if isinstance(client, DryRunIssueClient):
        for issue in client.created:
            print(f"\n--- would open issue: {issue.title}\n{issue.body}\n")
        for number, body in client.comments:
            print(f"\n--- would comment on #{number}:\n{body}\n")

    return 0 if report.ok else 1


def cmd_discover(args: argparse.Namespace) -> int:
    from adapters import get_adapters
    from adapters.base import AdapterContext

    config = Config.from_env(args.root)
    fetcher = config.fetcher()
    archive = config.archive_writer()
    findings = []
    for adapter in get_adapters(_split_sources(args.sources)):
        state = load_state(config.state_path, adapter.name)
        ctx = AdapterContext(
            fetcher=fetcher, archive=archive, state=state,
            now=utcnow_iso(), limits=config.limits(),
        )
        LOG.info("discovering %s", adapter.name)
        result = adapter.discover(ctx)
        result["checked_at"] = utcnow_iso()
        findings.append(result)
        out = config.path(Path("adapters") / adapter.name / "DISCOVERY.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    print(json.dumps(findings, indent=2, ensure_ascii=False))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from adapters import all_adapters

    config = Config.from_env(args.root)
    adapters = all_adapters()
    states = {a.name: load_state(config.state_path, a.name) for a in adapters}
    healths = evaluate_health(states, {a.name: a.expectation for a in adapters})
    report = RunReport(started_at=utcnow_iso(), finished_at=utcnow_iso(), slot="check")
    failures = health_failures(healths)
    report.global_failures.extend(failures)
    write_heartbeat(config.heartbeat_file, report, healths)

    summary = render_summary(report, healths)
    print(summary)
    write_job_summary(summary)

    if failures and not args.no_alert:
        from .alerts import dispatch

        client = _issue_client(args.dry_run, args.no_alert)
        dispatch(report, client, create_labels=config.labels_enabled)
        if isinstance(client, DryRunIssueClient):
            for issue in client.created:
                print(f"\n--- would open issue: {issue.title}\n{issue.body}\n")
    return 1 if failures else 0


def cmd_digest(args: argparse.Namespace) -> int:
    config = Config.from_env(args.root)
    since = (utcnow() - timedelta(days=args.days)).isoformat().replace("+00:00", "Z")
    rows = recent_records(config.records_path, since=since)
    digest = render_digest(rows, days=args.days, generated_at=utcnow_iso())
    if args.dry_run or args.no_alert:
        print(digest.title)
        print(digest.body)
        return 0
    client = _issue_client(False, False)
    labels = ["tnw", "tnw:digest"]
    client.ensure_labels(labels)
    issue = client.create_issue(digest.title, digest.body, labels)
    print(f"opened {issue.url}")
    return 0


def cmd_feed(args: argparse.Namespace) -> int:
    config = Config.from_env(args.root)
    out = write_feed(
        config.records_path,
        config.outputs_path / "feed.xml",
        limit=args.limit,
        self_url=args.self_url,
    )
    print(f"wrote {out}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    config = Config.from_env(args.root)
    out_path = Path(args.out) if args.out else config.outputs_path / "export.ndjson"
    out, count = export_ndjson(
        config.records_path, out_path, since=args.since, sources=_split_sources(args.sources)
    )
    print(f"wrote {count} record(s) to {out}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from adapters import all_adapters

    config = Config.from_env(args.root)
    problems = 0

    try:
        watchlist = Watchlist.load(config.watchlist_file)
        print(f"watchlist: {len(watchlist.entities)} entities, "
              f"{sum(len(e.patterns) for e in watchlist.entities)} patterns — ok")
    except WatchlistError as exc:
        print(f"watchlist: INVALID — {exc}")
        problems += 1

    count = 0
    for row in read_records(config.records_path):
        count += 1
        errors = validate_record(row)
        if errors:
            problems += 1
            print(f"record {row.get('source')}/{row.get('id')}: {'; '.join(errors)}")
    print(f"records: {count} checked, {problems} problem(s)")

    for adapter in all_adapters():
        state = load_state(config.state_path, adapter.name)
        print(
            f"state/{adapter.name}: {len(state.items)} known item(s), "
            f"last success {state.last_success_at or 'never'}, status {state.last_status}"
        )
    return 1 if problems else 0


def cmd_match(args: argparse.Namespace) -> int:
    config = Config.from_env(args.root)
    watchlist = Watchlist.load(config.watchlist_file)
    text = args.text
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    if not text:
        print("nothing to match: pass --text or --file")
        return 2
    matches = watchlist.match_item("", text)
    print(f"matches ({len(matches)}):")
    for match in matches:
        print(f"  T{match.tier} {match.entity} via {match.pattern!r} -> {match.matched_text!r}")
    near = watchlist.near_misses(text, exclude=[m.entity for m in matches])
    print(f"near misses ({len(near)}):")
    for candidate in near:
        print(f"  {candidate.ratio:.3f} {candidate.entity} ~ {candidate.candidate!r}")
    return 0


def cmd_capture_fixture(args: argparse.Namespace) -> int:
    """Save a live page into tests/fixtures so a parser bug gets a regression test."""
    config = Config.from_env(args.root)
    fetcher = config.fetcher()
    result = fetcher.get(args.url)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result.body)
    meta = {
        "url": args.url,
        "final_url": result.final_url,
        "status": result.status,
        "content_type": result.content_type,
        "fetched_at": result.fetched_at,
        "bytes": len(result.body),
    }
    out.with_suffix(out.suffix + ".meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {out} ({len(result.body)} bytes)")
    return 0


# -- argument parsing -------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tnw", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=os.environ.get("TNW_ROOT", "."),
                        help="project root (default: current directory)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the full pipeline")
    run.add_argument("--sources", help="comma-separated source names")
    run.add_argument("--force", action="store_true", help="run regardless of the schedule slot")
    run.add_argument("--ignore-schedule", action="store_true",
                     help="skip slot resolution entirely (tests and backfills)")
    run.add_argument("--dry-run", action="store_true", help="no writes, no issues")
    run.add_argument("--no-alert", action="store_true", help="write state but do not post issues")
    run.add_argument("--now", help="override the run timestamp (ISO 8601 UTC)")
    run.set_defaults(func=cmd_run)

    discover = sub.add_parser("discover", help="probe each source and record findings")
    discover.add_argument("--sources")
    discover.set_defaults(func=cmd_discover)

    check = sub.add_parser("check", help="heartbeat check only")
    check.add_argument("--dry-run", action="store_true")
    check.add_argument("--no-alert", action="store_true")
    check.set_defaults(func=cmd_check)

    digest = sub.add_parser("digest", help="weekly digest issue")
    digest.add_argument("--days", type=int, default=7)
    digest.add_argument("--dry-run", action="store_true")
    digest.add_argument("--no-alert", action="store_true")
    digest.set_defaults(func=cmd_digest)

    feed = sub.add_parser("feed", help="write the static Atom feed")
    feed.add_argument("--limit", type=int, default=100)
    feed.add_argument("--self-url", default="")
    feed.set_defaults(func=cmd_feed)

    export = sub.add_parser("export", help="export records as NDJSON")
    export.add_argument("--since", help="ISO 8601 UTC lower bound on fetched_at")
    export.add_argument("--sources")
    export.add_argument("--out")
    export.set_defaults(func=cmd_export)

    validate = sub.add_parser("validate", help="validate watchlist, records and state")
    validate.set_defaults(func=cmd_validate)

    match = sub.add_parser("match", help="test the watchlist against text")
    match.add_argument("--text")
    match.add_argument("--file")
    match.set_defaults(func=cmd_match)

    capture = sub.add_parser("capture-fixture", help="save a live page as a test fixture")
    capture.add_argument("--url", required=True)
    capture.add_argument("--out", required=True)
    capture.set_defaults(func=cmd_capture_fixture)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    if getattr(args, "since", None):
        parse_iso(args.since)  # fail fast on a malformed bound
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
