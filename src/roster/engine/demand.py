"""
Stage 2 of the engine: Demand.

Answers: "For each session, what work exists and what skills are required?"
"""
from __future__ import annotations
from dataclasses import dataclass, field

from roster.config.schema import AppConfig
from roster.domain.models import AppointmentMeta, Session


@dataclass
class SessionDemand:
    session_key: str

    # Which dentist provider IDs have appointments this session
    active_dentist_provider_ids: set[int] = field(default_factory=set)

    # Which hygienist provider IDs have appointments this session
    hygienist_provider_ids: set[int] = field(default_factory=set)

    # Skills required per dentist provider ID
    # e.g. {1: {"implant", "surgery"}, 2: set()}
    skills_by_provider: dict[int, set[str]] = field(default_factory=dict)

    # Total assistant-minutes needed across all appointments
    assistant_minutes: int = 0

    # Operatories in use (for overstaffing checks)
    operatories_in_use: set[str] = field(default_factory=set)

    # Raw appointment count
    appointment_count: int = 0

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
    """
    Group appointments into sessions and derive demand for each.
    Returns a dict keyed by session_key.
    """
    # Initialise empty demand for every session
    demand: dict[str, SessionDemand] = {
        s.key: SessionDemand(session_key=s.key) for s in sessions
    }

    # Map procedure categories to required skills (from rules config)
    proc_skill_map = cfg.rules.procedure_skill_map

    for appt in appointments:
        key = appt.session_key
        if key not in demand:
            # Appointment falls outside any defined session — skip
            continue

        d = demand[key]
        d.appointment_count += 1
        d.assistant_minutes += appt.assistant_min

        if appt.operatory:
            d.operatories_in_use.add(appt.operatory)

        # Dentist appointment
        if appt.provider_id is not None:
            d.active_dentist_provider_ids.add(appt.provider_id)

            # Map procedure to required skills
            required_skills = set()
            if appt.procedure_category:
                for proc, skills in proc_skill_map.items():
                    if proc.lower() in appt.procedure_category.lower():
                        required_skills.update(skills)

            # Merge skills for this provider (dentist may have multiple appts)
            if appt.provider_id not in d.skills_by_provider:
                d.skills_by_provider[appt.provider_id] = set()
            d.skills_by_provider[appt.provider_id].update(required_skills)

        # Hygienist appointment
        if appt.hygienist_id is not None:
            d.hygienist_provider_ids.add(appt.hygienist_id)

    return demand
