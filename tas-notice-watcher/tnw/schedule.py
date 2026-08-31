"""Run-slot resolution and de-duplication (§2.1).

The watcher runs twice daily at 07:00 and 17:00 Australia/Hobart. GitHub Actions
cron is UTC and Hobart moves between UTC+10 and UTC+11, so the workflow
schedules *both* UTC candidates for each local time and this module decides, in
code, whether the firing is the one that counts. That is deliberately more
robust than trusting a single cron expression to be right year-round.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from .state import load_json, save_json
from .timeutil import HOBART, parse_iso, utcnow_iso

TARGET_LOCAL_HOURS = {"morning": 7, "evening": 17}
DEFAULT_TOLERANCE_MINUTES = 100
SLOT_HISTORY_LIMIT = 120


@dataclass(frozen=True)
class Slot:
    name: str  # "morning" | "evening" | "manual"
    key: str  # "YYYY-MM-DD:name" in Hobart local time
    local_time: str


def resolve_slot(
    now_iso: str | None = None,
    *,
    tolerance_minutes: int = DEFAULT_TOLERANCE_MINUTES,
) -> Slot | None:
    """Return the slot this moment belongs to, or None if it is off-schedule."""
    moment = parse_iso(now_iso or utcnow_iso()).astimezone(HOBART)
    best: tuple[float, str] | None = None
    for name, hour in TARGET_LOCAL_HOURS.items():
        target = moment.replace(hour=hour, minute=0, second=0, microsecond=0)
        for candidate in (target - timedelta(days=1), target, target + timedelta(days=1)):
            delta = abs((moment - candidate).total_seconds()) / 60.0
            if delta <= tolerance_minutes and (best is None or delta < best[0]):
                best = (delta, f"{candidate:%Y-%m-%d}:{name}")
    if best is None:
        return None
    key = best[1]
    return Slot(name=key.split(":", 1)[1], key=key, local_time=f"{moment:%Y-%m-%d %H:%M %Z}")


def manual_slot(now_iso: str | None = None) -> Slot:
    moment = parse_iso(now_iso or utcnow_iso()).astimezone(HOBART)
    return Slot(
        name="manual",
        key=f"{moment:%Y-%m-%dT%H:%M}:manual",
        local_time=f"{moment:%Y-%m-%d %H:%M %Z}",
    )


def load_runs(path: Path | str) -> dict[str, Any]:
    data = load_json(path, {"version": 1, "slots": {}})
    data.setdefault("slots", {})
    return data


def already_ran(runs: dict[str, Any], slot: Slot) -> bool:
    entry = runs["slots"].get(slot.key)
    return bool(entry and entry.get("status") == "completed")


def record_run(runs: dict[str, Any], slot: Slot, *, status: str, now_iso: str | None = None) -> dict[str, Any]:
    runs["slots"][slot.key] = {"ran_at": now_iso or utcnow_iso(), "status": status}
    if len(runs["slots"]) > SLOT_HISTORY_LIMIT:
        for key in sorted(runs["slots"])[: len(runs["slots"]) - SLOT_HISTORY_LIMIT]:
            del runs["slots"][key]
    return runs


def save_runs(path: Path | str, runs: dict[str, Any]) -> Path:
    return save_json(path, runs)


def decide(
    runs: dict[str, Any],
    *,
    now_iso: str | None = None,
    force: bool = False,
) -> tuple[bool, Slot, str]:
    """Decide whether this firing should do work.

    Returns ``(should_run, slot, reason)``. Manual dispatches always run.
    """
    if force:
        return True, manual_slot(now_iso), "forced run (manual dispatch or --force)"
    slot = resolve_slot(now_iso)
    if slot is None:
        return False, manual_slot(now_iso), (
            "off-schedule firing: not within tolerance of 07:00 or 17:00 Australia/Hobart"
        )
    if already_ran(runs, slot):
        return False, slot, f"slot {slot.key} already completed (duplicate UTC cron firing)"
    return True, slot, f"slot {slot.key} is due"
