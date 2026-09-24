"""Worked examples derived from legal/rules.yaml (LEGAL_MODEL.md). Each test names the rule id and
section it exercises; the numbers are read from the rules file, never hard-coded here."""
from datetime import date

import pytest

from rti_tracker.deadlines import (EV_ACCEPTED, EV_DECISION_NOTIFIED, EV_EXTENSION_AGREED, EV_INTERNAL_REVIEW_LODGED,
                                   EV_INTERNAL_REVIEW_NOTIFIED, EV_RECEIVED, EV_THIRD_PARTY_DECIDED, EV_TRANSFERRED,
                                   DeadlineEngine, Event, Rules)
from rti_tracker.holidays_cal import Calendar, library_holidays


@pytest.fixture
def rules():
    return Rules.load()


@pytest.fixture
def cal():
    sw, _ = library_holidays([2026, 2027])
    # synthetic regional day inside the test windows (regional.yaml entries are unverified and ignored by default)
    return Calendar(statewide=sw, regional={"south": {date(2026, 2, 9): "Regatta (test)"}, "north": {date(2026, 11, 2): "Recreation Day (test)"}}, sources=["test"])


def eng(cal, today):
    return DeadlineEngine(rules=Rules.load(), calendar=cal, today=today)


def _count_wd(cal, start, end, region=None):
    return cal.working_days_between(start, end, region)


def test_decision_due_20wd_s15_1(rules, cal):
    """decision_due: accepted Mon 2026-08-03; N working days later per rules.yaml (no holidays in window)."""
    n = rules.days("decision_due")
    st = eng(cal, date(2026, 8, 5)).compute([Event(EV_RECEIVED, date(2026, 8, 3)), Event(EV_ACCEPTED, date(2026, 8, 3))])
    dd = next(d for d in st.deadlines if d.id == "decision_due")
    assert _count_wd(cal, date(2026, 8, 3), dd.due) == n
    assert dd.due == date(2026, 8, 31)  # 20 wd after Mon 3 Aug 2026 with no holidays = Mon 31 Aug
    assert dd.section == rules.rule("decision_due")["section"]
    assert st.state == "awaiting_decision"


def test_decision_due_skips_statutory_holiday(rules, cal):
    """Accepted 2026-03-02 (Mon); Eight Hours Day 2026-03-09 is a statewide holiday and must not count."""
    n = rules.days("decision_due")
    st = eng(cal, date(2026, 3, 3)).compute([Event(EV_ACCEPTED, date(2026, 3, 2))])
    dd = next(d for d in st.deadlines if d.id == "decision_due")
    assert _count_wd(cal, date(2026, 3, 2), dd.due) == n
    assert dd.due == date(2026, 3, 31)  # 20 wd = 4 weeks + 1 day for the holiday
    assert not dd.is_range  # no regional day in window for a south authority? (Regatta 9 Feb is outside)


def test_regional_holiday_produces_range_when_uncertain(rules, cal):
    """Accepted 2026-01-27; Regatta Day (south, synthetic) 2026-02-09 falls inside the window. Because
    LEGAL_MODEL.md marks regional holidays UNCERTAIN, the engine must report both readings."""
    st = eng(cal, date(2026, 1, 28)).compute([Event(EV_ACCEPTED, date(2026, 1, 27))], region="south")
    dd = next(d for d in st.deadlines if d.id == "decision_due")
    assert dd.is_range and dd.due_regional == cal.add_working_days(dd.due, 1, None)
    assert any("UNCERTAIN" in w for w in st.warnings)
    # a north authority is unaffected by a south regional day
    st2 = eng(cal, date(2026, 1, 28)).compute([Event(EV_ACCEPTED, date(2026, 1, 27))], region="north")
    assert not next(d for d in st2.deadlines if d.id == "decision_due").is_range


def test_third_party_consultation_extends_to_40(rules, cal):
    total = rules.days("third_party_consultation_extension")
    st = eng(cal, date(2026, 8, 20)).compute([Event(EV_ACCEPTED, date(2026, 8, 3)), Event(EV_THIRD_PARTY_DECIDED, date(2026, 8, 10))])
    dd = next(d for d in st.deadlines if d.id == "third_party_consultation_extension")
    assert _count_wd(cal, date(2026, 8, 3), dd.due) == total
    assert dd.due == date(2026, 9, 28)
    assert not any(d.id == "decision_due" for d in st.deadlines)


def test_extension_by_agreement_overrides(rules, cal):
    st = eng(cal, date(2026, 8, 20)).compute([Event(EV_ACCEPTED, date(2026, 8, 3)), Event(EV_EXTENSION_AGREED, date(2026, 8, 25), {"new_due_date": "2026-10-09"})])
    dd = next(d for d in st.deadlines if d.id == "extension_by_agreement")
    assert dd.due == date(2026, 10, 9) and dd.section == rules.rule("extension_by_agreement")["section"]


def test_deemed_refusal_after_due_passes(rules, cal):
    st = eng(cal, date(2026, 9, 24)).compute([Event(EV_ACCEPTED, date(2026, 8, 3))])
    assert st.state == "deemed_refused"
    dr = next(d for d in st.deadlines if d.id == "deemed_refusal")
    assert dr.due == date(2026, 8, 31) and dr.pinpoint_uncertain  # pinpoint flagged per rules.yaml
    assert rules.rule("deemed_refusal")["section"] in st.state_section
    titles = " ".join(s["title"] for s in st.next_steps)
    assert "Ombudsman" in titles


