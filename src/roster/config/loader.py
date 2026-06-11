"""
Reads the YAML config files into an AppConfig object.
"""
from __future__ import annotations
from datetime import time
from pathlib import Path
import yaml

from roster.config.schema import (
    AppConfig, ClinicConfig, RulesConfig, SessionDef, ConfigError,
)
from roster.domain.models import StaffMember, Role, DayPart


def _parse_time(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def load_config_dir(config_dir: str | Path) -> AppConfig:
    config_dir = Path(config_dir)

    clinic_raw = yaml.safe_load((config_dir / "clinic.yaml").read_text())
    staff_raw = yaml.safe_load((config_dir / "staff.yaml").read_text())
    rules_raw = yaml.safe_load((config_dir / "rules.yaml").read_text())

    # ── Clinic ──
    sessions = [
        SessionDef(
            daypart=DayPart(s["daypart"]),
            start=_parse_time(s["start"]),
            end=_parse_time(s["end"]),
        )
        for s in clinic_raw["sessions"]
    ]
    clinic = ClinicConfig(
        name=clinic_raw["name"],
        working_weekdays=clinic_raw["working_weekdays"],
        sessions=sessions,
        assistants_per_dentist=clinic_raw.get("assistants_per_dentist", 1),
    )

    # ── Staff ──
    staff: list[StaffMember] = []
    for s in staff_raw["staff"]:
        raw_pattern = s.get("normal_pattern", [])
        pattern = frozenset(
            (int(p[0]), DayPart(p[1]))
            for p in raw_pattern
        )
        # Default arrival buffer by role (assistants prep before first patient)
        _role_buffer = {"assistant": 30, "reception": 90}
        arrival_buffer = int(s.get("arrival_buffer_min",
                                   _role_buffer.get(s["role"], 0)))
        recurring_off = frozenset(int(x) for x in s.get("recurring_days_off", []))

        staff.append(StaffMember(
            staff_id=s["staff_id"],
            name=s["name"],
            role=Role(s["role"]),
            provider_id=s.get("provider_id"),
            skills=frozenset(s.get("skills", [])),
            hourly_cost=float(s.get("hourly_cost", 30.0)),
            max_weekly_hours=float(s.get("max_weekly_hours", 40.0)),
            overtime_threshold=float(s.get("overtime_threshold", s.get("max_weekly_hours", 40.0))),
            arrival_buffer_min=arrival_buffer,
            recurring_days_off=recurring_off,
            normal_pattern=pattern,
        ))

    # ── Rules ──
    rules = RulesConfig(
        dentist_preferences=rules_raw.get("dentist_preferences", {}),
        procedure_skill_map=rules_raw.get("procedure_skill_map", {}),
        skill_catalogue=rules_raw.get("skill_catalogue", []),
        allow_overtime=rules_raw.get("allow_overtime", True),
        assistant_requirements=rules_raw.get("assistant_requirements", {}),
        fixed_assistants=rules_raw.get("fixed_assistants", {}),
    )

    cfg = AppConfig(clinic=clinic, staff=staff, rules=rules)

    problems = cfg.validate()
    if problems:
        raise ConfigError("Config validation failed:\n  - " + "\n  - ".join(problems))

    return cfg
