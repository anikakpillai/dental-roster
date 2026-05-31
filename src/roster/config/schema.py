"""
Config shapes + validation.

These mirror the YAML files. AppConfig is the single bundle the rest of
the app receives — it never reads YAML directly.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import time

from roster.domain.models import StaffMember, Role, DayPart


class ConfigError(Exception):
    """Raised when config is structurally invalid."""


@dataclass
class SessionDef:
    daypart: DayPart
    start: time
    end: time

    @property
    def hours(self) -> float:
        mins = (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)
        return round(mins / 60, 2)


@dataclass
class ClinicConfig:
    name: str
    working_weekdays: list[int]
    sessions: list[SessionDef]
    assistants_per_dentist: int = 1


@dataclass
class RulesConfig:
    dentist_preferences: dict[str, list[str]] = field(default_factory=dict)
    procedure_skill_map: dict[str, list[str]] = field(default_factory=dict)
    skill_catalogue: list[str] = field(default_factory=list)
    allow_overtime: bool = True


@dataclass
class AppConfig:
    clinic: ClinicConfig
    staff: list[StaffMember]
    rules: RulesConfig

    # ── Lookup helpers (so the engine never loops manually) ──
    def staff_by_id(self) -> dict[str, StaffMember]:
        return {s.staff_id: s for s in self.staff}

    def staff_by_role(self, role: Role) -> list[StaffMember]:
        return [s for s in self.staff if s.role == role and s.active]

    def dentist_by_provider_id(self) -> dict[int, StaffMember]:
        return {s.provider_id: s for s in self.staff
                if s.role == Role.DENTIST and s.provider_id is not None}

    def hygienist_by_provider_id(self) -> dict[int, StaffMember]:
        return {s.provider_id: s for s in self.staff
                if s.role == Role.HYGIENIST and s.provider_id is not None}

    def session_def(self, daypart: DayPart) -> SessionDef:
        for sd in self.clinic.sessions:
            if sd.daypart == daypart:
                return sd
        raise ConfigError(f"No session defined for {daypart}")

    def validate(self) -> list[str]:
        """Return a list of problems. Empty list = config is valid."""
        problems: list[str] = []
        catalogue = set(self.rules.skill_catalogue)
        ids = {s.staff_id for s in self.staff}

        # Every skill a staff member has must be in the catalogue
        for s in self.staff:
            for skill in s.skills:
                if catalogue and skill not in catalogue:
                    problems.append(f"Staff '{s.staff_id}' has skill '{skill}' not in catalogue")

        # Every preference must point to a real assistant
        for dentist, prefs in self.rules.dentist_preferences.items():
            if dentist not in ids:
                problems.append(f"Preference references unknown dentist '{dentist}'")
            for a in prefs:
                if a not in ids:
                    problems.append(f"Dentist '{dentist}' prefers unknown assistant '{a}'")

        # No duplicate session dayparts
        seen = set()
        for sd in self.clinic.sessions:
            if sd.daypart in seen:
                problems.append(f"Duplicate session daypart '{sd.daypart}'")
            seen.add(sd.daypart)

        return problems
