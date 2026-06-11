"""
Stage 1 of the engine: Availability.

Answers: "For each session this week, who can work it and for how many hours?"
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, time

from roster.config.schema import AppConfig
from roster.domain.models import DayPart, Session, StaffMember


@dataclass
class Availability:
    staff_id:        str
    session_key:     str
    available:       bool
    available_hours: float
    reason:          str   # always explain why — helps with warnings later


@dataclass
class WeeklyInput:
    """
    Minimal per-week data the manager enters each Saturday.
    Everything else comes from permanent config or Open Dental.
    """
    days_off:    list[tuple[str, date]] = None    # (staff_id, date)
    late_starts: list[tuple[str, date, time]] = None  # (staff_id, date, start_time)
    early_finishes: list[tuple[str, date, time]] = None  # (staff_id, date, end_time)
    notes: list[str] = None

    def __post_init__(self):
        self.days_off = self.days_off or []
        self.late_starts = self.late_starts or []
        self.early_finishes = self.early_finishes or []
        self.notes = self.notes or []

    def is_off(self, staff_id: str, d: date) -> bool:
        return any(sid == staff_id and dt == d for sid, dt in self.days_off)

    def late_start_for(self, staff_id: str, d: date) -> time | None:
        for sid, dt, t in self.late_starts:
            if sid == staff_id and dt == d:
                return t
        return None

    def early_finish_for(self, staff_id: str, d: date) -> time | None:
        for sid, dt, t in self.early_finishes:
            if sid == staff_id and dt == d:
                return t
        return None


def build_sessions(cfg: AppConfig, week_start: date, week_end: date) -> list[Session]:
    """Generate every working session block for the week."""
    sessions = []
    current = week_start
    while current <= week_end:
        if current.weekday() in cfg.clinic.working_weekdays:
            for sd in cfg.clinic.sessions:
                sessions.append(Session(date=current, daypart=sd.daypart))
        current = current + __import__('datetime').timedelta(days=1)
    return sessions


def _hours_overlap(
    session_start: time, session_end: time,
    avail_start: time,  avail_end: time,
) -> float:
    """How many hours does [avail_start, avail_end] overlap with [session_start, session_end]?"""
    def to_min(t: time) -> int:
        return t.hour * 60 + t.minute

    start = max(to_min(session_start), to_min(avail_start))
    end   = min(to_min(session_end),   to_min(avail_end))
    return max(0.0, (end - start) / 60)


def resolve_availability(
    staff: StaffMember,
    session: Session,
    weekly: WeeklyInput,
    cfg: AppConfig,
) -> Availability:
    """Compute availability for one staff member in one session."""
    sd = cfg.session_def(session.daypart)

    # ── Hard block: day off ──
    if weekly.is_off(staff.staff_id, session.date):
        return Availability(staff.staff_id, session.key, False, 0.0, "day off")
    # ── Hard block: recurring weekly day off (permanent pattern) ──
    if session.date.weekday() in staff.recurring_days_off:
        return Availability(staff.staff_id, session.key, False, 0.0, "recurring day off")

    # ── Normal pattern gate (assistants/hygienists only) ──
    # Empty pattern = available every session (dentists)
    if staff.normal_pattern:
        weekday = session.date.weekday()
        if (weekday, session.daypart) not in staff.normal_pattern:
            return Availability(
                staff.staff_id, session.key, False, 0.0, "outside normal working pattern"
            )

    # ── Calculate available hours within the session ──
    avail_start = weekly.late_start_for(staff.staff_id, session.date) or sd.start
    avail_end   = weekly.early_finish_for(staff.staff_id, session.date) or sd.end
    hours = _hours_overlap(sd.start, sd.end, avail_start, avail_end)

    if hours <= 0:
        return Availability(staff.staff_id, session.key, False, 0.0, "late start/early finish removes session")

    reason_parts = []
    if avail_start != sd.start:
        reason_parts.append(f"late start {avail_start.strftime('%H:%M')}")
    if avail_end != sd.end:
        reason_parts.append(f"early finish {avail_end.strftime('%H:%M')}")
    reason = ", ".join(reason_parts) if reason_parts else "normal availability"

    return Availability(staff.staff_id, session.key, True, hours, reason)


def availability_matrix(
    cfg: AppConfig,
    sessions: list[Session],
    weekly: WeeklyInput,
) -> dict[tuple[str, str], Availability]:
    """
    Build the full availability matrix for the week.
    Returns a dict keyed by (staff_id, session_key).
    """
    matrix = {}
    for staff in cfg.staff:
        if not staff.active:
            continue
        for session in sessions:
            av = resolve_availability(staff, session, weekly, cfg)
            matrix[(staff.staff_id, session.key)] = av
    return matrix