def test_no_deemed_refusal_before_due(cal):
    st = eng(cal, date(2026, 8, 31)).compute([Event(EV_ACCEPTED, date(2026, 8, 3))])
    assert st.state == "awaiting_decision"


def test_internal_review_window_s43(rules, cal):
    n = rules.days("internal_review_window")
    st = eng(cal, date(2026, 9, 1)).compute([Event(EV_ACCEPTED, date(2026, 8, 3)), Event(EV_DECISION_NOTIFIED, date(2026, 8, 28), {"decision_maker": "delegate", "outcome": "partial"})])
    assert st.state == "decided_partial"
    ir = next(d for d in st.deadlines if d.id == "internal_review_window")
    assert _count_wd(cal, date(2026, 8, 28), ir.due) == n and ir.due == date(2026, 9, 25)
    assert any("internal review" in s["title"].lower() for s in st.next_steps)


def test_minister_decision_goes_straight_to_ombudsman(rules, cal):
    st = eng(cal, date(2026, 9, 1)).compute([Event(EV_ACCEPTED, date(2026, 8, 3)), Event(EV_DECISION_NOTIFIED, date(2026, 8, 28), {"decision_maker": "minister", "outcome": "refused"})])
    ids = {d.id for d in st.deadlines}
    assert "external_review_window" in ids and "internal_review_window" not in ids
    ex = next(d for d in st.deadlines if d.id == "external_review_window")
    assert ex.uncertain == bool(rules.rule("external_review_window")["uncertain"])


def test_internal_review_decision_due_with_alternative(rules, cal):
    r = rules.rule("internal_review_decision_due")
    st = eng(cal, date(2026, 9, 10)).compute([Event(EV_ACCEPTED, date(2026, 8, 3)), Event(EV_DECISION_NOTIFIED, date(2026, 8, 28)), Event(EV_INTERNAL_REVIEW_LODGED, date(2026, 9, 7))])
    d = next(x for x in st.deadlines if x.id == "internal_review_decision_due")
    assert _count_wd(cal, date(2026, 9, 7), d.due) == r["days"]
    if r.get("candidate_values"):
        alt = [c for c in r["candidate_values"] if c != r["days"]]
        assert d.alternative and d.alternative["days"] == alt[0]
    assert d.uncertain == bool(r["uncertain"])


def test_internal_review_lapse_then_ombudsman_window(rules, cal):
    st = eng(cal, date(2026, 11, 2)).compute([Event(EV_ACCEPTED, date(2026, 8, 3)), Event(EV_DECISION_NOTIFIED, date(2026, 8, 28)), Event(EV_INTERNAL_REVIEW_LODGED, date(2026, 9, 7))])
    assert st.state == "internal_review_deemed_refused"
    ex = next(d for d in st.deadlines if d.id == "external_review_after_internal_review")
    assert ex.uncertain  # inferred trigger flagged


def test_external_review_after_internal_review_s44(rules, cal):
    n = rules.days("external_review_after_internal_review")
    st = eng(cal, date(2026, 10, 1)).compute([Event(EV_ACCEPTED, date(2026, 8, 3)), Event(EV_DECISION_NOTIFIED, date(2026, 8, 28)), Event(EV_INTERNAL_REVIEW_LODGED, date(2026, 9, 7)), Event(EV_INTERNAL_REVIEW_NOTIFIED, date(2026, 9, 28))])
    assert st.state == "internal_review_decided"
    d = next(x for x in st.deadlines if x.id == "external_review_after_internal_review")
    assert _count_wd(cal, date(2026, 9, 28), d.due) == n


def test_transfer_deemed_receipt_s14(rules, cal):
    n = rules.days("transfer_deemed_receipt")
    # original received Mon 3 Aug; transferred 2026-08-20 (later than 10 wd = 17 Aug) -> deemed 17 Aug
    st = eng(cal, date(2026, 8, 21)).compute([Event(EV_RECEIVED, date(2026, 8, 3)), Event(EV_TRANSFERRED, date(2026, 8, 20))])
    assert any("taken to have received" in w for w in st.warnings)
    dd = next(d for d in st.deadlines if d.id == "decision_due")
    assert dd.due == cal.add_working_days(cal.add_working_days(date(2026, 8, 3), n), rules.days("decision_due"))


def test_negotiation_period_s13_7(rules, cal):
    n = rules.days("negotiation_period")
    st = eng(cal, date(2026, 8, 4)).compute([Event(EV_RECEIVED, date(2026, 8, 3))])
    d = next(x for x in st.deadlines if x.id == "negotiation_period")
    assert _count_wd(cal, date(2026, 8, 3), d.due) == n


def test_every_rule_has_citation_and_evidence(rules):
    for rid, r in rules.by_id.items():
        assert r.get("section"), rid
        assert r.get("evidence") in ("snippet_verified", "inferred", "memory"), rid
        assert "uncertain" in r, rid
    assert rules.raw["working_day"]["section"]


def test_null_days_rules_never_invent_dates(rules, cal):
    """Rules with days: null (e.g. external_review_deemed_refusal_window) must not yield a deadline."""
    st = eng(cal, date(2026, 9, 24)).compute([Event(EV_ACCEPTED, date(2026, 8, 3))])
    assert not any(d.id == "external_review_deemed_refusal_window" for d in st.deadlines)
    step = next(s for s in st.next_steps if "Ombudsman" in s["title"])
    assert step["deadline"] is None
