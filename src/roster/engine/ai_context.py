"""
AI Context Assembler.

Gathers everything Claude needs to build a roster into one clean,
structured briefing:
  1. The week's demand (from Open Dental, already parsed by demand.py)
  2. Staff roster + their rules (from config)
  3. Who is available each day (recurring days off + weekly exceptions)
  4. The clinic's standing rules (preferences, caps, front desk policy)
  5. The manager's free-text considerations for THIS week

The factual parsing (appointment patterns, assistant-minutes, availability)
is done deterministically here. The JUDGMENT (who covers what) is left to
the AI. This module produces the briefing; ai_roster.py sends it.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date

from roster.config.schema import AppConfig
from roster.domain.models import Role
from roster.engine.availability import WeeklyInput
from roster.engine.demand import SessionDemand

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class RosterContext:
    """The complete briefing handed to the AI."""
    week_start:        str
    week_end:          str
    clinic_name:       str
    demand_summary:    list           # per-session demand, human-readable
    staff_briefing:    list           # each staff member + their rules
    standing_rules:    dict           # clinic-wide policies
    weekly_availability: list         # who is off / limited this week
    manager_notes:     str            # free-text weekly considerations
    dentist_days:      dict = None    # FACTS: {date: [{dentist, start, end}]} from Open Dental


def _provider_name(cfg: AppConfig, prov_id: int) -> str:
    d = cfg.dentist_by_provider_id().get(prov_id)
    if d:
        return d.name
    h = cfg.hygienist_by_provider_id().get(prov_id)
    if h:
        return h.name
    return f"Provider {prov_id}"


def build_demand_summary(cfg: AppConfig, demand: dict) -> list:
    """Turn the parsed SessionDemand into readable per-session facts."""
    summary = []
    for key, d in sorted(demand.items()):
        if d.appointment_count == 0:
            continue
        day_iso, daypart = key.split("|")
        dentists = []
        for prov_id in sorted(d.active_dentist_provider_ids):
            name = _provider_name(cfg, prov_id)
            count = d.assistant_count_by_provider.get(prov_id, 1)
            skills = sorted(d.skills_by_provider.get(prov_id, set()))
            dentists.append({
                "dentist": name,
                "provider_id": prov_id,
                "assistants_needed": count,
                "skills_required": skills,
            })
        summary.append({
            "date": day_iso,
            "weekday": DAY_NAMES[date.fromisoformat(day_iso).weekday()],
            "session": daypart,
            "appointment_count": d.appointment_count,
            "assistant_minutes": d.assistant_minutes,
            "dentists_working": dentists,
        })
    return summary


def build_staff_briefing(cfg: AppConfig) -> list:
    """Each staff member with the rules the AI must respect."""
    briefing = []
    for s in cfg.staff:
        if not s.active:
            continue
        days_off = [DAY_NAMES[d] for d in (s.recurring_days_off or [])]
        entry = {
            "staff_id": s.staff_id,
            "name": s.name,
            "role": s.role.value,
            "skills": sorted(s.skills),
            "max_weekly_hours": s.max_weekly_hours,
            "max_daily_hours": s.max_daily_hours,
            "arrival_buffer_min": s.arrival_buffer_min,
            "usual_days_off": days_off,
        }
        if s.role == Role.DENTIST:
            entry["provider_id"] = s.provider_id
        if s.dual_role:
            entry["dual_role"] = s.dual_role
        if s.preferred_role:
            entry["preferred_role"] = s.preferred_role
        if s.shift_start:
            entry["fixed_shift"] = f"{s.shift_start}-{s.shift_end}"
        if s.monday_cap_hours:
            entry["monday_cap_hours"] = s.monday_cap_hours
        briefing.append(entry)
    return briefing


def build_standing_rules(cfg: AppConfig) -> dict:
    """Clinic-wide policies the AI must follow."""
    r = cfg.rules
    fd = r.front_desk
    return {
        "shift_shape": {
            "description": "Each person works up to 40h/week. Aim for 8-9h on the "
                           "first 4 working days and 4-6h on the 5th day so the week "
                           "stays at or under 40h.",
            "standard_day_hours": r.shift_shape.standard_day_hours,
            "standard_day_max": r.shift_shape.standard_day_max,
            "fifth_day_cap": r.shift_shape.fifth_day_cap,
        },
        "assistant_priority": [
            "1. Keep everyone at or under 40h/week (hard limit).",
            "2. Shape shifts: 8-9h days 1-4, 4-6h on day 5.",
            "3. Respect each dentist's preferred assistants.",
            "4. Prefer people on their usual working days.",
            "5. Balance hours fairly across the team.",
        ],
        "dentist_preferences": r.dentist_preferences,
        "fixed_assistants": r.fixed_assistants,
        "assistant_count_by_dentist": r.assistant_count_by_dentist,
        "front_desk_policy": {
            "description": "One opener + one closer per day. A 3rd front desk person "
                           "is only added when ALL THREE doctors are working and only "
                           "one person would otherwise cover a period.",
            "preferred_closer": fd.preferred_closer,
            "preferred_openers": fd.preferred_openers,
            "third_person_trigger_doctors": fd.third_person_trigger,
            "every_front_desk_gets_a_day_off": fd.weekly_day_off,
            "maximise_hours_for": fd.preferred_closer,
            "dual_role_counts_as_coverage": fd.dual_role_staff,
        },
        "coordinator_note": "Nav is the patient coordinator on fixed hours "
                            "(9:30-17:30). She is independent and never counts as "
                            "an opener or closer. Never change her hours.",
        "arrival_buffers": {
            "front_desk_opener_min": 90,
            "assistant_min": 30,
            "note": "Start time = first patient time minus the person's arrival "
                    "buffer. End time = last patient's finish.",
        },
    }


def build_weekly_availability(cfg: AppConfig, week_start: date, week_end: date,
                              weekly: WeeklyInput) -> list:
    """Who is off or time-limited this specific week (exceptions on top of usual)."""
    items = []
    for sid, d in weekly.days_off:
        staff = cfg.staff_by_id().get(sid)
        items.append({
            "staff": staff.name if staff else sid,
            "date": d.isoformat(),
            "type": "day_off",
            "note": weekly.note_for(sid, d, "day_off"),
        })
    for sid, d, t in weekly.late_starts:
        staff = cfg.staff_by_id().get(sid)
        items.append({
            "staff": staff.name if staff else sid,
            "date": d.isoformat(),
            "type": "late_start",
            "from": t.strftime("%H:%M"),
            "note": weekly.note_for(sid, d, "late_start"),
        })
    for sid, d, t in weekly.early_finishes:
        staff = cfg.staff_by_id().get(sid)
        items.append({
            "staff": staff.name if staff else sid,
            "date": d.isoformat(),
            "type": "early_finish",
            "until": t.strftime("%H:%M"),
            "note": weekly.note_for(sid, d, "early_finish"),
        })
    return items


def assemble_context(
    cfg: AppConfig,
    week_start: date,
    week_end: date,
    demand: dict,
    weekly: WeeklyInput,
    manager_notes: str = "",
    dentist_truth: dict | None = None,
) -> RosterContext:
    """Build the full briefing for the AI."""
    dentist_days = None
    if dentist_truth:
        dentist_days = {
            day: [{"dentist": v["name"], "staff_id": v["staff_id"],
                   "start": v["start"], "end": v["end"]}
                  for _, v in sorted(info.items())]
            for day, info in sorted(dentist_truth.items())
        }
    return RosterContext(
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        clinic_name=cfg.clinic.name,
        demand_summary=build_demand_summary(cfg, demand),
        staff_briefing=build_staff_briefing(cfg),
        standing_rules=build_standing_rules(cfg),
        weekly_availability=build_weekly_availability(cfg, week_start, week_end, weekly),
        manager_notes=manager_notes.strip(),
        dentist_days=dentist_days,
    )

