"""
The public interface to the engine.

One function — build_roster() — runs all 4 stages in order and returns
a complete Roster object. The API and frontend only ever call this.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date

from roster.config.schema import AppConfig
from roster.db.queries import get_week_appointments
from roster.domain.models import Assignment, Role, StaffMember
from roster.engine.assigner import AssignResult, Vacancy, assign
from roster.engine.availability import WeeklyInput, availability_matrix, build_sessions
from roster.engine.demand import SessionDemand, build_demand
from roster.engine.warnings import generate_warnings


@dataclass
class StaffHours:
    staff_id:       str
    staff_name:     str
    role:           Role
    total_hours:    float
    max_hours:      float
    overtime_hours: float
    cost:           float


@dataclass
class Roster:
    week_start:  date
    week_end:    date
    assignments: list[Assignment]
    vacancies:   list[Vacancy]
    hours:       list[StaffHours]
    warnings:    list = field(default_factory=list)
    notes:       list[str] = field(default_factory=list)

    # ── Convenience helpers ──
    def assignments_for(self, session_key: str) -> list[Assignment]:
        return [a for a in self.assignments if a.session_key == session_key]

    def by_role(self, role: Role) -> list[Assignment]:
        return [a for a in self.assignments if a.role == role]

    @property
    def total_cost(self) -> float:
        return round(sum(h.cost for h in self.hours), 2)

    @property
    def total_overtime_hours(self) -> float:
        return round(sum(h.overtime_hours for h in self.hours), 2)

    @property
    def vacancy_count(self) -> int:
        return len(self.vacancies)

    def summary(self) -> dict:
        return {
            "week_start":       self.week_start.isoformat(),
            "week_end":         self.week_end.isoformat(),
            "total_assignments": len(self.assignments),
            "vacancies":        self.vacancy_count,
            "total_cost":       self.total_cost,
            "overtime_hours":   self.total_overtime_hours,
        }


def _compute_hours(
    staff: StaffMember,
    running_hours: dict[str, float],
    days_worked: int = 0,
) -> StaffHours:
    base   = running_hours.get(staff.staff_id, 0.0)
    buffer = round((staff.arrival_buffer_min / 60.0) * days_worked, 2)
    total  = round(base + buffer, 2)
    overtime = max(0.0, total - staff.overtime_threshold)
    regular  = min(total, staff.overtime_threshold)
    cost = round(regular * staff.hourly_cost + overtime * staff.hourly_cost * 1.5, 2)
    return StaffHours(
        staff_id=staff.staff_id,
        staff_name=staff.name,
        role=staff.role,
        total_hours=total,
        max_hours=staff.max_weekly_hours,
        overtime_hours=overtime,
        cost=cost,
    )


def build_roster(
    cfg: AppConfig,
    week_start: date,
    week_end: date,
    weekly: WeeklyInput | None = None,
    preassigned: list[Assignment] | None = None,
) -> Roster:
    """
    Build a complete roster for the given week.

    Args:
        cfg:         Full app config (clinic + staff + rules)
        week_start:  Monday of the week
        week_end:    Saturday of the week
        weekly:      Optional weekly exceptions (days off, late starts, etc.)
        preassigned: Optional locked assignments from a previous draft
    """
    weekly = weekly or WeeklyInput()

    # ── Stage 1: Sessions + Availability ──
    sessions = build_sessions(cfg, week_start, week_end)
    av = availability_matrix(cfg, sessions, weekly)

    # ── Stage 2: Demand (from Open Dental) ──
    appointments = get_week_appointments(week_start, week_end)
    demand = build_demand(cfg, sessions, appointments)

    # ── Stage 3 + 4: Score + Assign ──
    result: AssignResult = assign(
        cfg, sessions, demand, av,
        weekly=weekly,
        preassigned=preassigned,
    )

    # ── Compute hours + cost for everyone who was assigned ──
    days_worked: dict[str, set] = {}
    for a in result.assignments:
        day = a.session_key.split("|")[0]
        days_worked.setdefault(a.staff_id, set()).add(day)

    assigned_ids = {a.staff_id for a in result.assignments}
    hours = [
        _compute_hours(s, result.running_hours, len(days_worked.get(s.staff_id, set())))
        for s in cfg.staff
        if s.staff_id in assigned_ids
    ]

    notes = list(weekly.notes)
    if result.vacancies:
        notes.append(f"{len(result.vacancies)} unfilled slot(s) — manual assignment required.")

        # ── Stage 5: Warnings ──
    warnings = generate_warnings(cfg, sessions, demand, av, result, weekly)

    return Roster(
        week_start=week_start,
        week_end=week_end,
        assignments=result.assignments,
        vacancies=result.vacancies,
        hours=hours,
        notes=notes,
        warnings=warnings,
    )
