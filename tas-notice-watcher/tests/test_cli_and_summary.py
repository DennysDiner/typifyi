"""CLI wiring and the run summary (§5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ROOT

from tnw.cli import main
from tnw.diff import NEW, Change
from tnw.heartbeat import Expectation, evaluate_health
from tnw.models import Item
from tnw.records import append_items
from tnw.report import Failure, RunReport, SourceReport
from tnw.state import SourceState
from tnw.summary import render_summary, write_job_summary

NOW = "2026-08-31T21:05:00Z"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "state").mkdir()
    (tmp_path / "records").mkdir()
    (tmp_path / "watchlist.yml").write_text(
        (ROOT / "watchlist.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    append_items(
        tmp_path / "records",
        "gazette",
        [
            Item(id="gazette:22599", source="gazette", title="22599 - Gazette 12 August 2026",
                 url="https://www.gazette.tas.gov.au/a.pdf", published_at="2026-08-12",
                 body_text="Nyrstar Hobart", entities=["Nyrstar"], content_hash="a" * 64,
                 fetched_at=NOW, http_status=200, archive_path="archive/a.pdf.gz")
        ],
    )
    return tmp_path


def test_validate_passes_on_a_healthy_project(root, capsys):
    assert main(["--root", str(root), "validate"]) == 0
    out = capsys.readouterr().out
    assert "watchlist:" in out and "records: 1 checked, 0 problem(s)" in out


def test_validate_reports_a_corrupt_record(root, capsys):
    target = next((root / "records").glob("*.ndjson"))
    row = json.loads(target.read_text().splitlines()[0])
    row["content_hash"] = "nope"
    target.write_text(json.dumps(row) + "\n")

    assert main(["--root", str(root), "validate"]) == 1
    assert "content_hash" in capsys.readouterr().out


def test_check_alerts_on_a_source_that_has_never_run(root, capsys):
    assert main(["--root", str(root), "check", "--dry-run"]) == 1
    out = capsys.readouterr().out
    assert "never_run" in out
    assert "would open issue" in out


def test_feed_and_export_write_files(root, capsys):
    assert main(["--root", str(root), "feed"]) == 0
    assert (root / "outputs" / "feed.xml").exists()
    assert main(["--root", str(root), "export", "--out", str(root / "outputs" / "e.ndjson")]) == 0
    assert (root / "outputs" / "e.ndjson").read_text().count("\n") == 1


def test_digest_dry_run_prints_without_posting(root, capsys):
    assert main(["--root", str(root), "digest", "--days", "30", "--dry-run"]) == 0
    assert "Weekly digest" in capsys.readouterr().out


def test_match_reports_hits_and_near_misses(root, capsys):
    assert main(["--root", str(root), "match", "--text",
                 "Nyrstar Hobart and Libertty Bell Bay"]) == 0
    out = capsys.readouterr().out
    assert "T1 Nyrstar" in out
    assert "Libertty Bell Bay" in out


def test_a_malformed_since_bound_fails_fast(root):
    with pytest.raises(ValueError):
        main(["--root", str(root), "export", "--since", "last tuesday"])


def test_the_summary_shows_every_source_and_its_health():
    report = RunReport(started_at=NOW, finished_at=NOW, slot="2026-09-01:morning", duration_s=8.5)
    ok = SourceReport(source="gazette", status="ok", item_count=3, records_written=1,
                      requests=4, page_bytes=1234, endpoint="https://x/editions/2026")
    ok.changes = [Change(kind=NEW, id="gazette:1", title="T", url="https://x/a", source="gazette")]
    ok.warnings.append("no usable text layer")
    failed = SourceReport(source="tenders", status="failed")
    failed.failures.append(Failure("tenders", "parse", "no rows extracted"))
    report.sources = [ok, failed]

    healths = evaluate_health(
        {"gazette": SourceState(source="gazette", last_success_at=NOW)},
        {
            "gazette": Expectation("gazette", 12, 24, 1),
            "tenders": Expectation("tenders", 12, 24, 1),
        },
        now=NOW,
    )
    summary = render_summary(report, healths)

    assert "| gazette | 🟢 ok | 3 |" in summary
    assert "| tenders | 🔴 failed |" in summary
    assert "## Heartbeat" in summary
    assert "never_run" in summary
    assert "no usable text layer" in summary
    assert "**parse**: no rows extracted" in summary


def test_the_job_summary_is_appended_when_running_in_actions(tmp_path, monkeypatch):
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    write_job_summary("# one\n")
    write_job_summary("# two\n")
    assert target.read_text() == "# one\n# two\n"


def test_no_job_summary_outside_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert write_job_summary("# nothing\n") is None
