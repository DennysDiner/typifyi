"""Failure detection (§5).

Silent failure is the primary risk to this project's usefulness, so absence of
alerts must be distinguishable from absence of events. Three mechanisms:

* **heartbeat** — a source that has not fetched successfully within its expected
  interval plus grace is a broken parser until proven otherwise;
* **canary counts** — zero (or implausibly few) items from a 200 response is a
  parse failure, not an empty week;
* **structural drift** — a large shift in items-per-byte against the trailing
  median is logged as a warning before it becomes a silent breakage.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .report import CANARY, STALE, Failure, RunReport
from .state import SourceState, save_json
from .timeutil import hours_between, utcnow_iso

OK = "ok"
STALE_STATUS = "stale"
FAILED = "failed"
NEVER_RUN = "never_run"

DEFAULT_DRIFT_FACTOR = 2.5
MIN_HISTORY_FOR_DRIFT = 5


@dataclass(frozen=True)
class Expectation:
    """What an adapter promises about its source."""

    source: str
    expected_interval_hours: float
    grace_hours: float
    min_expected_items: int
    description: str = ""


@dataclass
class SourceHealth:
    source: str
    status: str
    last_success_at: str | None
    hours_since_success: float | None
    expected_interval_hours: float
    grace_hours: float
    consecutive_failures: int
    last_item_count: int
    min_expected_items: int
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_health(
    states: Mapping[str, SourceState],
    expectations: Mapping[str, Expectation],
    *,
    now: str | None = None,
) -> list[SourceHealth]:
    now = now or utcnow_iso()
    healths: list[SourceHealth] = []
    for source, expectation in sorted(expectations.items()):
        state = states.get(source)
        last_success = state.last_success_at if state else None
        last_count = state.history[-1].item_count if state and state.history else 0
        failures = state.consecutive_failures if state else 0

        if last_success is None:
            status = NEVER_RUN
            age = None
            message = "no successful fetch has ever been recorded"
        else:
            age = hours_between(last_success, now)
            deadline = expectation.expected_interval_hours + expectation.grace_hours
            if age > deadline:
                status = STALE_STATUS
                message = (
                    f"last successful fetch was {age:.1f}h ago; expected at least every "
                    f"{expectation.expected_interval_hours:.0f}h "
                    f"(+{expectation.grace_hours:.0f}h grace)"
                )
            elif failures:
                status = FAILED
                message = f"{failures} consecutive failure(s); last error: {state.last_error}"
            else:
                status = OK
                message = f"last successful fetch {age:.1f}h ago"
        healths.append(
            SourceHealth(
                source=source,
                status=status,
                last_success_at=last_success,
                hours_since_success=None if age is None else round(age, 2),
                expected_interval_hours=expectation.expected_interval_hours,
                grace_hours=expectation.grace_hours,
                consecutive_failures=failures,
                last_item_count=last_count,
                min_expected_items=expectation.min_expected_items,
                message=message,
            )
        )
    return healths


def health_failures(healths: Iterable[SourceHealth]) -> list[Failure]:
    """Turn stale/never-run heartbeats into alertable failures."""
    failures: list[Failure] = []
    for health in healths:
        if health.status in (STALE_STATUS, NEVER_RUN):
            failures.append(
                Failure(
                    source=health.source,
                    kind=STALE,
                    message=f"heartbeat: {health.status}",
                    detail=health.message,
                )
            )
    return failures


def canary_failure(source: str, item_count: int, expectation: Expectation, endpoint: str) -> Failure | None:
    """Too few items from a successful fetch is a parse failure, not a quiet week."""
    if item_count >= expectation.min_expected_items:
        return None
    return Failure(
        source=source,
        kind=CANARY,
        message=(
            f"extracted {item_count} item(s) from a successful fetch, "
            f"expected at least {expectation.min_expected_items}"
        ),
        detail=(
            f"endpoint: {endpoint}\n"
            "A 200 response that yields no items means the page structure changed "
            "or a selector broke. Treat as broken until re-checked by hand."
        ),
    )


def drift_warning(
    state: SourceState,
    *,
    item_count: int,
    page_bytes: int,
    factor: float = DEFAULT_DRIFT_FACTOR,
) -> str | None:
    """Warn when items-per-byte moves sharply against the trailing median."""
    ratios = [
        entry.item_count / entry.page_bytes
        for entry in state.history
        if entry.page_bytes > 0 and entry.status == "ok"
    ]
    if len(ratios) < MIN_HISTORY_FOR_DRIFT or page_bytes <= 0:
        return None
    median = statistics.median(ratios)
    if median <= 0:
        return None
    current = item_count / page_bytes
    if current > median * factor or current < median / factor:
        return (
            f"structural drift: {item_count} items in {page_bytes} bytes "
            f"({current:.3e} items/byte) against a trailing median of {median:.3e} "
            f"(threshold ×{factor})"
        )
    return None


def write_heartbeat(
    path: Path | str,
    report: RunReport,
    healths: Iterable[SourceHealth],
) -> Path:
    payload = {
        "written_at": utcnow_iso(),
        "run": report.to_dict(),
        "sources": [health.to_dict() for health in healths],
    }
    return save_json(path, payload)
