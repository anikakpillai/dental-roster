from __future__ import annotations
from pathlib import Path
import yaml

from roster.config.schema import (
    AppConfig, ClinicConfig, ClinicSession, FrontDeskRules,
    RajatMondayRule, RulesConfig, ShiftShape, build_staff_member,
)


def _hours_from_session(s: dict) -> float:
    """Session length in hours. Supports explicit `hours` OR `start`/`end` times."""
    if "hours" in s and s["hours"] is not None:
        return float(s["hours"])
    start = s.get("start")
    end = s.get("end")
    if start and end:
        sh, sm = [int(x) for x in str(start).split(":")]
        eh, em = [int(x) for x in str(end).split(":")]
        hours = (eh + em / 60.0) - (sh + sm / 60.0)
        if hours < 0:
            hours += 24
        return round(hours, 2)
    daypart = str(s.get("daypart", "")).lower()
    return 5.0 if daypart == "morning" else 4.0


def load_config_dir(config_dir: Path) -> AppConfig:
    staff_raw  = yaml.safe_load((config_dir / "staff.yaml").read_text())
    rules_raw  = yaml.safe_load((config_dir / "rules.yaml").read_text())
    clinic_raw = {}
    clinic_path = config_dir / "clinic.yaml"
    if clinic_path.exists():
        clinic_raw = yaml.safe_load(clinic_path.read_text()) or {}

    staff = [build_staff_member(s) for s in staff_raw.get("staff", [])]

    ss_raw = rules_raw.get("shift_shape", {})
    shift_shape = ShiftShape(
        standard_day_hours=float(ss_raw.get("standard_day_hours", 8.0)),
        standard_day_max=float(ss_raw.get("standard_day_max", 9.0)),
        fifth_day_target=float(ss_raw.get("fifth_day_target", 5.0)),
        fifth_day_cap=float(ss_raw.get("fifth_day_cap", 6.0)),
    )

    fd_raw = rules_raw.get("front_desk", {})
    front_desk = FrontDeskRules(
        preferred_closer=fd_raw.get("preferred_closer", "F_SRAVANI"),
        preferred_openers=fd_raw.get("preferred_openers", []),
        third_person_trigger=int(fd_raw.get("third_person_trigger", 3)),
        sravani_priority=bool(fd_raw.get("sravani_priority", True)),
        weekly_day_off=bool(fd_raw.get("weekly_day_off", True)),
        dual_role_staff=fd_raw.get("dual_role_staff", []),
    )

    rm_raw = rules_raw.get("rajat_monday_rule", {})
    rajat_rule = RajatMondayRule(
        staff_id=rm_raw.get("staff_id", "A_RAJAT"),
        avoid_if_available=rm_raw.get("avoid_if_available", "A_LIKHITHA"),
        monday_cap_hours=float(rm_raw.get("monday_cap_hours", 6.0)),
    ) if rm_raw else None

    rules = RulesConfig(
        dentist_preferences=rules_raw.get("dentist_preferences", {}),
        fixed_assistants=rules_raw.get("fixed_assistants", {}),
        assistant_count_by_dentist=rules_raw.get("assistant_count_by_dentist", {}),
        procedure_skill_map=rules_raw.get("procedure_skill_map", {}),
        assistant_requirements=rules_raw.get("assistant_requirements", {}),
        skill_catalogue=rules_raw.get("skill_catalogue", []),
        allow_overtime=bool(rules_raw.get("allow_overtime", False)),
        shift_shape=shift_shape,
        front_desk=front_desk,
        rajat_monday_rule=rajat_rule,
        scoring_weights=rules_raw.get("scoring_weights", {}),
    )

    raw_sessions = clinic_raw.get("sessions", [
        {"daypart": "morning", "hours": 5.0},
        {"daypart": "afternoon", "hours": 4.0},
    ])
    sessions = [
        ClinicSession(daypart=s["daypart"], hours=_hours_from_session(s))
        for s in raw_sessions
    ]

    clinic = ClinicConfig(
        name=clinic_raw.get("name", "Unity Dental"),
        assistants_per_dentist=int(clinic_raw.get("assistants_per_dentist", 1)),
        sessions=sessions,
    )

    return AppConfig(clinic=clinic, staff=staff, rules=rules)
