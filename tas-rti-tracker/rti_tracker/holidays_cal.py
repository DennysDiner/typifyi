"""Tasmanian public-holiday calendar for working-day arithmetic.

Sources (never hand-typed into code):
  1. The `holidays` PyPI package (AU / TAS), which derives its data from the Statutory Holidays Act 2000
     (Tas). Version is recorded with every row (source = "library:holidays==<ver>"). Provides STATEWIDE
     holidays only.
  2. legal/holidays/regional.yaml — regional / part-State holidays (Royal Hobart Regatta, Recreation Day,
     show days, Launceston Cup, ...). Each entry carries a `source` URL and `verified: true|false`.
     Unverified entries are ignored by default. `rti holidays import-csv` loads a file downloaded from
     WorkSafe Tasmania's statutory holidays page and marks entries verified with that URL as source.

LEGAL_MODEL.md (working_day) records that whether regional holidays count is UNCERTAIN; the deadline
engine therefore computes under both readings and reports a range when they differ.
"""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import holidays as _holidays
import yaml

from .config import LEGAL_DIR
from .db import tx, utcnow

REGIONS = ("statewide", "south", "north", "north_west")
# Municipality -> broad region (for inheriting part-State days). Memory-derived; only used with unverified data.
MUNICIPALITY_REGION = {
    "hobart": "south", "glenorchy": "south", "clarence": "south", "kingborough": "south", "brighton": "south", "sorell": "south",
    "derwent_valley": "south", "huon_valley": "south", "tasman": "south", "glamorgan_spring_bay": "south", "central_highlands": "south",
    "southern_midlands": "south", "launceston": "north", "west_tamar": "north", "george_town": "north", "meander_valley": "north",
    "northern_midlands": "north", "dorset": "north", "break_oday": "north", "flinders": "north", "devonport": "north_west",
    "burnie": "north_west", "central_coast": "north_west", "latrobe": "north_west", "kentish": "north_west", "waratah_wynyard": "north_west",
    "circular_head": "north_west", "west_coast": "north_west", "king_island": "north_west",
}


@dataclass
class Calendar:
    statewide: dict[date, str] = field(default_factory=dict)
    regional: dict[str, dict[date, str]] = field(default_factory=dict)   # region -> {date: name}
    sources: list[str] = field(default_factory=list)

    def is_holiday(self, d: date, region: str | None = None) -> str | None:
        """`region` may be a municipality slug ("launceston") or a broad region ("north"). A municipality
        inherits its broad region's part-State days (Regatta / Recreation Day) via MUNICIPALITY_REGION."""
        if d in self.statewide:
            return self.statewide[d]
        if region and region != "statewide":
            hit = self.regional.get(region, {}).get(d)
            if hit:
                return hit
            broad = MUNICIPALITY_REGION.get(region)
            if broad:
                return self.regional.get(broad, {}).get(d)
        return None

    def is_working_day(self, d: date, region: str | None = None) -> bool:
        # LEGAL_MODEL.md working_day.excludes: saturday, sunday, statutory_holiday
        if d.weekday() >= 5:
            return False
        return self.is_holiday(d, region) is None

    def add_working_days(self, start: date, n: int, region: str | None = None) -> date:
        """Day count starts the day AFTER `start` ("not later than N working days after ...")."""
        d = start
        remaining = n
        step = 1 if n >= 0 else -1
        while remaining != 0:
            d += timedelta(days=step)
            if self.is_working_day(d, region):
                remaining -= step
        return d

    def working_days_between(self, a: date, b: date, region: str | None = None) -> int:
        """Working days strictly after a up to and including b (negative if b < a)."""
        if b < a:
            return -self.working_days_between(b, a, region)
        n, d = 0, a
        while d < b:
            d += timedelta(days=1)
            if self.is_working_day(d, region):
                n += 1
        return n


def library_holidays(years: list[int]) -> tuple[dict[date, str], str]:
    h = _holidays.country_holidays("AU", subdiv="TAS", years=years)
    return {d: n for d, n in h.items()}, f"library:holidays=={_holidays.__version__}"


def load_regional(path: Path | None = None, include_unverified: bool = False) -> tuple[dict[str, dict[date, str]], list[str]]:
    path = path or (LEGAL_DIR / "holidays" / "regional.yaml")
    out: dict[str, dict[date, str]] = {r: {} for r in REGIONS if r != "statewide"}
    out.update({m: {} for m in MUNICIPALITY_REGION})
    sources: list[str] = []
    if not path.exists():
        return out, sources
    data = yaml.safe_load(path.read_text()) or {}
    for e in data.get("holidays", []):
        if not e.get("verified") and not include_unverified:
            continue
        d = e["date"] if isinstance(e["date"], date) else date.fromisoformat(str(e["date"]))
        region = e.get("region", "statewide")
        if region == "statewide":
            continue
        out.setdefault(region, {})[d] = e["name"]
        src = e.get("source") or "unknown"
        if src not in sources:
            sources.append(src)
    return out, sources


def build_calendar(years: list[int], include_unverified_regional: bool = False) -> Calendar:
    sw, src = library_holidays(years)
    reg, rsrc = load_regional(include_unverified=include_unverified_regional)
    return Calendar(statewide=sw, regional=reg, sources=[src, *rsrc])


def sync_to_db(conn: sqlite3.Connection, years: list[int], include_unverified_regional: bool = False) -> int:
    cal = build_calendar(years, include_unverified_regional)
    now = utcnow()
    n = 0
    with tx(conn):
        for d, name in cal.statewide.items():
            conn.execute("INSERT OR IGNORE INTO holidays(date,name,region,source,retrieved_at) VALUES (?,?,?,?,?)",
                         (d.isoformat(), name, "statewide", cal.sources[0], now))
            n += 1
        for region, days in cal.regional.items():
            for d, name in days.items():
                conn.execute("INSERT OR IGNORE INTO holidays(date,name,region,source,retrieved_at) VALUES (?,?,?,?,?)",
                             (d.isoformat(), name, region, ";".join(cal.sources[1:]) or "regional.yaml", now))
                n += 1
    return n


def import_csv(path: Path, source_url: str, out_path: Path | None = None) -> int:
    """Import a CSV (date,name,region) downloaded from an official source into regional.yaml as verified."""
    out_path = out_path or (LEGAL_DIR / "holidays" / "regional.yaml")
    data = yaml.safe_load(out_path.read_text()) if out_path.exists() else {}
    data = data or {}
    entries = data.setdefault("holidays", [])
    existing = {(str(e["date"]), e["name"], e.get("region")) for e in entries}
    added = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["date"], row["name"], row.get("region", "statewide"))
            if key in existing:
                for e in entries:
                    if (str(e["date"]), e["name"], e.get("region")) == key:
                        e["verified"], e["source"], e["retrieved_at"] = True, source_url, utcnow()
                continue
            entries.append({"date": row["date"], "name": row["name"], "region": row.get("region", "statewide"),
                            "source": source_url, "verified": True, "retrieved_at": utcnow()})
            added += 1
    out_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return added
