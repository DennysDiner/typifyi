"""Twice-daily slot resolution and de-duplication (§2.1).

Hobart moves between UTC+10 (AEST) and UTC+11 (AEDT), so the workflow fires four
UTC crons a day and the duplicates are dropped here rather than in cron syntax.
"""

from __future__ import annotations

import pytest

from tnw.schedule import decide, load_runs, manual_slot, record_run, resolve_slot


@pytest.mark.parametrize(
    "moment, expected",
    [
        # August: AEST (UTC+10)
        ("2026-08-31T21:00:00Z", "2026-09-01:morning"),   # 07:00 local
        ("2026-08-31T07:00:00Z", "2026-08-31:evening"),   # 17:00 local
        # January: AEDT (UTC+11)
        ("2026-01-14T20:00:00Z", "2026-01-15:morning"),   # 07:00 local
        ("2026-01-14T06:00:00Z", "2026-01-14:evening"),   # 17:00 local
    ],
)
def test_both_daylight_saving_states_resolve_to_the_right_slot(moment, expected):
    slot = resolve_slot(moment)
    assert slot is not None and slot.key == expected


def test_the_other_utc_cron_maps_to_the_same_slot():
    """Both scheduled UTC firings for one local time must share a slot key."""
    aest = resolve_slot("2026-08-31T21:00:00Z")
    aedt_candidate = resolve_slot("2026-08-31T20:00:00Z")
    assert aest.key == aedt_candidate.key == "2026-09-01:morning"


def test_an_off_schedule_firing_is_not_a_slot():
    assert resolve_slot("2026-08-31T12:00:00Z") is None


def test_the_second_firing_of_a_slot_is_skipped():
    runs = load_runs("/nonexistent/runs.json")
    should_run, slot, _ = decide(runs, now_iso="2026-08-31T21:00:00Z")
    assert should_run
    record_run(runs, slot, status="completed", now_iso="2026-08-31T21:05:00Z")
    should_run_again, _, reason = decide(runs, now_iso="2026-08-31T22:00:00Z")
    assert not should_run_again
    assert "already completed" in reason


def test_a_failed_slot_is_retried_by_the_next_firing():
    runs = load_runs("/nonexistent/runs.json")
    _, slot, _ = decide(runs, now_iso="2026-08-31T21:00:00Z")
    record_run(runs, slot, status="failed", now_iso="2026-08-31T21:05:00Z")
    should_run, _, _ = decide(runs, now_iso="2026-08-31T22:00:00Z")
    assert should_run


def test_manual_dispatch_always_runs():
    runs = load_runs("/nonexistent/runs.json")
    should_run, slot, reason = decide(runs, now_iso="2026-08-31T12:00:00Z", force=True)
    assert should_run and slot.name == "manual" and "forced" in reason


def test_slot_history_is_bounded():
    runs = {"version": 1, "slots": {}}
    for day in range(1, 200):
        slot = manual_slot(f"2026-01-01T00:{day % 60:02d}:00Z")
        slot = type(slot)(name="morning", key=f"2026-{(day % 12) + 1:02d}-{(day % 28) + 1:02d}:morning",
                          local_time="")
        record_run(runs, slot, status="completed", now_iso="2026-01-01T00:00:00Z")
    assert len(runs["slots"]) <= 120
