"""
Stage 4 of the engine: Assignment.

Order of assignment per dentist slot:
  1. Fixed assistants (hard rule) — assigned if available, else fall back + flag
  2. Remaining slots filled by scoring
The required count = max(procedure-based count, number of fixed assistants).
"""
from __future__ import annotations
from dataclasses import dataclass, field

from roster.config.schema import AppConfig
from roster.domain.models import Assignment, Role, Session, StaffMember
from roster.engine.availability import Availability, WeeklyInput
from roster.engine.demand import SessionDemand
from roster.engine.scoring import score_candidate


@dataclass
class Vacancy:
    session_key:        str
    serves_provider_id: int
    reason:             str


@dataclass
class AssignResult:
    assignments:   list[Assignment]   = field(default_factory=list)
    vacancies:     list[Vacancy]      = field(default_factory=list)
    running_hours: dict[str, float]   = field(default_factory=dict)


def assign(
    cfg: AppConfig,
    sessions: list[Session],
    demand: dict[str, SessionDemand],
    av_matrix: dict[tuple[str, str], Availability],
    weekly: WeeklyInput | None = None,
    preassigned: list[Assignment] | None = None,
) -> AssignResult:
    weekly = weekly or WeeklyInput()
    result = AssignResult()

    for a in (preassigned or []):
        result.running_hours[a.staff_id] = result.running_hours.get(a.staff_id, 0.0) + a.hours
        result.assignments.append(a)

    dentist_assistant_pairing: dict[int, str] = {}
    assistants      = cfg.staff_by_role(Role.ASSISTANT)
    dentist_by_prov = cfg.dentist_by_provider_id()
    hyg_by_prov     = cfg.hygienist_by_provider_id()
    staff_by_id     = cfg.staff_by_id()
    session_defs    = {sd.daypart: sd for sd in cfg.clinic.sessions}

    def _is_free(staff_id, key):
        """Available this session and not already assigned to anything."""
        av = av_matrix.get((staff_id, key))
        if not av or not av.available:
            return None
        if any(a.session_key == key and a.staff_id == staff_id for a in result.assignments):
            return None
        return av

    for session in sessions:
        key = session.key
        d = demand.get(key)
        if not d or d.appointment_count == 0:
            continue
        sd = session_defs[session.daypart]
        session_hours = sd.hours

        # ── Dentists ──
        for prov_id in d.active_dentist_provider_ids:
            dentist = dentist_by_prov.get(prov_id)
            if not dentist:
                continue
            if any(a.session_key == key and a.staff_id == dentist.staff_id for a in result.assignments):
                continue
            result.assignments.append(Assignment(
                session_key=key, staff_id=dentist.staff_id, staff_name=dentist.name,
                role=Role.DENTIST, hours=session_hours,
                reasons=["active in Open Dental this session"],
            ))
            result.running_hours[dentist.staff_id] = result.running_hours.get(dentist.staff_id, 0.0) + session_hours

        # ── Hygienists ──
        for prov_id in d.hygienist_provider_ids:
            hyg = hyg_by_prov.get(prov_id)
            if not hyg:
                continue
            if any(a.session_key == key and a.staff_id == hyg.staff_id for a in result.assignments):
                continue
            result.assignments.append(Assignment(
                session_key=key, staff_id=hyg.staff_id, staff_name=hyg.name,
                role=Role.HYGIENIST, hours=session_hours,
                reasons=["active in Open Dental this session"],
            ))
            result.running_hours[hyg.staff_id] = result.running_hours.get(hyg.staff_id, 0.0) + session_hours

        # ── Assistants ──
        for prov_id in sorted(d.active_dentist_provider_ids):
            dentist     = dentist_by_prov.get(prov_id)
            dentist_sid = dentist.staff_id if dentist else None
            dentist_name = dentist.name if dentist else f"Provider {prov_id}"

            fixed      = cfg.rules.fixed_assistants.get(dentist_sid, []) if dentist_sid else []
            proc_count = d.assistant_count_by_provider.get(prov_id, cfg.clinic.assistants_per_dentist)
            per_dentist_count = cfg.rules.assistant_count_by_dentist.get(dentist_sid, 0)
            count = max(proc_count, len(fixed), per_dentist_count)
            extra_needs_skill = d.extra_needs_skill_by_provider.get(prov_id, False)

            already_serving = [a for a in result.assignments
                               if a.session_key == key and a.role == Role.ASSISTANT
                               and a.serves_provider_id == prov_id]
            already_ids = {a.staff_id for a in already_serving}
            slots_filled = len(already_serving)

            # ── Step 1: fixed assistants ──
            for fid in fixed:
                if slots_filled >= count:
                    break
                if fid in already_ids:
                    continue
                fstaff = staff_by_id.get(fid)
                if not fstaff:
                    continue
                av = _is_free(fid, key)
                if av is None:
                    continue  # unavailable — warnings stage flags this gap via vacancy below
                is_primary = (slots_filled == 0)
                result.assignments.append(Assignment(
                    session_key=key, staff_id=fid, staff_name=fstaff.name,
                    role=Role.ASSISTANT, hours=min(session_hours, av.available_hours),
                    reasons=[f"fixed assistant for {dentist_name}"],
                    serves_provider_id=prov_id,
                    support_role="chairside" if is_primary else "prep",
                ))
                result.running_hours[fid] = result.running_hours.get(fid, 0.0) + session_hours
                if is_primary:
                    dentist_assistant_pairing[prov_id] = fid
                slots_filled += 1
                already_ids.add(fid)

            # ── Step 2: fill remaining slots by scoring ──
            for slot in range(slots_filled, count):
                is_primary = (slot == 0)
                skill_override = None if (is_primary or extra_needs_skill) else set()

                candidates = []
                for asst in assistants:
                    av = _is_free(asst.staff_id, key)
                    if av is None:
                        continue
                    projected = result.running_hours.get(asst.staff_id, 0.0) + session_hours
                    if not cfg.rules.allow_overtime and projected > asst.max_weekly_hours:
                        continue
                    sc = score_candidate(asst, av, d, prov_id, cfg,
                                         result.running_hours, dentist_assistant_pairing,
                                         required_skills_override=skill_override)
                    candidates.append((sc, asst, av))

                if not candidates:
                    role_note = "" if is_primary else " (prep role)"
                    result.vacancies.append(Vacancy(
                        session_key=key, serves_provider_id=prov_id,
                        reason=f"no available assistant{role_note}",
                    ))
                    continue

                candidates.sort(key=lambda x: x[0].total, reverse=True)
                best_score, best_asst, best_av = candidates[0]
                result.assignments.append(Assignment(
                    session_key=key, staff_id=best_asst.staff_id, staff_name=best_asst.name,
                    role=Role.ASSISTANT, hours=min(session_hours, best_av.available_hours),
                    reasons=best_score.reasons, serves_provider_id=prov_id,
                    support_role="chairside" if is_primary else "prep",
                ))
                result.running_hours[best_asst.staff_id] = result.running_hours.get(best_asst.staff_id, 0.0) + session_hours
                if is_primary:
                    dentist_assistant_pairing[prov_id] = best_asst.staff_id

    return result
