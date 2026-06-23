from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from roster.domain.models import Role, StaffMember

_ROLE_MAP = {
    "dentist":     Role.DENTIST,
    "hygienist":   Role.HYGIENIST,
    "assistant":   Role.ASSISTANT,
    "front_desk":  Role.FRONT_DESK,
    "coordinator": Role.COORDINATOR,
    "sterilization": Role.STERILIZATION,
}

_BUFFER_DEFAULTS = {
    Role.DENTIST:     0,
    Role.HYGIENIST:   0,
    Role.ASSISTANT:   30,
    Role.FRONT_DESK:  90,
    Role.COORDINATOR: 0,
    Role.STERILIZATION: 120,
}


@dataclass
class ClinicSession:
    daypart: str
    hours:   float


@dataclass
class ClinicConfig:
    name:                   str
    assistants_per_dentist: int = 1
    sessions:               list = field(default_factory=list)


@dataclass
class ShiftShape:
    standard_day_hours: float = 8.0
    standard_day_max:   float = 9.0
    fifth_day_target:   float = 5.0
    fifth_day_cap:      float = 6.0


@dataclass
class FrontDeskRules:
    preferred_closer:     str
    preferred_openers:    list
    third_person_trigger: int
    sravani_priority:     bool
    weekly_day_off:       bool
    dual_role_staff:      list


@dataclass
class RajatMondayRule:
    staff_id:           str
    avoid_if_available: str
    monday_cap_hours:   float


@dataclass
class RulesConfig:
    dentist_preferences:        dict
    fixed_assistants:           dict
    assistant_count_by_dentist: dict
    procedure_skill_map:        dict
    assistant_requirements:     dict
    skill_catalogue:            list
    allow_overtime:             bool
    shift_shape:                ShiftShape
    front_desk:                 FrontDeskRules
    rajat_monday_rule:          Optional[RajatMondayRule]
    scoring_weights:            dict


@dataclass
class AppConfig:
    clinic: ClinicConfig
    staff:  list
    rules:  RulesConfig

    def staff_by_id(self) -> dict:
        return {s.staff_id: s for s in self.staff if s.active}

    def staff_by_role(self, role: Role) -> list:
        return [s for s in self.staff if s.role == role and s.active]

    def dentist_by_provider_id(self) -> dict:
        return {
            s.provider_id: s for s in self.staff
            if s.role == Role.DENTIST and s.provider_id is not None and s.active
        }

    def hygienist_by_provider_id(self) -> dict:
        return {
            s.provider_id: s for s in self.staff
            if s.role == Role.HYGIENIST and s.provider_id is not None and s.active
        }

    def front_desk_pool(self) -> list:
        """Front desk staff + dual-role assistants."""
        result = [s for s in self.staff if s.role == Role.FRONT_DESK and s.active]
        dual_ids = self.rules.front_desk.dual_role_staff
        result += [s for s in self.staff if s.staff_id in dual_ids and s.active]
        return result

    def assistants(self) -> list:
        return [s for s in self.staff if s.role == Role.ASSISTANT and s.active]


def build_staff_member(raw: dict) -> StaffMember:
    role_str = raw.get("role", "assistant")
    role = _ROLE_MAP.get(role_str, Role.ASSISTANT)
    buf = raw.get("arrival_buffer_min", _BUFFER_DEFAULTS.get(role, 30))
    ot  = raw.get("overtime_threshold", raw.get("max_weekly_hours", 40.0))
    return StaffMember(
        staff_id=raw["staff_id"],
        name=raw["name"],
        role=role,
        skills=set(raw.get("skills", [])),
        hourly_cost=float(raw.get("hourly_cost", 30.0)),
        max_weekly_hours=float(raw.get("max_weekly_hours", 40.0)),
        max_daily_hours=float(raw.get("max_daily_hours", 9.0)),
        overtime_threshold=float(ot),
        arrival_buffer_min=int(buf),
        provider_id=raw.get("provider_id"),
        active=raw.get("active", True),
        recurring_days_off=raw.get("recurring_days_off", []),
        normal_pattern=raw.get("normal_pattern", []),
        dual_role=raw.get("dual_role"),
        preferred_role=raw.get("preferred_role"),
        shift_start=raw.get("shift_start"),
        shift_end=raw.get("shift_end"),
        monday_cap_hours=raw.get("monday_cap_hours"),
    )
