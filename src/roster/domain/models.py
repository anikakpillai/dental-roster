from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum
from typing import Optional


# ── Enums ──────────────────────────────────────────────────────────────────

class Role(str, Enum):
    DENTIST    = "dentist"
    HYGIENIST  = "hygienist"
    ASSISTANT  = "assistant"


class DayPart(str, Enum):
    MORNING   = "morning"
    AFTERNOON = "afternoon"


class Severity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


# ── Core shapes ────────────────────────────────────────────────────────────

@dataclass
class StaffMember:
    """One person who can be rostered."""
    staff_id:               str
    name:                   str
    role:                   Role
    provider_id:            Optional[int]         = None
    skills:                 frozenset[str]        = field(default_factory=frozenset)
    max_weekly_hours:       float                 = 40.0
    overtime_threshold:     float                 = 40.0
    hourly_cost:            float                 = 30.0
    # Which (weekday, daypart) combos this person normally works.
    # Empty = available every session (typical for dentists).
    # weekday: 0=Mon, 1=Tue ... 5=Sat
    normal_pattern:         frozenset[tuple[int, DayPart]] = field(default_factory=frozenset)
    active:                 bool                  = True


@dataclass
class Session:
    """A single working block — one date + one daypart (morning or afternoon)."""
    date:    date
    daypart: DayPart

    @property
    def key(self) -> str:
        """Unique string ID for this session e.g. '2026-06-01|morning'"""
        return f"{self.date.isoformat()}|{self.daypart.value}"


@dataclass
class AppointmentMeta:
    """
    Metadata about one Open Dental appointment.
    Contains NO patient-identifying information — only scheduling metadata.
    """
    apt_id:             int
    session_key:        str           # links back to a Session
    provider_id:        Optional[int] # treating dentist (None = hygiene-only)
    hygienist_id:       Optional[int]
    operatory:          str
    duration_min:       int
    assistant_min:      int           # how many minutes an assistant is needed
    procedure_category: Optional[str] # e.g. "Implant", "Hygiene", "Exam"


@dataclass
class Assignment:
    """One staff member assigned to one session."""
    session_key: str
    staff_id:    str
    staff_name:  str
    role:        Role
    hours:       float
    reasons:     list[str] = field(default_factory=list)  # why this person was chosen


@dataclass
class Warning:
    """Something the practice manager needs to know about."""
    session_key: str
    severity:    Severity
    message:     str