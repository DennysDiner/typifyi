"""Deadline engine driven entirely by legal/rules.yaml (see LEGAL_MODEL.md).

No statutory number lives in this file. Every computed deadline carries the rule id, the section pinpoint,
the evidence label and the `uncertain` flag from the rules file, so the UI can show
"deemed refused (s 15(…), UNCERTAIN pinpoint)" honestly.

Because LEGAL_MODEL.md marks the regional-holiday question UNCERTAIN, every deadline is computed under
two readings — statewide holidays only, and statewide + the authority's regional holidays — and reported
as a range when they differ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import LEGAL_DIR
from .holidays_cal import Calendar, build_calendar

# Event names recorded in application_events. Kept as constants so typos fail loudly.
EV_RECEIVED = "application_received"
EV_ACCEPTED = "application_accepted"
EV_FEE_WAIVER_DECIDED = "fee_waiver_decided"
EV_TRANSFERRED = "application_transferred"
EV_THIRD_PARTY_DECIDED = "third_party_consultation_decided"
EV_THIRD_PARTY_NOTIFIED = "third_party_notified"
EV_EXTENSION_AGREED = "extension_agreed"                # detail: {new_due_date}
EV_OMBUDSMAN_EXTENSION = "ombudsman_extension_granted"  # detail: {new_due_date}
EV_DECISION_NOTIFIED = "decision_notified"              # detail: {decision_maker: delegate|principal_officer|minister, outcome}
EV_INTERNAL_REVIEW_LODGED = "internal_review_lodged"
EV_INTERNAL_REVIEW_NOTIFIED = "internal_review_decision_notified"
EV_EXTERNAL_REVIEW_LODGED = "external_review_lodged"
EV_EXTERNAL_REVIEW_DECIDED = "external_review_decided"
EV_WITHDRAWN = "withdrawn"
EV_CLOSED = "closed"

ALL_EVENTS = [EV_RECEIVED, EV_ACCEPTED, EV_FEE_WAIVER_DECIDED, EV_TRANSFERRED, EV_THIRD_PARTY_DECIDED,
              EV_THIRD_PARTY_NOTIFIED, EV_EXTENSION_AGREED, EV_OMBUDSMAN_EXTENSION, EV_DECISION_NOTIFIED,
              EV_INTERNAL_REVIEW_LODGED, EV_INTERNAL_REVIEW_NOTIFIED, EV_EXTERNAL_REVIEW_LODGED,
              EV_EXTERNAL_REVIEW_DECIDED, EV_WITHDRAWN, EV_CLOSED]


@dataclass
class Rules:
    raw: dict
    by_id: dict[str, dict]

    @classmethod
    def load(cls, path: Path | None = None) -> "Rules":
        path = path or (LEGAL_DIR / "rules.yaml")
        raw = yaml.safe_load(path.read_text())
        return cls(raw=raw, by_id={r["id"]: r for r in raw.get("rules", [])})

    def rule(self, rid: str) -> dict:
        if rid not in self.by_id:
            raise KeyError(f"legal/rules.yaml has no rule {rid!r}")
        return self.by_id[rid]

    def days(self, rid: str) -> int | None:
        return self.rule(rid).get("days")

    @property
    def working_day_uncertain(self) -> bool:
        return bool(self.raw.get("working_day", {}).get("uncertain"))

    @property
    def regional_reading(self) -> str:
        return str(self.raw.get("working_day", {}).get("regional_holidays", "UNCERTAIN"))


@dataclass
class Event:
    event: str
    date: date
    detail: dict = field(default_factory=dict)


@dataclass
class Deadline:
    id: str                    # rule id
    label: str
    due: date                  # statewide reading
    due_regional: date | None  # authority-region reading (None if identical or no region)
    section: str
    evidence: str
    uncertain: bool
    pinpoint_uncertain: bool
    basis: str                 # human explanation of the arithmetic
    passed: bool = False
    alternative: dict | None = None   # e.g. {"days": 20, "due": ...} for candidate values

    @property
    def is_range(self) -> bool:
        return self.due_regional is not None and self.due_regional != self.due

    def display(self) -> str:
        s = self.due.isoformat()
        if self.is_range:
            s += f" (or {self.due_regional.isoformat()} if regional holidays count)"
        flags = []
        if self.uncertain:
            flags.append("UNCERTAIN")
        elif self.pinpoint_uncertain:
            flags.append("pinpoint UNCERTAIN")
        return f"{self.label}: {s} [{self.section}{' — ' + ', '.join(flags) if flags else ''}]"


@dataclass
class Status:
    state: str
    state_section: str
    state_note: str
    deadlines: list[Deadline]
    next_steps: list[dict]
    warnings: list[str]


class DeadlineEngine:
    def __init__(self, rules: Rules | None = None, calendar: Calendar | None = None, today: date | None = None):
        self.rules = rules or Rules.load()
        self.today = today or date.today()
        self.cal = calendar or build_calendar(list(range(self.today.year - 2, self.today.year + 3)))

    # -- helpers -----------------------------------------------------------------------------------
    def _dl(self, rid: str, label: str, start: date, region: str | None, *, days: int | None = None,
            basis: str = "") -> Deadline | None:
        r = self.rules.rule(rid)
        n = days if days is not None else r.get("days")
        if n is None:
            return None
        due = self.cal.add_working_days(start, n, None)
        due_r = self.cal.add_working_days(start, n, region) if region and region != "statewide" else None
        if due_r == due:
            due_r = None
        alt = None
        cands = [c for c in (r.get("candidate_values") or []) if c != n]
        if cands:
            alt = {"days": cands[0], "due": self.cal.add_working_days(start, cands[0], None).isoformat(), "note": "alternative value in evidence"}
        return Deadline(
            id=rid, label=label, due=due, due_regional=due_r, section=str(r.get("section", "?")),
            evidence=str(r.get("evidence", "?")), uncertain=bool(r.get("uncertain")),
            pinpoint_uncertain=bool(r.get("pinpoint_uncertain")),
            basis=basis or f"{n} working days after {start.isoformat()}",
            passed=(due_r or due) < self.today if False else due < self.today, alternative=alt,
        )

    @staticmethod
    def _last(events: list[Event], name: str) -> Event | None:
        hits = [e for e in events if e.event == name]
        return hits[-1] if hits else None

    # -- main ----------------------------------------------------------------------------------------
    def compute(self, events: list[Event], *, region: str | None = None) -> Status:
        events = sorted(events, key=lambda e: e.date)
        warnings: list[str] = []
        deadlines: list[Deadline] = []
        R = self.rules

        received = self._last(events, EV_RECEIVED)
        accepted = self._last(events, EV_ACCEPTED)
        waiver = self._last(events, EV_FEE_WAIVER_DECIDED)
        transferred = self._last(events, EV_TRANSFERRED)
        third_party = self._last(events, EV_THIRD_PARTY_DECIDED)
        tp_notified = self._last(events, EV_THIRD_PARTY_NOTIFIED)
        ext_agreed = self._last(events, EV_EXTENSION_AGREED)
        omb_ext = self._last(events, EV_OMBUDSMAN_EXTENSION)
        decision = self._last(events, EV_DECISION_NOTIFIED)
        ir_lodged = self._last(events, EV_INTERNAL_REVIEW_LODGED)
        ir_notified = self._last(events, EV_INTERNAL_REVIEW_NOTIFIED)
        er_lodged = self._last(events, EV_EXTERNAL_REVIEW_LODGED)
        er_decided = self._last(events, EV_EXTERNAL_REVIEW_DECIDED)
        withdrawn = self._last(events, EV_WITHDRAWN)
        closed = self._last(events, EV_CLOSED)

        if R.working_day_uncertain:
            warnings.append(f"Working-day definition is UNCERTAIN in LEGAL_MODEL.md ({R.raw['working_day'].get('section')}); "
                            f"regional-holiday reading: {R.regional_reading}. Deadlines shown as a range where readings differ.")
        if waiver and accepted and waiver.date > accepted.date:
            warnings.append("Fee waiver decided after the recorded acceptance date; whether acceptance is backdated to receipt is UNCERTAIN (rules.yaml acceptance).")

        # Transfer: deemed receipt (s 14) — earlier of transfer date and original + N wd
        if transferred and received:
            n = R.days("transfer_deemed_receipt")
            if n is not None:
                alt = self.cal.add_working_days(received.date, n, None)
                deemed = min(transferred.date, alt)
                r = R.rule("transfer_deemed_receipt")
                warnings.append(f"Transferred {transferred.date}: receiving body taken to have received it on {deemed} "
                                f"[{r['section']}, {r['evidence']}{', UNCERTAIN' if r.get('uncertain') else ''}]. "
                                f"Whether its decision clock runs from that date or from its own acceptance is UNCERTAIN.")
                if not accepted or accepted.date < transferred.date:
                    accepted = Event(EV_ACCEPTED, deemed, {"derived_from": "transfer_deemed_receipt"})

        # Negotiation period from receipt
        if received:
            d = self._dl("negotiation_period", "Negotiation period ends", received.date, region)
            if d:
                deadlines.append(d)

        # Decision due
        decision_due: Deadline | None = None
        if accepted:
            if omb_ext and omb_ext.detail.get("new_due_date"):
                r = R.rule("ombudsman_extension")
                nd = date.fromisoformat(str(omb_ext.detail["new_due_date"]))
                decision_due = Deadline("ombudsman_extension", "Decision due (Ombudsman-extended)", nd, None, str(r["section"]),
                                        str(r["evidence"]), bool(r.get("uncertain")), bool(r.get("pinpoint_uncertain")),
                                        f"date allowed by Ombudsman on {omb_ext.date}", passed=nd < self.today)
            elif ext_agreed and ext_agreed.detail.get("new_due_date"):
                r = R.rule("extension_by_agreement")
                nd = date.fromisoformat(str(ext_agreed.detail["new_due_date"]))
                decision_due = Deadline("extension_by_agreement", "Decision due (extended by agreement)", nd, None, str(r["section"]),
                                        str(r["evidence"]), bool(r.get("uncertain")), bool(r.get("pinpoint_uncertain")),
                                        f"date agreed with applicant on {ext_agreed.date}", passed=nd < self.today)
            elif third_party:
                decision_due = self._dl("third_party_consultation_extension", "Decision due (third-party consultation)", accepted.date, region)
            else:
                decision_due = self._dl("decision_due", "Decision due", accepted.date, region)
            if decision_due:
                deadlines.append(decision_due)
            # alternative reading recorded in rules (negotiation -> 30 wd) shown only as alternative
            if "negotiation_extended_decision_due" in R.by_id and received and not third_party:
                alt = self._dl("negotiation_extended_decision_due", "Decision due — ALTERNATIVE reading (negotiation)", accepted.date, region)
                if alt and decision_due and alt.due != decision_due.due:
                    alt.label += " (not applied automatically)"
                    deadlines.append(alt)
        if tp_notified:
            d = self._dl("third_party_response_window", "Third party response window ends", tp_notified.date, region)
            if d:
                deadlines.append(d)

        # State machine
        state, state_section, note = "lodged", "s 13", "Application lodged; not yet accepted (fee/waiver outstanding)"
        if accepted:
            state, state_section, note = "awaiting_decision", str(R.rule("decision_due")["section"]), "Accepted; decision clock running"
        deemed: Deadline | None = None
        if accepted and decision_due and not decision and decision_due.due < self.today and not withdrawn:
            r = R.rule("deemed_refusal")
            deemed = Deadline("deemed_refusal", "Deemed refusal", decision_due.due, decision_due.due_regional, str(r["section"]),
                              str(r["evidence"]), bool(r.get("uncertain")), bool(r.get("pinpoint_uncertain")),
                              f"no decision notified by {decision_due.due}", passed=True)
            deadlines.append(deemed)
            state, state_section, note = "deemed_refused", str(r["section"]), r["description"]
        if decision:
            outcome = decision.detail.get("outcome", "decided")
            state, state_section, note = f"decided_{outcome}", "s 22", f"Decision notified {decision.date} ({outcome})"
            maker = decision.detail.get("decision_maker", "delegate")
            if maker in ("minister", "principal_officer"):
                d = self._dl("external_review_window", "Ombudsman review window (no internal review for Minister/principal officer decision)", decision.date, region)
            else:
                d = self._dl("internal_review_window", "Internal review window", decision.date, region)
            if d:
                deadlines.append(d)
        if ir_lodged:
            state, state_section, note = "internal_review", str(R.rule("internal_review_decision_due")["section"]), f"Internal review lodged {ir_lodged.date}"
            d = self._dl("internal_review_decision_due", "Internal review decision due", ir_lodged.date, region)
            if d:
                deadlines.append(d)
                if not ir_notified and d.due < self.today:
                    r = R.rule("internal_review_deemed_refusal")
                    deadlines.append(Deadline("internal_review_deemed_refusal", "Internal review deemed refused", d.due, d.due_regional,
                                              str(r["section"]), str(r["evidence"]), True, True, "no internal review decision in time", passed=True))
                    state, state_section, note = "internal_review_deemed_refused", str(r["section"]), r["description"]
                    e = self._dl("external_review_after_internal_review", "Ombudsman review window (after internal review lapse)", d.due, region)
                    if e:
                        e.uncertain = True
                        e.basis += " — trigger on lapse is inferred, see rules.yaml"
                        deadlines.append(e)
        if ir_notified:
            state, state_section, note = "internal_review_decided", "s 43", f"Internal review decision notified {ir_notified.date}"
            d = self._dl("external_review_after_internal_review", "Ombudsman review window", ir_notified.date, region)
            if d:
                deadlines.append(d)
        if er_lodged:
            state, state_section, note = "external_review", str(R.rule("ombudsman_decision")["section"]), f"Ombudsman review lodged {er_lodged.date}; no fixed statutory period"
        if er_decided:
            state, state_section, note = "external_review_decided", "s 47", f"Ombudsman decision {er_decided.date}"
        if withdrawn:
            state, state_section, note = "withdrawn", "-", f"Withdrawn {withdrawn.date}"
        if closed:
            state, state_section, note = "closed", "-", f"Closed {closed.date}"

        for d in deadlines:
            d.passed = d.due < self.today
        next_steps = self._next_steps(state, deadlines, deemed, decision)
        return Status(state=state, state_section=state_section, state_note=note, deadlines=deadlines,
                      next_steps=next_steps, warnings=warnings)

    def _next_steps(self, state: str, deadlines: list[Deadline], deemed: Deadline | None, decision: Event | None) -> list[dict]:
        R = self.rules
        steps: list[dict] = []
        by_id = {d.id: d for d in deadlines}

        def add(title: str, rid: str | None, deadline: Deadline | None = None, note: str = "") -> None:
            r = R.rule(rid) if rid else {}
            steps.append({
                "title": title, "section": r.get("section", "-") if rid else "-", "evidence": r.get("evidence"),
                "uncertain": bool(r.get("uncertain")) if rid else False,
                "deadline": deadline.due.isoformat() if deadline else None,
                "deadline_regional": deadline.due_regional.isoformat() if deadline and deadline.due_regional else None,
                "note": note or r.get("notes", ""),
            })

        if state == "lodged":
            add("Pay the application fee or seek a waiver so the application is accepted", None, note=str(R.raw.get("acceptance", {}).get("description", "")))
            add("Respond to any negotiation/clarification request", "negotiation_period", by_id.get("negotiation_period"))
        elif state == "awaiting_decision":
            dd = by_id.get("decision_due") or by_id.get("third_party_consultation_extension") or by_id.get("extension_by_agreement") or by_id.get("ombudsman_extension")
            add("Wait for the decision; chase the authority as the due date approaches", dd.id if dd else "decision_due", dd)
            add("If asked to agree to an extension, you may decline (the authority may then seek Ombudsman time)", "extension_by_agreement")
        elif state == "deemed_refused":
            add("Apply to the Ombudsman for external review of the deemed refusal (no internal review needed)", "external_review_deemed_refusal_window",
                note="No time limit for this route was established in LEGAL_MODEL.md — treat as 'may apply now'; confirm against s 45 before relying on it.")
            add("Or keep waiting: a late decision can still issue; the deemed refusal stays available as a review ground", "deemed_refusal")
        elif state.startswith("decided"):
            maker = (decision.detail.get("decision_maker") if decision else None) or "delegate"
            if maker in ("minister", "principal_officer"):
                add("Apply to the Ombudsman for external review (decision by Minister/principal officer: internal review unavailable)", "external_review_window", by_id.get("external_review_window"))
            else:
                add("Apply for internal review (free) within the window", "internal_review_window", by_id.get("internal_review_window"))
                add("Then, if unhappy with the internal review, apply to the Ombudsman", "external_review_after_internal_review")
        elif state == "internal_review":
            add("Wait for the internal review decision", "internal_review_decision_due", by_id.get("internal_review_decision_due"))
        elif state == "internal_review_deemed_refused":
            add("Apply to the Ombudsman for external review (internal review not decided in time)", "external_review_after_internal_review", by_id.get("external_review_after_internal_review"))
        elif state == "internal_review_decided":
            add("Apply to the Ombudsman for external review within the window", "external_review_after_internal_review", by_id.get("external_review_after_internal_review"))
        elif state == "external_review":
            add("Wait for the Ombudsman; chase periodically (no statutory period)", "ombudsman_decision")
        elif state == "external_review_decided":
            add("Consider further avenues (judicial review) — LEGAL_MODEL.md marks this memory-only; get advice", None)
        return steps


def upcoming_alert_offsets(engine: DeadlineEngine, due: date, offsets=(5, 2, 0), region: str | None = None) -> dict[int, date]:
    """Dates on which alerts fire: N working days before `due`."""
    return {n: engine.cal.add_working_days(due, -n, region) for n in offsets}
