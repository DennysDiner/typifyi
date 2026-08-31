"""Time helpers.

Every timestamp the system writes is ISO 8601 in UTC with a trailing ``Z``.
``published_at`` values are the exception: they are whatever the source states,
normalised to ISO 8601 but never invented (see :mod:`tnw.models`).
"""

from __future__ import annotations

import datetime as _dt
import re
from zoneinfo import ZoneInfo

HOBART = ZoneInfo("Australia/Hobart")
UTC = _dt.timezone.utc

ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
# Accepts a bare date, or a date-time with or without an offset.
ISO_LOOSE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
    r"(Z|[+-]\d{2}:\d{2})?)?$"
)

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_DMY = re.compile(
    r"\b(?P<day>\d{1,2})[\s_./-]+(?P<month>[A-Za-z]{3,9}|\d{1,2})[\s_./-]+(?P<year>\d{4})\b"
)
_YMD = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b")
_MDY_NAMED = re.compile(
    r"\b(?P<month>[A-Za-z]{3,9})[\s_.-]+(?P<day>\d{1,2}),?[\s_.-]+(?P<year>\d{4})\b"
)


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(tz=UTC)


def to_iso_utc(moment: _dt.datetime) -> str:
    """Render a datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utcnow_iso() -> str:
    return to_iso_utc(utcnow())


def parse_iso(value: str) -> _dt.datetime:
    """Parse an ISO 8601 string. A bare date becomes midnight UTC."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = _dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def hours_between(earlier: str, later: str) -> float:
    return (parse_iso(later) - parse_iso(earlier)).total_seconds() / 3600.0


def parse_stated_date(text: str | None) -> str | None:
    """Extract a *source-stated* date from free text and return it as ``YYYY-MM-DD``.

    Returns ``None`` when the text states no parseable date. The caller must not
    substitute the fetch date: an unstated publication date stays null (§2.4).
    """
    if not text:
        return None
    candidate = text.strip()
    for pattern in (_YMD, _DMY, _MDY_NAMED):
        match = pattern.search(candidate)
        if not match:
            continue
        raw_month = match.group("month")
        if raw_month.isdigit():
            month = int(raw_month)
        else:
            month = MONTHS.get(raw_month.lower(), 0)
        if not 1 <= month <= 12:
            continue
        try:
            day = int(match.group("day"))
            year = int(match.group("year"))
            return _dt.date(year, month, day).isoformat()
        except ValueError:
            continue
    return None
