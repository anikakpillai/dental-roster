"""
Stage 2 of the engine: Demand.

For each session, derive what work exists, what skills are required,
and how many assistants each dentist needs.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from roster.config.schema import AppConfig
from roster.domain.models import AppointmentMeta, Session


@dataclass
class SessionDemand:
    session_key: str
    active_dentist_provider_ids: set[int] = field(default_factory=set)
    hygienist_provider_ids: set[int] = field(default_factory=set)
    skills_by_provider: dict[int, set[str]] = field(default_factory=dict)
    assistant_minutes: int = 0
    operatories_in_use: set[str] = field(default_factory=set)
    appointment_count: int = 0
    # How many assistants each provider needs this session (default 1)
    assistant_count_by_provider: dict[int, int] = field(default_factory=dict)
    # Whether the extra (prep) assistant also needs the procedure skill
    extra_needs_skill_by_provider: dict[int, bool] = field(default_factory=dict)

    @property
    def requires_assistant(self) -> bool:
        return len(self.active_dentist_provider_ids) > 0

    @property
    def dentist_count(self) -> int:
        return len(self.active_dentist_provider_ids)


def build_demand(
    cfg: AppConfig,
    sessions: list[Session],
    appointments: list[AppointmentMeta],
) -> dict[str, SessionDemand]:
    demand: dict[str, SessionDemand] = {
        s.key: SessionDemand(session_key=s.key) for s in sessions
    }
    proc_skill_map = cfg.rules.procedure_skill_map
    asst_req       = cfg.rules.assistant_requirements

    # Truth-layer normalisation applied BEFORE any counting:
    #   coverage      : fold a covered book into the covering dentist  (e.g. 28 -> 32)
    #   hygienist_ids : ProvNums that belong to hygienists booked in the dentist slot;
    #                   they are solo staff, never dentists, never generate assistant demand.
    coverage      = cfg.covered_provider_map()
    hygienist_ids = set(cfg.rules.hygienist_provider_ids or [])

    for appt in appointments:
        key = appt.session_key
        if key not in demand:
            continue
        d = demand[key]

        prov = appt.provider_id
        if prov is not None and prov in coverage:
            prov = coverage[prov]            # remap covered book to covering dentist

        is_hygienist = prov is not None and prov in hygienist_ids

        # Any real appointment means the clinic is open this session.
        d.appointment_count += 1
        if appt.operatory:
            d.operatories_in_use.add(appt.operatory)

        if prov is not None and not is_hygienist:
            d.assistant_minutes += appt.assistant_min
            d.active_dentist_provider_ids.add(prov)

            required_skills = set()
            count = 1
            extra_skill = False
            if appt.procedure_category:
                pc = appt.procedure_category.lower()
                for proc, skills in proc_skill_map.items():
                    if proc.lower() in pc:
                        required_skills.update(skills)
                for proc, req in asst_req.items():
                    if proc.lower() in pc:
                        count = max(count, int(req.get("count", 1)))
                        if req.get("extra_needs_skill", False):
                            extra_skill = True

            if prov not in d.skills_by_provider:
                d.skills_by_provider[prov] = set()
            d.skills_by_provider[prov].update(required_skills)

            d.assistant_count_by_provider[prov] = max(
                d.assistant_count_by_provider.get(prov, 1), count
            )
            if extra_skill:
                d.extra_needs_skill_by_provider[prov] = True

        # Hygienists are hidden from the roster: no dentist demand, no assistant demand.

    return demand




def dentist_day_truth(cfg: AppConfig, appointments: list[AppointmentMeta]) -> dict:
    """Ground truth from Open Dental: which dentists work each day and their real spans.
    {day_iso: {provider_id: {"staff_id","name","start","end"}}}.
    Applies the same coverage remap + hygienist filter as build_demand."""
    coverage      = cfg.covered_provider_map()
    hygienist_ids = set(cfg.rules.hygienist_provider_ids or [])
    dentists      = cfg.dentist_by_provider_id()
    truth: dict = {}
    for appt in appointments:
        prov = appt.provider_id
        if prov is None:
            continue
        if prov in coverage:
            prov = coverage[prov]
        if prov in hygienist_ids:
            continue
        d = dentists.get(prov)
        if d is None or not appt.day_iso or not appt.start_hm:
            continue
        day = truth.setdefault(appt.day_iso, {})
        cur = day.get(prov)
        if cur is None:
            day[prov] = {"staff_id": d.staff_id, "name": d.name,
                         "start": appt.start_hm, "end": appt.end_hm}
        else:
            if appt.start_hm < cur["start"]:
                cur["start"] = appt.start_hm
            if appt.end_hm > cur["end"]:
                cur["end"] = appt.end_hm
    return truth
