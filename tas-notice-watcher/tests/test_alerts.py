"""Alert rendering and dispatch (§2.5)."""

from __future__ import annotations

from tnw.alerts import (
    LABEL_FAILURE,
    dispatch,
    fingerprint_marker,
    render_change_issue,
    render_failure_issue,
)
from tnw.diff import CHANGED, NEW, REMOVED, Change
from tnw.github import DryRunIssueClient, IssueRef
from tnw.models import Item
from tnw.report import Failure, RunReport, SourceReport
from tnw.state import ItemState
from tnw.watchlist import Watchlist

NOW = "2026-08-31T21:05:00Z"

WATCHLIST = Watchlist.from_dict(
    {
        "entities": [
            {"name": "Nyrstar", "tier": 1, "patterns": ["Nyrstar"]},
            {"name": "Forico", "tier": 2, "patterns": ["Forico"]},
        ]
    }
)


def build_report() -> RunReport:
    item = Item(
        id="gazette:22599",
        source="gazette",
        title="22599 - Gazette 12 August 2026",
        url="https://www.gazette.tas.gov.au/editions/2026/x.pdf",
        published_at="2026-08-12",
        body_text="Nyrstar land acquisition",
        entities=["Nyrstar"],
        content_hash="a" * 64,
        fetched_at=NOW,
        http_status=200,
        archive_path="archive/2026/08/gazette/abc.pdf.gz",
        source_notes="kind: regular; pages: 40",
    )
    undated = Item(
        id="gazette:supp",
        source="gazette",
        title="Supplement to the Gazette",
        url="https://www.gazette.tas.gov.au/editions/2026/s.pdf",
        published_at=None,
        entities=["Forico"],
        content_hash="b" * 64,
        fetched_at=NOW,
        http_status=200,
        archive_path="archive/2026/08/gazette/def.pdf.gz",
        source_notes="published_at_not_stated_by_source",
    )
    source = SourceReport(source="gazette", status="ok", started_at=NOW, item_count=2)
    source.changes = [
        Change(kind=NEW, id=item.id, title=item.title, url=item.url, source="gazette", item=item),
        Change(kind=CHANGED, id=undated.id, title=undated.title, url=undated.url,
               source="gazette", item=undated, field_changes=["body_text changed"]),
        Change(kind=REMOVED, id="gazette:old", title="Old issue", url="https://x/old.pdf",
               source="gazette",
               previous=ItemState(content_hash="c" * 64, title="Old issue",
                                  url="https://x/old.pdf", published_at="2026-01-01",
                                  archive_path="archive/old.gz", last_seen_at=NOW)),
    ]
    report = RunReport(started_at=NOW, finished_at=NOW, slot="2026-09-01:morning", duration_s=12.0)
    report.sources = [source]
    return report


def test_the_title_promotes_tier_one_hits_and_names_the_sources():
    title, _, labels = render_change_issue(build_report(), WATCHLIST)
    assert title.startswith("[tnw] 3 changes")
    assert "P1: Nyrstar" in title
    assert "[gazette]" in title
    assert set(labels) == {"tnw", "tnw:source:gazette", "tnw:priority:1"}


def test_every_alerted_item_carries_the_required_evidence():
    _, body, _ = render_change_issue(build_report(), WATCHLIST)
    assert "22599 - Gazette 12 August 2026" in body
    assert "source: `gazette`" in body
    assert "stated publication date: 2026-08-12" in body
    assert "https://www.gazette.tas.gov.au/editions/2026/x.pdf" in body
    assert "Nyrstar (T1)" in body
    assert "archive/2026/08/gazette/abc.pdf.gz" in body
    assert "content hash: `" + "a" * 64 in body


def test_an_undated_item_says_so_instead_of_showing_the_fetch_date():
    _, body, _ = render_change_issue(build_report(), WATCHLIST)
    assert "**not stated by source** (never inferred from the fetch date)" in body
    assert "flag: `published_at_missing`" in body
    assert NOW.split("T")[0] not in body.split("stated publication date: **not stated")[1][:80]


def test_removals_are_shown_with_their_last_known_archive():
    _, body, _ = render_change_issue(build_report(), WATCHLIST)
    assert "### Removed (1)" in body
    assert "archive/old.gz" in body


def test_no_summarisation_claim_is_made_in_the_body():
    _, body, _ = render_change_issue(build_report(), WATCHLIST)
    assert "No text in this issue is machine-summarised." in body


def test_failure_issues_carry_a_stable_fingerprint():
    report = build_report()
    failure = Failure("gazette", "parse", "no issue PDFs were found", "traceback…")
    title, body, labels = render_failure_issue(failure, report)
    assert title.startswith("[tnw] FAILURE (parse) — gazette")
    assert fingerprint_marker(failure.fingerprint) in body
    assert LABEL_FAILURE in labels
    assert Failure("gazette", "parse", "no issue PDFs were found").fingerprint == failure.fingerprint
    assert Failure("gazette", "parse", "something else").fingerprint != failure.fingerprint


def test_dispatch_opens_one_change_issue_and_one_issue_per_new_failure():
    report = build_report()
    report.global_failures.append(Failure("tenders", "fetch", "boom", "detail"))
    client = DryRunIssueClient()
    result = dispatch(report, client, watchlist=WATCHLIST)

    assert result.change_issue is not None
    assert len(result.failure_issues) == 1
    assert len(client.created) == 2


def test_dispatch_comments_on_an_existing_failure_issue():
    report = build_report()
    failure = Failure("tenders", "fetch", "boom", "detail")
    report.global_failures.append(failure)
    client = DryRunIssueClient()
    client.existing = [
        IssueRef(number=7, url="https://github.com/x/y/issues/7", title="old",
                 body=fingerprint_marker(failure.fingerprint))
    ]
    result = dispatch(report, client, watchlist=WATCHLIST)

    assert result.failure_issues == []
    assert result.failure_comments == [7]


def test_a_quiet_run_posts_nothing():
    report = RunReport(started_at=NOW, finished_at=NOW, slot="2026-09-01:morning")
    report.sources = [SourceReport(source="gazette", status="ok", item_count=12)]
    client = DryRunIssueClient()
    result = dispatch(report, client)
    assert result.change_issue is None and client.created == []


def test_the_body_is_bounded_for_a_very_large_run():
    report = build_report()
    source = report.sources[0]
    template = source.changes[0]
    source.changes = [
        Change(kind=NEW, id=f"gazette:{index}", title=f"Issue {index}", url=template.url,
               source="gazette", item=template.item)
        for index in range(200)
    ]
    _, body, _ = render_change_issue(report, WATCHLIST)
    assert "further items omitted" in body
    assert len(body) < 65_536  # GitHub rejects bodies over 65,536 characters
