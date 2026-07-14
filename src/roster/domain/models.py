from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class Role(str, Enum):
    DENTIST     = "dentist"
    HYGIENIST   = "hygienist"
    ASSISTANT   = "assistant"
    FRONT_DESK  = "front_desk"
    COORDINATOR = "coordinator"
    STERILIZATION = "sterilization"


class DayPart(str, Enum):
    MORNING   = "morning"
    AFTERNOON = "afternoon"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING  = "warning"
    INFO     = "info"


@dataclass
class StaffMember:
    staff_id:           str
    name:               str
    role:               Role
    skills:             set
    hourly_cost:        float        = 30.0
    max_weekly_hours:   float        = 40.0
    max_daily_hours:    float        = 9.0
    overtime_threshold: float        = 40.0
    arrival_buffer_min: int          = 30
    provider_id:        Optional[int] = None
    active:             bool         = True
    recurring_days_off: list         = field(default_factory=list)
    normal_pattern:     list         = field(default_factory=list)
    dual_role:          Optional[str] = None
    preferred_role:     Optional[str] = None
    shift_start:        Optional[str] = None
    shift_end:          Optional[str] = None
    monday_cap_hours:   Optional[float] = None
    covers_provider_ids: list         = field(default_factory=list)


@dataclass
class Session:
    date:    date
    daypart: DayPart

    @property
    def key(self) -> str:
        return f"{self.date.isoformat()}|{self.daypart.value}"


@dataclass
class AppointmentMeta:
    apt_id:             int
    session_key:        str
    provider_id:        Optional[int]
    hygienist_id:       Optional[int]
    operatory:          str
    duration_min:       int
    assistant_min:      int
    procedure_category: Optional[str]


@dataclass
class Assignment:
    session_key:        str
    staff_id:           str
    staff_name:         str
    role:               Role
    hours:              float
    reasons:            list = field(default_factory=list)
    serves_provider_id: Optional[int] = None
    support_role:       Optional[str] = None


@dataclass
class Warning:
    session_key:  str
    severity:     Severity
    warning_type: str
    message:      str
    staff_id:     Optional[str] = None


@dataclass
class PatternTiming:
    total_min:     int
    assistant_min: int