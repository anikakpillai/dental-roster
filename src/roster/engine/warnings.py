"""
Stage 5 of the engine: Warnings.

Scans a completed roster for issues the manager should review.
Each warning has a severity:
  CRITICAL — must be addressed (e.g. a booked dentist with no assistant)
  WARNING  — should be reviewed (e.g. skill mismatch, overtime risk)
  INFO     — worth noting       (e.g. an unusually busy session)
"""
from __future__ import annotations

from roster.config.schema import AppConfig
from roster.domain.models import Severity, Warning, Session
from roster.engine.availability import Availability, WeeklyInput
from roster.engine.demand import SessionDemand
from roster.engine.assigner import AssignResult

# A session with more than this many assistant-minutes of demand is "high demand"
HIGH_DEMAND_MINUTES = 240


def generate_warnings(
    cfg: AppConfig,
    sessions: list[Session],
    demand: dict[str, SessionDemand],
    av_matrix: dict[tuple[str, str], Availability],
    result: AssignResult,
    weekly: WeeklyInput,
) -> list[Warning]:
    warnings: list[Warning] = []
    dentist_by_prov   = cfg.dentist_by_provider_id()
    hygienist_by_prov = cfg.hygienist_by_provider_id()
    staff_by_id       = cfg.staff_by_id()

    # ── 1. UNDERSTAFFED — a booked dentist with no assistant ──
    for v in result.vacancies:
        dentist = dentist_by_prov.get(v.serves_provider_id)
        name = dentist.name if dentist else f"Provider {v.serves_provider_id}"
        warnings.append(Warning(
            session_key=v.session_key,
            severity=Severity.CRITICAL,
            warning_type="understaffed",
            message=f"{name} has appointments but no assistant could be assigned ({v.reason}).",
        ))

    # ── 2. SKILL_MISMATCH — assigned assistant lacks a required skill ──
    for a in result.assignments:
        if a.serves_provider_id is None:
            continue  # only assistants serve a provider
        d = demand.get(a.session_key)
        if not d:
            continue
        required = d.skills_by_provider.get(a.serves_provider_id, set())
        if not required:
            continue
        assistant = staff_by_id.get(a.staff_id)
        if not assistant:
            continue
        missing = required - assistant.skills
        if missing:
            dentist = dentist_by_prov.get(a.serves_provider_id)
            dname = dentist.name if dentist else f"Provider {a.serves_provider_id}"
            warnings.append(Warning(
                session_key=a.session_key,
                severity=Severity.WARNING,
                warning_type="skill_mismatch",
                staff_id=a.staff_id,
                message=f"{a.staff_name} is assisting {dname} but lacks required skill(s): {', '.join(sorted(missing))}.",
            ))

    # ── 3 & 4. OVERTIME_RISK / MAX_HOURS_EXCEEDED ──
    for staff_id, hours in result.running_hours.items():
        staff = staff_by_id.get(staff_id)
        if not staff:
            continue
        if hours > staff.max_weekly_hours:
            warnings.append(Warning(
                session_key="",  # week-level, not tied to one session
                severity=Severity.CRITICAL,
                warning_type="max_hours_exceeded",
                staff_id=staff_id,
                message=f"{staff.name} is scheduled {hours}h — over their max of {staff.max_weekly_hours}h.",
            ))
        elif hours > staff.overtime_threshold:
            warnings.append(Warning(
                session_key="",
                severity=Severity.WARNING,
                warning_type="overtime_risk",
                staff_id=staff_id,
                message=f"{staff.name} is at {hours}h — into overtime (threshold {staff.overtime_threshold}h).",
            ))

    # ── 5. MISSING_OD_DATA — a provider in OD isn't in our staff config ──
    known_provs = set(dentist_by_prov) | set(hygienist_by_prov)
    seen_unknown = set()
    for key, d in demand.items():
        for prov_id in d.active_dentist_provider_ids:
            if prov_id not in known_provs and prov_id not in seen_unknown:
                seen_unknown.add(prov_id)
                warnings.append(Warning(
                    session_key=key,
                    severity=Severity.WARNING,
                    warning_type="missing_od_data",
                    message=f"Open Dental provider ID {prov_id} has appointments but isn't set up in Staff. Add them so they can be rostered.",
                ))

    # ── 6. DENTIST_OFF_BUT_BOOKED — marked off but OD shows them working ──
    for session in sessions:
        d = demand.get(session.key)
        if not d:
            continue
        for prov_id in d.active_dentist_provider_ids:
            dentist = dentist_by_prov.get(prov_id)
            if not dentist:
                continue
            if weekly.is_off(dentist.staff_id, session.date):
                warnings.append(Warning(
                    session_key=session.key,
                    severity=Severity.CRITICAL,
                    warning_type="dentist_off_but_booked",
                    staff_id=dentist.staff_id,
                    message=f"{dentist.name} is marked OFF but has appointments booked in Open Dental this session.",
                ))

    # ── 7. HIGH_DEMAND_SESSION — unusually heavy assistant load ──
    for key, d in demand.items():
        if d.assistant_minutes > HIGH_DEMAND_MINUTES:
            warnings.append(Warning(
                session_key=key,
                severity=Severity.INFO,
                warning_type="high_demand",
                message=f"Heavy session — {d.assistant_minutes} assistant-minutes across {d.appointment_count} appointments.",
            ))

    # Sort: CRITICAL first, then WARNING, then INFO
    order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    warnings.sort(key=lambda w: order.get(w.severity, 3))
    return warnings
