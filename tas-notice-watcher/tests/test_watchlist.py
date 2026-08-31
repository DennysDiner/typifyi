"""Watchlist matching and near-miss logging (§4)."""

from __future__ import annotations

import pytest
from conftest import ROOT

from tnw.watchlist import Watchlist, WatchlistError

SIMPLE = {
    "settings": {"near_miss_threshold": 0.86},
    "entities": [
        {"name": "Nyrstar", "tier": 1, "patterns": ["Nyrstar", "Nyrstar Hobart"]},
        {"name": "GFG Alliance", "tier": 1, "patterns": ["Liberty Bell Bay"],
         "regexes": [r"\bGFG\b"]},
        {"name": "Group 6 Metals", "tier": 2, "patterns": ["Group 6 Metals"]},
    ],
}


@pytest.fixture
def watchlist() -> Watchlist:
    return Watchlist.from_dict(SIMPLE)


def test_matching_is_case_insensitive(watchlist):
    assert [m.entity for m in watchlist.match_text("contract with NYRSTAR pty ltd")] == ["Nyrstar"]


def test_matching_is_word_boundary_anchored(watchlist):
    assert watchlist.match_text("Nyrstarry Holdings") == []
    assert watchlist.match_text("preNyrstar") == []
    assert watchlist.match_text("(Nyrstar)") != []


def test_a_name_broken_across_lines_still_matches(watchlist):
    """PDF extraction inserts line breaks mid-name."""
    assert [m.entity for m in watchlist.match_text("the Liberty Bell\nBay smelter")] == ["GFG Alliance"]


def test_regex_patterns_are_supported(watchlist):
    assert [m.entity for m in watchlist.match_text("GFG restructure")] == ["GFG Alliance"]


def test_title_matches_are_reported_from_the_title(watchlist):
    matches = watchlist.match_item("Nyrstar land acquisition", "Group 6 Metals road works")
    assert {(m.entity, m.where) for m in matches} == {
        ("Nyrstar", "title"), ("Group 6 Metals", "body")
    }


def test_matches_are_ordered_by_tier(watchlist):
    matches = watchlist.match_item("", "Group 6 Metals and Nyrstar")
    assert [m.tier for m in matches] == [1, 2]


def test_near_misses_catch_misspellings_and_exclude_exact_matches(watchlist):
    text = "Correspondence with Libertty Bell Bay and with Nyrstar."
    matches = watchlist.match_item("", text)
    near = watchlist.near_misses(text, exclude=[m.entity for m in matches])
    assert any("Libertty Bell Bay" in n.candidate for n in near)
    assert all(n.entity != "Nyrstar" for n in near)
    assert all(0.86 <= n.ratio < 1.0 for n in near)


def test_near_misses_are_quiet_on_unrelated_text(watchlist):
    assert watchlist.near_misses("A notice about road maintenance in Sorell.") == []


def test_tier_lookup(watchlist):
    assert watchlist.tier_of("Nyrstar") == 1
    assert watchlist.tier_of("Unknown Entity") == 3


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ({"entities": []}, "entities"),
        ({"entities": [{"tier": 1, "patterns": ["x"]}]}, "name"),
        ({"entities": [{"name": "A", "tier": 9, "patterns": ["x"]}]}, "tier"),
        ({"entities": [{"name": "A", "tier": 1}]}, "at least one pattern"),
        ({"entities": [{"name": "A", "tier": 1, "regexes": ["[unclosed"]}]}, "invalid regex"),
        ({"entities": [{"name": "A", "tier": 1, "patterns": ["x"]},
                       {"name": "a", "tier": 1, "patterns": ["y"]}]}, "duplicate"),
        ({"settings": {"near_miss_threshold": 1.5},
          "entities": [{"name": "A", "tier": 1, "patterns": ["x"]}]}, "near_miss_threshold"),
    ],
)
def test_malformed_watchlists_are_rejected(payload, fragment):
    with pytest.raises(WatchlistError) as excinfo:
        Watchlist.from_dict(payload)
    assert fragment in str(excinfo.value)


def test_the_shipped_watchlist_loads_and_matches():
    watchlist = Watchlist.load(ROOT / "watchlist.yml")
    assert len(watchlist.entities) >= 8
    names = {
        m.entity
        for m in watchlist.match_text(
            "Notice: Nyrstar Hobart, Liberty Bell Bay and Sustainable Timber Tasmania"
        )
    }
    assert {"Nyrstar", "GFG Alliance", "Sustainable Timber Tasmania"} <= names
