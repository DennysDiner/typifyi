"""Replays every recorded fixture under tests/fixtures/recorded/<authority>/ through its adapter and checks
the parse still matches expected.json. Empty until `rti fixtures record` has been run with network access."""
import json
from pathlib import Path

import pytest

from rti_tracker.adapters.base import get_adapter

REC = Path(__file__).parent / "fixtures" / "recorded"
CASES = sorted(p for p in REC.iterdir() if (p / "meta.json").exists()) if REC.exists() else []


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_recorded_fixture(case: Path):
    meta = json.loads((case / "meta.json").read_text())
    expected = json.loads((case / "expected.json").read_text())
    items = get_adapter(meta["adapter"]).parse((case / "listing.body").read_bytes(), meta["final_url"], meta.get("config") or {})
    assert len(items) == len(expected) > 0
    assert {i.external_key for i in items} == {e["external_key"] for e in expected}
