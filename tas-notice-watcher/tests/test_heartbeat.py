"""Failure detection: heartbeat, canary counts, structural drift (§5)."""

from __future__ import annotations

from tnw.heartbeat import (
    FAILED,
    NEVER_RUN,
    OK,
    STALE_STATUS,
    Expectation,
    canary_failure,
    drift_warning,
    evaluate_health,
    health_failures,
)
from tnw.state import SourceState

NOW = "2026-08-31T21:05:00Z"
EXPECTATION = Expectation(
    source="gazette", expected_interval_hours=12, grace_hours=24, min_expected_items=1
)


def state_with(**overrides) -> SourceState:
    state = SourceState(source="gazette")
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_a_source_that_has_never_run_is_reported():
    [health] = evaluate_health({}, {"gazette": EXPECTATION}, now=NOW)
    assert health.status == NEVER_RUN
    assert [f.kind for f in health_failures([health])] == ["stale"]


def test_a_recent_success_is_healthy():
    state = state_with(last_success_at="2026-08-31T09:00:00Z")
    [health] = evaluate_health({"gazette": state}, {"gazette": EXPECTATION}, now=NOW)
    assert health.status == OK
    assert health_failures([health]) == []


def test_a_silent_source_goes_stale_and_alerts():
    """A weekly gazette silent for ten days is a broken parser until proven otherwise."""
    state = state_with(last_success_at="2026-08-21T21:00:00Z")
    [health] = evaluate_health({"gazette": state}, {"gazette": EXPECTATION}, now=NOW)
    assert health.status == STALE_STATUS
    assert health.hours_since_success > 36
    failures = health_failures([health])
    assert failures and failures[0].source == "gazette"


def test_consecutive_failures_are_surfaced():
    state = state_with(
        last_success_at="2026-08-31T09:00:00Z", consecutive_failures=2, last_error="boom"
    )
    [health] = evaluate_health({"gazette": state}, {"gazette": EXPECTATION}, now=NOW)
    assert health.status == FAILED
    assert "boom" in health.message


def test_zero_items_from_a_successful_fetch_is_a_parse_failure():
    failure = canary_failure("gazette", 0, EXPECTATION, "https://x/editions/2026")
    assert failure is not None
    assert failure.kind == "canary"
    assert "expected at least 1" in failure.message
    assert canary_failure("gazette", 1, EXPECTATION, "https://x") is None


def test_drift_is_flagged_against_the_trailing_median():
    state = SourceState(source="gazette")
    for _ in range(8):
        state.record_history(item_count=40, page_bytes=100_000, status="ok", run_at=NOW)
    assert drift_warning(state, item_count=40, page_bytes=100_000) is None
    warning = drift_warning(state, item_count=3, page_bytes=100_000)
    assert warning and "structural drift" in warning


def test_drift_needs_enough_history_before_it_speaks():
    state = SourceState(source="gazette")
    state.record_history(item_count=40, page_bytes=100_000, status="ok", run_at=NOW)
    assert drift_warning(state, item_count=1, page_bytes=100_000) is None


def test_failed_runs_do_not_pollute_the_drift_baseline():
    state = SourceState(source="gazette")
    for _ in range(8):
        state.record_history(item_count=0, page_bytes=100_000, status="failed", run_at=NOW)
    assert drift_warning(state, item_count=40, page_bytes=100_000) is None
