"""
Stage 4 of the engine: Assignment.

The final step — picks the best available assistant for each dentist
slot and produces a complete roster.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from roster.config.schema import AppConfig
from roster.domain.models import Assignment, Role, Session, StaffMember
from roster.engine.availability import Availability, WeeklyInput, availability_matrix
from roster.engine.demand import SessionDemand, build_demand
from roster.engine.scoring import score_candidate


@dataclass
class Vacancy:
    """A slot that couldn't be filled."""
    session_key:       str
    serves_provider_id: int
    reason:            str


@dataclass
class AssignResult:
    assignments: list[Assignment] = field(default_factory=list)
    vacancies:   list[Vacancy]   = field(default_factory=list)
    running_hours: dict[str, float] = field(default_factory=dict)


def assign(
    cfg: AppConfig,
    sessions: list[Session],
    demand: dict[str, SessionDemand],
    av_matrix: dict[tuple[str, str], Availability],
    weekly: WeeklyInput | None = None,
    preassigned: list[Assignment] | None = None,
) -> AssignResult:
    """
    Core assignment loop.
    Processes sessions in chronological order so running_hours
    accurately reflects fairness across the week.
    """
    weekly = weekly or WeeklyInput()
    result = AssignResult()

    # Seed running hours from any pre-assigned/locked slots
    for a in (preassigned or []):
        result.running_hours[a.staff_id] = (
            result.running_hours.get(a.staff_id, 0.0) + a.hours
        )
        result.assignments.append(a)

    # Track who's paired with which dentist this week (for continuity scoring)
    dentist_assistant_pairing: dict[int, str] = {}

    assistants = cfg.staff_by_role(Role.ASSISTANT)
    dentist_by_prov = cfg.dentist_by_provider_id()
    session_defs = {sd.daypart: sd for sd in cfg.clinic.sessions}

    for session in sessions:
        key = session.key
        d = demand.get(key)
        if not d or d.appointment_count == 0:
            continue

        # ── Assign dentists (they're present if OD has bookings) ──
        for prov_id in d.active_dentist_provider_ids:
            dentist = dentist_by_prov.get(prov_id)
            if not dentist:
                continue  # unknown provider — warning generated later
            sd = session_defs[session.daypart]
            hours = sd.hours

            # Skip if already locked/preassigned
            already = [a for a in result.assignments
                       if a.session_key == key and a.staff_id == dentist.staff_id]
            if already:
                continue

            result.assignments.append(Assignment(
                session_key=key,
                staff_id=dentist.staff_id,
                staff_name=dentist.name,
                role=Role.DENTIST,
                hours=hours,
                reasons=["active in Open Dental this session"],
            ))
            result.running_hours[dentist.staff_id] = (
                result.running_hours.get(dentist.staff_id, 0.0) + hours
            )

        # ── Assign hygienists ──
        hyg_by_prov = cfg.hygienist_by_provider_id()
        for prov_id in d.hygienist_provider_ids:
            hyg = hyg_by_prov.get(prov_id)
            if not hyg:
                continue
            sd = session_defs[session.daypart]
            already = [a for a in result.assignments
                       if a.session_key == key and a.staff_id == hyg.staff_id]
            if already:
                continue
            result.assignments.append(Assignment(
                session_key=key,
                staff_id=hyg.staff_id,
                staff_name=hyg.name,
                role=Role.HYGIENIST,
                hours=sd.hours,
                reasons=["active in Open Dental this session"],
            ))
            result.running_hours[hyg.staff_id] = (
                result.running_hours.get(hyg.staff_id, 0.0) + sd.hours
            )

        # ── Assign assistants — one per active dentist ──
        for prov_id in sorted(d.active_dentist_provider_ids):
            # Check if already locked
            locked = [a for a in result.assignments
                      if a.session_key == key
                      and a.role == Role.ASSISTANT
                      and a.serves_provider_id == prov_id]
            if locked:
                continue

            sd = session_defs[session.daypart]
            session_hours = sd.hours

            # Score all available assistants
            candidates = []
            for asst in assistants:
                av = av_matrix.get((asst.staff_id, key))
                if not av or not av.available:
                    continue

                # Skip if already assigned elsewhere this session
                in_use = any(
                    a.session_key == key and a.staff_id == asst.staff_id
                    for a in result.assignments
                )
                if in_use:
                    continue

                # Skip if would exceed hours cap (when overtime disabled)
                projected = result.running_hours.get(asst.staff_id, 0.0) + session_hours
                if not cfg.rules.allow_overtime and projected > asst.max_weekly_hours:
                    continue

                sc = score_candidate(
                    asst, av, d, prov_id, cfg,
                    result.running_hours, dentist_assistant_pairing
                )
                candidates.append((sc, asst, av))

            if not candidates:
                result.vacancies.append(Vacancy(
                    session_key=key,
                    serves_provider_id=prov_id,
                    reason="no available assistant found",
                ))
                continue

            # Pick highest scorer
            candidates.sort(key=lambda x: x[0].total, reverse=True)
            best_score, best_asst, best_av = candidates[0]

            result.assignments.append(Assignment(
                session_key=key,
                staff_id=best_asst.staff_id,
                staff_name=best_asst.name,
                role=Role.ASSISTANT,
                hours=min(session_hours, best_av.available_hours),
                reasons=best_score.reasons,
                serves_provider_id=prov_id,
            ))
            result.running_hours[best_asst.staff_id] = (
                result.running_hours.get(best_asst.staff_id, 0.0) + session_hours
            )
            dentist_assistant_pairing[prov_id] = best_asst.staff_id

    return result
