"""
Stage 1: Sessions and Availability.

Builds the list of sessions for the week and determines which staff
members are available for each session, including:
- recurring days off
- weekly exceptions (days off, late starts, early finishes)
- fifth-day detection per staff member
- Rajat Monday special rule
- Nav fixed hours (coordinator — never changes)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Optional

from roster.config.schema import AppConfig
from roster.domain.models import DayPart, Role, Session, StaffMember

MONDAY    = 0
WEDNESDAY = 2
SATURDAY  = 5

_MORNING_HOURS   = 5.0
_AFTERNOON_HOURS = 4.0


@dataclass
class WeeklyInput:
    """Weekly exceptions supplied by the manager (or via AI accommodation)."""
    days_off:       list = field(default_factory=list)   # [(staff_id, date)]
    late_starts:    list = field(default_factory=list)   # [(staff_id, date, time)]
    early_finishes: list = field(default_factory=list)   # [(staff_id, date, time)]
    notes:          list = field(default_factory=list)

    def is_off(self, staff_id: str, d: date) -> bool:
        return any(sid == staff_id and dt == d for sid, dt in self.days_off)

    def late_start(self, staff_id: str, d: date) -> Optional[time]:
        for sid, dt, t in self.late_starts:
            if sid == staff_id and dt == d:
                return t
        return None

    def early_finish(self, staff_id: str, d: date) -> Optional[time]:
        for sid, dt, t in self.early_finishes:
            if sid == staff_id and dt == d:
                return t
        return None


@dataclass
class Availability:
    available:       bool
    available_hours: float = 0.0
    is_fifth_day:    bool  = False    # day 5 of this staff member's working week
    reason:          str   = ""


def build_sessions(cfg: AppConfig, week_start: date, week_end: date) -> list[Session]:
    sessions = []
    current = week_start
    while current <= week_end:
        sessions.append(Session(date=current, daypart=DayPart.MORNING))
        sessions.append(Session(date=current, daypart=DayPart.AFTERNOON))
        current += timedelta(days=1)
    return sessions


def _is_recurring_off(staff: StaffMember, d: date) -> bool:
    return d.weekday() in (staff.recurring_days_off or [])


def _session_hours(daypart: DayPart) -> float:
    return _MORNING_HOURS if daypart == DayPart.MORNING else _AFTERNOON_HOURS


def availability_matrix(
    cfg: AppConfig,
    sessions: list[Session],
    weekly: WeeklyInput,
) -> dict[tuple[str, str], Availability]:
    """
    Returns {(staff_id, session_key): Availability} for every
    active staff member across every session.
    """
    matrix: dict[tuple, Availability] = {}

    # Track days worked per staff member to detect their 5th day
    # We process in chronological order (sessions are already ordered).
    days_worked: dict[str, set] = {s.staff_id: set() for s in cfg.staff if s.active}

    # Group sessions by date for ordered processing
    from itertools import groupby
    sessions_by_date: dict[date, list[Session]] = {}
    for s in sessions:
        sessions_by_date.setdefault(s.date, []).append(s)

    rajat_rule = cfg.rules.rajat_monday_rule
    likhitha_id = rajat_rule.avoid_if_available if rajat_rule else None

    for d, day_sessions in sorted(sessions_by_date.items()):
        weekday = d.weekday()

        # Determine if Likhitha is working today (for Rajat Monday rule)
        likhitha_available_today = False
        if likhitha_id and weekday == MONDAY:
            likhitha = next((s for s in cfg.staff if s.staff_id == likhitha_id), None)
            if likhitha and likhitha.active:
                if not _is_recurring_off(likhitha, d) and not weekly.is_off(likhitha_id, d):
                    likhitha_available_today = True

        for staff in cfg.staff:
            if not staff.active:
                continue

            sid = staff.staff_id
            days_so_far = len(days_worked[sid])
            is_fifth_day = (days_so_far >= 4)

            # ── Nav coordinator: always fixed, never changes ───────────────
            if staff.role == Role.COORDINATOR:
                for session in day_sessions:
                    is_off = _is_recurring_off(staff, d) or weekly.is_off(sid, d)
                    matrix[(sid, session.key)] = Availability(
                        available=not is_off,
                        available_hours=8.0,   # 9:30–17:30 = 8h fixed
                        is_fifth_day=False,
                        reason="fixed coordinator hours" if not is_off else "day off",
                    )
                if not _is_recurring_off(staff, d) and not weekly.is_off(sid, d):
                    days_worked[sid].add(d)
                continue

            # ── Recurring or weekly day off ───────────────────────────────
            if _is_recurring_off(staff, d) or weekly.is_off(sid, d):
                for session in day_sessions:
                    matrix[(sid, session.key)] = Availability(
                        available=False, reason="day off"
                    )
                continue

            # ── Rajat Monday: strong preference to skip if Likhitha in ───
            if sid == "A_RAJAT" and weekday == MONDAY and likhitha_available_today:
                for session in day_sessions:
                    matrix[(sid, session.key)] = Availability(
                        available=True,
                        available_hours=3.0,    # low hours = scores poorly; engine skips
                        is_fifth_day=is_fifth_day,
                        reason="Monday — Likhitha available, deprioritised",
                    )
                days_worked[sid].add(d)
                continue

            # ── Determine effective daily cap ─────────────────────────────
            daily_cap = staff.max_daily_hours

            # Rajat Monday hard cap (when Likhitha NOT available)
            if sid == "A_RAJAT" and weekday == MONDAY:
                daily_cap = staff.monday_cap_hours or 6.0

            # Fifth-day cap
            fifth_day_cap = cfg.rules.shift_shape.fifth_day_cap  # 6h
            if is_fifth_day:
                daily_cap = min(daily_cap, fifth_day_cap)

            # Late start / early finish adjustments
            late  = weekly.late_start(sid, d)
            early = weekly.early_finish(sid, d)
            if late or early:
                daily_cap = min(daily_cap, daily_cap * 0.6)  # rough reduction

            days_worked[sid].add(d)

            for session in day_sessions:
                session_h = _session_hours(session.daypart)
                avail_h = min(session_h, daily_cap)
                matrix[(sid, session.key)] = Availability(
                    available=avail_h > 0,
                    available_hours=avail_h,
                    is_fifth_day=is_fifth_day,
                    reason="available",
                )

    return matrix
