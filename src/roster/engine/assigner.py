"""
Stage 4: Assignment.

Assigns assistants to dentists and front desk staff to shifts.

Assistant priority:
  1. Hard filter: projected weekly hours must stay ≤ 40h
  2. Hard filter: projected daily hours must stay ≤ daily cap
  3. Scoring: hours headroom → shift shape → preference → usual day → fairness → cost

Front desk assignment:
  - One opener + one closer per day minimum
  - Opener: preferred_role='opener' (Ziya, Simran), arrives 90min before first patient
  - Closer: preferred_role='closer' (Sravani preferred), leaves after last patient
  - 3-doctor trigger: if all 3 doctors working and only 1 front desk covers midday,
    pull in a 3rd front desk person
  - Sravani scheduled first to maximise her hours under 40h
  - Deekshi: pulled to clinical first; counted in front desk coverage on same day

Nav (coordinator): fixed 9:30–17:30, assigned automatically, never changed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date

from roster.config.schema import AppConfig
from roster.domain.models import Assignment, Role, Session, StaffMember
from roster.engine.availability import Availability, WeeklyInput
from roster.engine.demand import SessionDemand
from roster.engine.scoring import score_candidate

MONDAY = 0


@dataclass
class Vacancy:
    session_key:        str
    serves_provider_id: int
    reason:             str


@dataclass
class AssignResult:
    assignments:   list = field(default_factory=list)
    vacancies:     list = field(default_factory=list)
    running_hours: dict = field(default_factory=dict)


def assign(
    cfg:          AppConfig,
    sessions:     list,
    demand:       dict,
    av_matrix:    dict,
    weekly:       WeeklyInput | None = None,
    preassigned:  list | None = None,
) -> AssignResult:
    weekly = weekly or WeeklyInput()
    result = AssignResult()
    running_daily: dict = {}
    days_worked: dict   = {}   # staff_id -> set of dates worked

    for a in (preassigned or []):
        result.running_hours[a.staff_id] = result.running_hours.get(a.staff_id, 0.0) + a.hours
        d = a.session_key.split("|")[0]
        running_daily[(a.staff_id, d)] = running_daily.get((a.staff_id, d), 0.0) + a.hours
        days_worked.setdefault(a.staff_id, set()).add(d)
        result.assignments.append(a)

    dentist_assistant_pairing: dict = {}
    dentist_by_prov = cfg.dentist_by_provider_id()
    hyg_by_prov     = cfg.hygienist_by_provider_id()
    staff_by_id     = cfg.staff_by_id()
    session_defs    = {sd.daypart: sd for sd in cfg.clinic.sessions}
    rajat_rule      = cfg.rules.rajat_monday_rule

    def _av(staff_id, key):
        av = av_matrix.get((staff_id, key))
        if not av or not av.available:
            return None
        if any(a.session_key == key and a.staff_id == staff_id for a in result.assignments):
            return None
        return av

    def _daily_ok(staff, day, add_hours):
        used = running_daily.get((staff.staff_id, day), 0.0)
        return used + add_hours <= staff.max_daily_hours + 1e-9

    def _weekly_ok(staff, add_hours):
        proj = result.running_hours.get(staff.staff_id, 0.0) + add_hours
        return proj <= staff.max_weekly_hours + 1e-9

    def _commit(staff_id, day_str, hours):
        result.running_hours[staff_id] = result.running_hours.get(staff_id, 0.0) + hours
        running_daily[(staff_id, day_str)] = running_daily.get((staff_id, day_str), 0.0) + hours
        days_worked.setdefault(staff_id, set()).add(day_str)

    # ── Group sessions by date ────────────────────────────────────────────────
    sessions_by_date: dict = {}
    for s in sessions:
        sessions_by_date.setdefault(s.date, []).append(s)

    for session_date, day_sessions in sorted(sessions_by_date.items()):
        day_str = session_date.isoformat()
        weekday = session_date.weekday()

        # How many doctors are scheduled today?
        doctors_today = set()
        for s in day_sessions:
            d = demand.get(s.key)
            if d:
                doctors_today.update(d.active_dentist_provider_ids)
        all_three_doctors = len(doctors_today) >= 3

        for session in day_sessions:
            key = session.key
            d = demand.get(key)
            from roster.domain.models import DayPart
            sd = session_defs.get(session.daypart)
            session_hours = sd.hours if sd else (5.0 if session.daypart == DayPart.MORNING else 4.0)

            # ── Nav coordinator: fixed assignment ─────────────────────────
            nav = staff_by_id.get("C_NAV")
            if nav:
                nav_av = av_matrix.get(("C_NAV", key))
                if nav_av and nav_av.available:
                    if not any(a.session_key == key and a.staff_id == "C_NAV"
                               for a in result.assignments):
                        result.assignments.append(Assignment(
                            session_key=key, staff_id="C_NAV", staff_name=nav.name,
                            role=Role.COORDINATOR, hours=4.0,  # half of 8h day per session
                            reasons=["fixed coordinator 09:30–17:30"],
                            support_role="coordinator",
                        ))
                        _commit("C_NAV", day_str, 4.0)

            # ── Dentists from OD ──────────────────────────────────────────
            if d and d.appointment_count > 0:
                for prov_id in d.active_dentist_provider_ids:
                    dentist = dentist_by_prov.get(prov_id)
                    if not dentist:
                        continue
                    if any(a.session_key == key and a.staff_id == dentist.staff_id
                           for a in result.assignments):
                        continue
                    result.assignments.append(Assignment(
                        session_key=key, staff_id=dentist.staff_id, staff_name=dentist.name,
                        role=Role.DENTIST, hours=session_hours,
                        reasons=["booked in Open Dental"],
                    ))
                    _commit(dentist.staff_id, day_str, session_hours)

                # Hygienists are not rostered (hidden from the grid).

            # ── Assistants ────────────────────────────────────────────────
            if d and d.appointment_count > 0:
                for prov_id in sorted(d.active_dentist_provider_ids):
                    dentist      = dentist_by_prov.get(prov_id)
                    dentist_sid  = dentist.staff_id if dentist else None
                    dentist_name = dentist.name if dentist else f"Provider {prov_id}"

                    fixed         = cfg.rules.fixed_assistants.get(dentist_sid, []) if dentist_sid else []
                    proc_count    = d.assistant_count_by_provider.get(prov_id, cfg.clinic.assistants_per_dentist)
                    per_d_count   = cfg.rules.assistant_count_by_dentist.get(dentist_sid, 0)
                    count         = max(proc_count, len(fixed), per_d_count)

                    already = [a for a in result.assignments
                               if a.session_key == key and a.role == Role.ASSISTANT
                               and a.serves_provider_id == prov_id]
                    already_ids  = {a.staff_id for a in already}
                    slots_filled = len(already)

                    # Step 1: fixed assistants
                    for fid in fixed:
                        if slots_filled >= count:
                            break
                        if fid in already_ids:
                            continue
                        fstaff = staff_by_id.get(fid)
                        if not fstaff:
                            continue
                        av = _av(fid, key)
                        if av is None:
                            continue
                        if not _daily_ok(fstaff, day_str, session_hours):
                            continue
                        if not _weekly_ok(fstaff, session_hours):
                            continue
                        is_primary = (slots_filled == 0)
                        result.assignments.append(Assignment(
                            session_key=key, staff_id=fid, staff_name=fstaff.name,
                            role=Role.ASSISTANT, hours=min(session_hours, av.available_hours),
                            reasons=[f"fixed for {dentist_name}"],
                            serves_provider_id=prov_id,
                            support_role="chairside" if is_primary else "prep",
                        ))
                        _commit(fid, day_str, session_hours)
                        if is_primary:
                            dentist_assistant_pairing[prov_id] = fid
                        slots_filled += 1
                        already_ids.add(fid)

                    # Step 2: scored candidates
                    for slot in range(slots_filled, count):
                        is_primary = (slot == 0)
                        candidates = []
                        for asst in cfg.assistants():
                            if asst.staff_id in already_ids:
                                continue
                            av = _av(asst.staff_id, key)
                            if av is None:
                                continue
                            if not _daily_ok(asst, day_str, session_hours):
                                continue
                            if not _weekly_ok(asst, session_hours):
                                continue
                            dw = len(days_worked.get(asst.staff_id, set()))
                            sc = score_candidate(
                                asst, av, d, prov_id, cfg,
                                result.running_hours, dentist_assistant_pairing,
                                session_date=session_date,
                                days_worked_this_week=dw,
                            )
                            candidates.append((sc, asst, av))

                        if not candidates:
                            result.vacancies.append(Vacancy(
                                session_key=key, serves_provider_id=prov_id,
                                reason="no available assistant" + ("" if is_primary else " (prep)"),
                            ))
                            continue

                        candidates.sort(key=lambda x: x[0].total, reverse=True)
                        best_sc, best_asst, best_av = candidates[0]
                        result.assignments.append(Assignment(
                            session_key=key, staff_id=best_asst.staff_id,
                            staff_name=best_asst.name, role=Role.ASSISTANT,
                            hours=min(session_hours, best_av.available_hours),
                            reasons=best_sc.reasons, serves_provider_id=prov_id,
                            support_role="chairside" if is_primary else "prep",
                        ))
                        _commit(best_asst.staff_id, day_str, session_hours)
                        if is_primary:
                            dentist_assistant_pairing[prov_id] = best_asst.staff_id
                        already_ids.add(best_asst.staff_id)

            # ── Front desk ────────────────────────────────────────────────
            _assign_front_desk(
                cfg, key, session, session_date, day_str, session_hours,
                result, running_daily, days_worked, av_matrix, staff_by_id,
                all_three_doctors, _commit, _av, _daily_ok, _weekly_ok,
            )

    return result


def _assign_front_desk(
    cfg, key, session, session_date, day_str, session_hours,
    result, running_daily, days_worked, av_matrix, staff_by_id,
    all_three_doctors, _commit, _av, _daily_ok, _weekly_ok,
):
    """
    Assign front desk coverage for a session.
    - Opener first (Ziya / Simran preferred), then closer (Sravani preferred).
    - Deekshi counts toward coverage if already assigned (clinical or front desk).
    - 3rd person only if all 3 doctors working and only 1 person covers midday.
    - Sravani prioritised to maximise her hours.
    """
    fd_rules = cfg.rules.front_desk
    already_fd = [
        a for a in result.assignments
        if a.session_key == key and a.role == Role.FRONT_DESK
    ]
    # Deekshi counts as front desk coverage even when assigned clinically
    deekshi_assigned = any(
        a.session_key == key and a.staff_id == "A_DEEKSHI"
        for a in result.assignments
    )
    effective_fd_count = len(already_fd) + (1 if deekshi_assigned else 0)

    if effective_fd_count >= 2:
        return  # Already covered

    from roster.domain.models import DayPart
    is_morning = (session.daypart == DayPart.MORNING)

    # ── Build available front desk pool ──────────────────────────────────
    fd_pool = cfg.front_desk_pool()

    def _fd_candidates(preferred_role: str | None = None):
        candidates = []
        for s in fd_pool:
            if s.staff_id == "A_DEEKSHI" and deekshi_assigned:
                continue  # already counts
            if s.role == Role.COORDINATOR:
                continue  # Nav is independent
            av = _av(s.staff_id, key)
            if av is None:
                continue
            if not _daily_ok(s, day_str, session_hours):
                continue
            if not _weekly_ok(s, session_hours):
                continue
            if any(a.session_key == key and a.staff_id == s.staff_id
                   for a in result.assignments):
                continue
            # Prioritise by preferred role, then Sravani priority
            pref_score = 0
            if preferred_role and s.preferred_role == preferred_role:
                pref_score = 2
            if s.staff_id == fd_rules.preferred_closer and preferred_role == "closer":
                pref_score += 1
            # Sravani gets priority (schedule more hours)
            sravani_boost = 1 if (fd_rules.sravani_priority and s.staff_id == "F_SRAVANI") else 0
            candidates.append((pref_score + sravani_boost, s, av))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates

    slots_needed = 2 - effective_fd_count

    # Slot 1: opener (morning) or support (afternoon)
    if slots_needed >= 1:
        role_pref = "opener" if is_morning else None
        cands = _fd_candidates(preferred_role=role_pref)
        if cands:
            _, best, av = cands[0]
            result.assignments.append(Assignment(
                session_key=key, staff_id=best.staff_id, staff_name=best.name,
                role=Role.FRONT_DESK, hours=min(session_hours, av.available_hours),
                reasons=[f"front desk {'opener' if is_morning else 'shift'}"],
                support_role="opener" if is_morning else "coverage",
            ))
            _commit(best.staff_id, day_str, session_hours)
            slots_needed -= 1

    # Slot 2: closer
    if slots_needed >= 1:
        cands = _fd_candidates(preferred_role="closer")
        if cands:
            _, best, av = cands[0]
            result.assignments.append(Assignment(
                session_key=key, staff_id=best.staff_id, staff_name=best.name,
                role=Role.FRONT_DESK, hours=min(session_hours, av.available_hours),
                reasons=["front desk closer"],
                support_role="closer",
            ))
            _commit(best.staff_id, day_str, session_hours)
            slots_needed -= 1

    # 3-doctor trigger: add 3rd person if all doctors working and only 1 covers midday
    if all_three_doctors and effective_fd_count < 2:
        cands = _fd_candidates()
        if cands:
            _, best, av = cands[0]
            result.assignments.append(Assignment(
                session_key=key, staff_id=best.staff_id, staff_name=best.name,
                role=Role.FRONT_DESK, hours=min(session_hours, av.available_hours),
                reasons=["3-doctor day — extra front desk coverage"],
                support_role="coverage",
            ))
            _commit(best.staff_id, day_str, session_hours)