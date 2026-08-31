"""End-to-end pipeline tests — the milestone acceptance criteria (§6).

Everything runs offline against fixtures, with a fake fetcher and a dry-run
issue client that records what would have been posted.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import FakeFetcher, Route

from adapters.base import Adapter, AdapterContext, AdapterResult
from adapters.gazette import GazetteAdapter
from adapters.lobbyists import LobbyistsAdapter
from tnw.archive import LocalGzipArchiveWriter
from tnw.github import DryRunIssueClient
from tnw.models import Item
from tnw.runner import Runner
from tnw.state import load_state
from tnw.watchlist import Watchlist

NOW = "2026-08-31T21:05:00Z"
LATER = "2026-09-01T07:05:00Z"
INDEX = "https://www.gazette.tas.gov.au/editions/2026"
HOME = "https://www.gazette.tas.gov.au/"
PDFS = {
    "https://www.gazette.tas.gov.au/editions/2026/august-2026/22599_-_Gazette_12_August_2026.pdf",
    "https://www.gazette.tas.gov.au/editions/2026/august-2026/22598_-_Special_Gazette_5_August_2026.pdf",
    "https://www.gazette.tas.gov.au/editions/2026/july-2026/22590_-_Gazette_1_July_2026.pdf",
    "https://www.gazette.tas.gov.au/editions/2026/supplements/notice_supplement.pdf",
}
REGISTER = "https://lobbyists.integrity.tas.gov.au/register"
LOBBYIST_SLUGS = (
    "font_public_relations",
    "tg_public_affairs_pty_ltd",
    "regs_and_corporate_advisory_pty_ltd",
    "premiernational_pty_ltd",
)


def gazette_routes(index="editions-2026.html", *, etag=None):
    routes = {INDEX: Route.html("gazette", index, etag=etag),
              HOME: Route.html("gazette", index)}
    for url in PDFS:
        routes[url] = Route.pdf("gazette", "sample-gazette.pdf")
    return routes


def lobbyist_routes(register="register.html", font="detail-font.html", slugs=LOBBYIST_SLUGS):
    routes = {REGISTER: Route.html("lobbyists", register)}
    for slug in slugs:
        fixture = font if slug == "font_public_relations" else f"detail-{slug}.html"
        routes[f"https://lobbyists.integrity.tas.gov.au/lobbyists/{slug}"] = Route.html(
            "lobbyists", fixture
        )
    return routes


def make_runner(project, routes, adapters, *, client=None, now=NOW):
    return Runner(
        project,
        adapters=adapters,
        fetcher=FakeFetcher(routes, now=now),
        archive=LocalGzipArchiveWriter(project.archive_path),
        watchlist=Watchlist.load(project.watchlist_file),
        issue_client=client or DryRunIssueClient(),
    )


# -- M0: scaffold and one source end to end ---------------------------------


def test_m0_a_run_archives_records_and_commits_state(project):
    runner = make_runner(project, gazette_routes(), [GazetteAdapter()])
    report, _ = runner.run(force=True, now=NOW)

    assert report.ok, [f.message for f in report.all_failures]
    [source] = report.sources
    assert source.status == "ok" and source.item_count >= 3

    records = sorted(project.records_path.glob("gazette-*.ndjson"))
    assert records, "records must be written"
    rows = [json.loads(line) for line in records[0].read_text().splitlines()]
    assert rows and all(row["source"] == "gazette" for row in rows)

    archived = list(project.archive_path.rglob("*.gz"))
    assert any(path.name.endswith(".pdf.gz") for path in archived)
    for row in rows:
        if row["archive_path"]:
            assert Path(row["archive_path"]).exists(), "every archive_path must resolve"

    state = load_state(project.state_path, "gazette")
    assert state.last_success_at == NOW
    assert state.consecutive_failures == 0
    assert len(state.items) >= 3
    assert project.heartbeat_file.exists()
    assert json.loads(project.runs_file.read_text())["slots"]


# -- M1: diff and alerting ---------------------------------------------------


def test_m1_a_new_issue_produces_one_alert_with_entities_and_archive_paths(project):
    client = DryRunIssueClient()
    runner = make_runner(project, gazette_routes(), [GazetteAdapter()], client=client)
    runner.run(force=True, now=NOW)

    assert len(client.created) == 1
    issue = client.created[0]
    assert "Nyrstar" in issue.title  # tier-1 hit is promoted into the title
    assert "gazette:22599" in issue.body
    assert "2026-08-12" in issue.body
    assert "archive/" in issue.body or ".gz" in issue.body
    assert "not stated by source" in issue.body  # the undated supplement
    assert "tnw:source:gazette" in issue.title + " ".join(client.labels_ensured)


def test_m1_a_rerun_with_no_change_produces_no_alert(project):
    client = DryRunIssueClient()
    routes = gazette_routes()
    runner = make_runner(project, routes, [GazetteAdapter()], client=client)
    runner.run(force=True, now=NOW)
    assert len(client.created) == 1

    second = make_runner(project, routes, [GazetteAdapter()], client=client, now=LATER)
    report, _ = second.run(force=True, now=LATER)

    assert len(client.created) == 1, "an unchanged run must not open an issue"
    assert report.all_changes == []
    assert report.ok


def test_m1_a_304_listing_is_a_quiet_successful_run(project):
    client = DryRunIssueClient()
    routes = gazette_routes(etag='"v1"')
    make_runner(project, routes, [GazetteAdapter()], client=client).run(force=True, now=NOW)
    report, _ = make_runner(
        project, routes, [GazetteAdapter()], client=client, now=LATER
    ).run(force=True, now=LATER)

    assert len(client.created) == 1
    assert report.sources[0].status == "ok"
    assert any("304" in note for note in report.sources[0].notes)
    assert load_state(project.state_path, "gazette").last_success_at == LATER


def test_m1_removals_are_detected_and_alerted(project):
    client = DryRunIssueClient()
    make_runner(project, lobbyist_routes(), [LobbyistsAdapter()], client=client).run(
        force=True, now=NOW
    )
    shrunk = lobbyist_routes(register="register.html", slugs=LOBBYIST_SLUGS)
    shrunk[REGISTER] = Route(
        body=b"""<html><body><ul>
        <li><a href="/lobbyists/tg_public_affairs_pty_ltd">TG Public Affairs Pty Ltd</a></li>
        <li><a href="/lobbyists/regs_and_corporate_advisory_pty_ltd">Regs and Corporate Advisory Pty Ltd</a></li>
        <li><a href="/lobbyists/premiernational_pty_ltd">PremierNational Pty Ltd</a></li>
        </ul></body></html>"""
    )
    report, _ = make_runner(
        project, shrunk, [LobbyistsAdapter()], client=client, now=LATER
    ).run(force=True, now=LATER)

    removed = [change for change in report.all_changes if change.kind == "removed"]
    assert [change.id for change in removed] == ["lobbyists:font_public_relations"]
    assert "Removed (1)" in client.created[-1].body

    # A removal is reported once, not on every subsequent run.
    third, _ = make_runner(
        project, shrunk, [LobbyistsAdapter()], client=client, now="2026-09-01T21:05:00Z"
    ).run(force=True, now="2026-09-01T21:05:00Z")
    assert [c for c in third.all_changes if c.kind == "removed"] == []


def test_m1_a_changed_client_list_alerts_as_changed(project):
    client = DryRunIssueClient()
    make_runner(project, lobbyist_routes(), [LobbyistsAdapter()], client=client).run(
        force=True, now=NOW
    )
    report, _ = make_runner(
        project,
        lobbyist_routes(font="detail-font-changed.html"),
        [LobbyistsAdapter()],
        client=client,
        now=LATER,
    ).run(force=True, now=LATER)

    changed = [change for change in report.all_changes if change.kind == "changed"]
    assert [change.id for change in changed] == ["lobbyists:font_public_relations"]
    assert "Nyrstar" in client.created[-1].title
    assert "body_text changed" in client.created[-1].body


# -- M2: failure detection ---------------------------------------------------


def test_m2_a_broken_selector_opens_a_failure_issue_instead_of_going_quiet(project):
    """The M2 acceptance criterion, exactly: break the page, get a FAILURE."""
    client = DryRunIssueClient()
    routes = gazette_routes(index="editions-2026-broken.html")
    report, _ = make_runner(project, routes, [GazetteAdapter()], client=client).run(
        force=True, now=NOW
    )

    assert not report.ok
    assert [f.kind for f in report.all_failures] == ["parse"]
    assert len(client.created) == 1
    issue = client.created[0]
    assert "FAILURE" in issue.title and "gazette" in issue.title
    assert "tnw:failure" in client.labels_ensured
    assert list(project.records_path.glob("*.ndjson")) == []

    state = load_state(project.state_path, "gazette")
    assert state.last_status == "failed" and state.consecutive_failures == 1


def test_m2_a_recurring_failure_comments_rather_than_spamming_new_issues(project):
    client = DryRunIssueClient()
    routes = gazette_routes(index="editions-2026-broken.html")
    make_runner(project, routes, [GazetteAdapter()], client=client).run(force=True, now=NOW)
    client.existing = list(client.created)
    make_runner(project, routes, [GazetteAdapter()], client=client, now=LATER).run(
        force=True, now=LATER
    )

    assert len(client.created) == 1
    assert len(client.comments) == 1
    assert "Still failing" in client.comments[0][1]


def test_m2_a_stale_source_alerts_even_when_it_was_not_selected(project):
    client = DryRunIssueClient()
    runner = make_runner(project, gazette_routes(), [GazetteAdapter(), LobbyistsAdapter()],
                         client=client)
    report, _ = runner.run(sources=["gazette"], force=True, now=NOW)

    stale = [f for f in report.all_failures if f.source == "lobbyists"]
    assert stale and stale[0].kind == "stale"
    assert any("lobbyists" in issue.title for issue in client.created)


def test_m2_a_fetch_failure_is_reported_and_state_records_it(project):
    client = DryRunIssueClient()
    report, _ = make_runner(project, {}, [GazetteAdapter()], client=client).run(
        force=True, now=NOW
    )
    assert [f.kind for f in report.all_failures] == ["fetch"]
    assert "no candidate endpoint could be fetched" in report.all_failures[0].message
    assert load_state(project.state_path, "gazette").last_error


class InvalidItemAdapter(Adapter):
    """Emits a record that cannot pass schema validation."""

    name = "tenders"
    label = "invalid"
    min_expected_items = 1
    supports_removals = False

    def collect(self, ctx: AdapterContext) -> AdapterResult:
        return AdapterResult(
            items=[
                Item(id="tenders:bad", source="tenders", title="Bad", url="not-a-url",
                     content_hash="short", fetched_at="whenever"),
                Item(id="tenders:ok", source="tenders", title="Good",
                     url="https://www.tenders.tas.gov.au/Tender/View/1",
                     content_hash="a" * 64, fetched_at=ctx.now, http_status=200),
            ],
            page_bytes=100,
            endpoint="https://www.tenders.tas.gov.au/tender/list",
        )


def test_m2_invalid_records_are_rejected_and_alerted_not_written(project):
    client = DryRunIssueClient()
    report, _ = make_runner(project, {}, [InvalidItemAdapter()], client=client).run(
        force=True, now=NOW
    )

    schema_failures = [f for f in report.all_failures if f.kind == "schema"]
    assert schema_failures and "tenders:bad" in schema_failures[0].message
    rows = [
        json.loads(line)
        for path in project.records_path.glob("tenders-*.ndjson")
        for line in path.read_text().splitlines()
    ]
    assert [row["id"] for row in rows] == ["tenders:ok"]
    assert any("FAILURE" in issue.title for issue in client.created)


class EmptyAdapter(Adapter):
    name = "tenders"
    label = "empty"
    min_expected_items = 5
    supports_removals = False

    def collect(self, ctx: AdapterContext) -> AdapterResult:
        return AdapterResult(items=[], page_bytes=50_000, endpoint="https://x.tas.gov.au/list")


def test_m2_too_few_items_from_a_200_is_a_canary_failure(project):
    client = DryRunIssueClient()
    report, _ = make_runner(project, {}, [EmptyAdapter()], client=client).run(force=True, now=NOW)
    canary = [f for f in report.all_failures if f.kind == "canary"]
    assert canary and "expected at least 5" in canary[0].message
    assert any("FAILURE" in issue.title for issue in client.created)


# -- scheduling and isolation ------------------------------------------------


def test_an_off_schedule_firing_does_no_work(project):
    client = DryRunIssueClient()
    runner = make_runner(project, gazette_routes(), [GazetteAdapter()], client=client)
    report, reason = runner.run(now="2026-08-31T12:00:00Z")
    assert report.sources == [] and "off-schedule" in reason
    assert client.created == []


def test_the_duplicate_utc_cron_firing_is_skipped(project):
    routes = gazette_routes()
    make_runner(project, routes, [GazetteAdapter()]).run(now="2026-08-31T21:00:00Z")
    report, reason = make_runner(project, routes, [GazetteAdapter()], now="2026-08-31T22:00:00Z").run(
        now="2026-08-31T22:00:00Z"
    )
    assert report.sources == [] and "already completed" in reason


def test_one_broken_source_does_not_hide_another_source(project):
    client = DryRunIssueClient()
    routes = {**gazette_routes(index="editions-2026-broken.html"), **lobbyist_routes()}
    report, _ = make_runner(
        project, routes, [GazetteAdapter(), LobbyistsAdapter()], client=client
    ).run(force=True, now=NOW)

    statuses = {source.source: source.status for source in report.sources}
    assert statuses == {"gazette": "failed", "lobbyists": "ok"}
    assert any("FAILURE" in issue.title for issue in client.created)
    assert any("change" in issue.title for issue in client.created)


def test_dry_run_writes_nothing(project):
    client = DryRunIssueClient()
    runner = make_runner(project, gazette_routes(), [GazetteAdapter()], client=client)
    report, _ = runner.run(force=True, now=NOW, dry_run=True)

    assert report.all_changes
    assert list(project.records_path.glob("*.ndjson")) == []
    assert not (project.state_path / "gazette.json").exists()
    assert not project.heartbeat_file.exists()
    assert not project.runs_file.exists()
    assert client.created == []


def test_dry_run_writes_nothing_when_a_source_fails_either(project):
    runner = make_runner(project, gazette_routes(index="editions-2026-broken.html"),
                         [GazetteAdapter()])
    report, _ = runner.run(force=True, now=NOW, dry_run=True)
    assert not report.ok
    assert list(project.state_path.glob("*.json")) == []


def test_near_misses_are_logged_for_review(project):
    routes = lobbyist_routes()
    routes["https://lobbyists.integrity.tas.gov.au/lobbyists/premiernational_pty_ltd"] = Route(
        body=b"<html><body><h1>PremierNational Pty Ltd</h1><h2>Clients</h2>"
        b"<ul><li>Nyrstarr Hobart Pty Ltd</li><li>Libertty Bell Bay</li></ul></body></html>"
    )
    report, _ = make_runner(project, routes, [LobbyistsAdapter()]).run(force=True, now=NOW)

    review = project.review_path / "near-misses.ndjson"
    assert review.exists()
    rows = [json.loads(line) for line in review.read_text().splitlines()]
    assert {row["entity"] for row in rows} >= {"Nyrstar", "Liberty Bell Bay"}
    assert all(0.86 <= row["ratio"] < 1.0 for row in rows)
    assert report.sources[0].near_miss_count == len(rows)


def test_a_robots_block_is_reported_as_robots_not_as_a_parse_failure(project):
    """Triage depends on the kind: "disallowed" and "structure changed" differ."""
    from tnw.fetcher import RobotsDisallowed

    routes = {
        url: Route(error=RobotsDisallowed("robots.txt disallows this URL", url=url))
        for url in (INDEX, HOME)
    }
    report, _ = make_runner(project, routes, [GazetteAdapter()]).run(force=True, now=NOW)
    assert [f.kind for f in report.all_failures] == ["robots"]


def test_a_transport_failure_on_every_candidate_is_reported_as_a_fetch_failure(project):
    from tnw.fetcher import TransientFetchError

    routes = {
        url: Route(error=TransientFetchError("HTTP 503", url=url, status=503))
        for url in (
            REGISTER,
            "https://lobbyists.integrity.tas.gov.au/",
            "https://lobbyists.dpac.tas.gov.au/",
        )
    }
    report, _ = make_runner(project, routes, [LobbyistsAdapter()]).run(force=True, now=NOW)
    assert [f.kind for f in report.all_failures] == ["fetch"]
