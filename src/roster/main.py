"""
Dental Roster API — v2

Endpoints:
  Roster:  GET/POST /api/roster
  Staff:   GET/POST /api/staff, PUT/DELETE /api/staff/{id}
  Rules:   GET /api/rules, PUT /api/rules/preferences|procedures
  Config:  GET /api/config/staff
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from roster.config.loader import load_config_dir
from roster.config.writer import (
    load_rules_raw, load_staff_raw,
    save_rules_raw, save_staff_raw,
)
from roster.engine.availability import WeeklyInput
from roster.engine.roster_service import build_roster, build_ai_roster

app = FastAPI(title="Dental Roster API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

CONFIG_DIR = Path("config")


# ── Request models ────────────────────────────────────────────────────────────

class DayOffInput(BaseModel):
    staff_id: str
    date:     date

class LateStartInput(BaseModel):
    staff_id:   str
    date:       date
    start_time: str

class EarlyFinishInput(BaseModel):
    staff_id:  str
    date:      date
    end_time:  str

class WeeklyExceptionsInput(BaseModel):
    days_off:       list[DayOffInput]      = []
    late_starts:    list[LateStartInput]   = []
    early_finishes: list[EarlyFinishInput] = []
    notes:          list[str]              = []

class AIRosterInput(BaseModel):
    exceptions:    WeeklyExceptionsInput | None = None
    manager_notes: str = ""

class StaffInput(BaseModel):
    recurring_days_off: list[int] = []
    arrival_buffer_min: int | None = None
    max_daily_hours: float | None = None
    name:               str
    role:               str
    provider_id:        Optional[int]   = None
    skills:             list[str]       = []
    hourly_cost:        float           = 30.0
    max_weekly_hours:   float           = 40.0
    overtime_threshold: Optional[float] = None
    normal_pattern:     list[list]      = []
    active:             bool            = True

class PreferencesInput(BaseModel):
    preferences: dict[str, list[str]]

class ProcedureRulesInput(BaseModel):
    procedure_skill_map: dict[str, list[str]]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_time(s: str):
    from datetime import time
    hh, mm = s.split(":")
    return time(int(hh), int(mm))

def _build_weekly(exc: WeeklyExceptionsInput) -> WeeklyInput:
    return WeeklyInput(
        days_off=[(d.staff_id, d.date) for d in exc.days_off],
        late_starts=[(l.staff_id, l.date, _parse_time(l.start_time)) for l in exc.late_starts],
        early_finishes=[(e.staff_id, e.date, _parse_time(e.end_time)) for e in exc.early_finishes],
        notes=exc.notes,
    )

def _serialise_roster(roster) -> dict:
    return {
        "summary":     roster.summary(),
        "assignments": [
            {"session_key": a.session_key, "staff_id": a.staff_id,
             "staff_name": a.staff_name, "role": a.role.value,
             "hours": a.hours, "serves_provider_id": a.serves_provider_id,
             "support_role": a.support_role, "reasons": a.reasons}
            for a in roster.assignments
        ],
        "vacancies": [
            {"session_key": v.session_key,
             "serves_provider_id": v.serves_provider_id, "reason": v.reason}
            for v in roster.vacancies
        ],
        "hours": [
            {"staff_id": h.staff_id, "staff_name": h.staff_name,
             "role": h.role.value, "total_hours": h.total_hours,
             "max_hours": h.max_hours, "overtime_hours": h.overtime_hours,
             "cost": h.cost}
            for h in roster.hours
        ],
        "notes":       roster.notes,
        "total_cost":  roster.total_cost,
        "warnings": [
            {"session_key": w.session_key, "severity": w.severity.value,
             "warning_type": w.warning_type, "staff_id": w.staff_id,
             "message": w.message}
            for w in getattr(roster, "warnings", [])
        ],
    }

def _generate_staff_id(name: str, role: str, existing: set[str]) -> str:
    prefix = {"dentist": "D", "hygienist": "H", "assistant": "A"}.get(role, "S")
    base   = name.split()[0].upper()
    cand   = f"{prefix}_{base}"
    i      = 2
    while cand in existing:
        cand = f"{prefix}_{base}_{i}"; i += 1
    return cand


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Config (read-only compiled view) ─────────────────────────────────────────

@app.get("/api/config/staff")
def get_compiled_staff():
    cfg = load_config_dir(CONFIG_DIR)
    return {"staff": [
        {"staff_id": s.staff_id, "name": s.name, "role": s.role.value,
         "skills": sorted(s.skills), "max_weekly_hours": s.max_weekly_hours,
         "hourly_cost": s.hourly_cost, "provider_id": s.provider_id,
         "active": s.active}
        for s in cfg.staff
    ]}


# ── Roster ────────────────────────────────────────────────────────────────────

@app.get("/api/roster")
def get_roster(week_start: date, week_end: date):
    try:
        cfg    = load_config_dir(CONFIG_DIR)
        roster = build_roster(cfg, week_start, week_end)
        return _serialise_roster(roster)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/roster")
def get_roster_with_exceptions(
    week_start: date, week_end: date,
    body: WeeklyExceptionsInput = None,
):
    try:
        cfg    = load_config_dir(CONFIG_DIR)
        weekly = _build_weekly(body) if body else WeeklyInput()
        roster = build_roster(cfg, week_start, week_end, weekly=weekly)
        return _serialise_roster(roster)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai-roster")
def get_ai_roster(
    week_start: date, week_end: date,
    body: AIRosterInput = None,
):
    """AI-built roster (Gemini + validator). Accepts optional manager_notes."""
    try:
        cfg = load_config_dir(CONFIG_DIR)
        weekly = WeeklyInput()
        notes = ""
        if body:
            if body.exceptions:
                weekly = _build_weekly(body.exceptions)
            notes = body.manager_notes or ""
        return build_ai_roster(cfg, week_start, week_end, weekly=weekly, manager_notes=notes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Staff CRUD ────────────────────────────────────────────────────────────────

@app.get("/api/staff")
def list_staff():
    return {"staff": load_staff_raw(CONFIG_DIR)}

@app.post("/api/staff")
def add_staff(body: StaffInput):
    staff_list   = load_staff_raw(CONFIG_DIR)
    existing_ids = {s["staff_id"] for s in staff_list}
    staff_id     = _generate_staff_id(body.name, body.role, existing_ids)

    entry = {
        "staff_id":         staff_id,
        "name":             body.name,
        "role":             body.role,
        "skills":           body.skills,
        "hourly_cost":      body.hourly_cost,
        "max_weekly_hours": body.max_weekly_hours,
        "active":           body.active,
    }
    if body.provider_id        is not None: entry["provider_id"]        = body.provider_id
    if body.overtime_threshold is not None: entry["overtime_threshold"] = body.overtime_threshold
    if body.normal_pattern:                 entry["normal_pattern"]     = body.normal_pattern
    if body.recurring_days_off:             entry["recurring_days_off"] = body.recurring_days_off
    if body.arrival_buffer_min is not None: entry["arrival_buffer_min"] = body.arrival_buffer_min
    if body.max_daily_hours    is not None: entry["max_daily_hours"]    = body.max_daily_hours

    staff_list.append(entry)
    save_staff_raw(CONFIG_DIR, staff_list)
    return {"staff_id": staff_id, "staff": entry}

@app.put("/api/staff/{staff_id}")
def update_staff(staff_id: str, body: StaffInput):
    staff_list = load_staff_raw(CONFIG_DIR)
    for i, s in enumerate(staff_list):
        if s["staff_id"] == staff_id:
            updated = {
                "staff_id":         staff_id,
                "name":             body.name,
                "role":             body.role,
                "skills":           body.skills,
                "hourly_cost":      body.hourly_cost,
                "max_weekly_hours": body.max_weekly_hours,
                "active":           body.active,
            }
            if body.provider_id        is not None: updated["provider_id"]        = body.provider_id
            if body.overtime_threshold is not None: updated["overtime_threshold"] = body.overtime_threshold
            updated["normal_pattern"] = body.normal_pattern
            if body.recurring_days_off:             updated["recurring_days_off"] = body.recurring_days_off
            if body.arrival_buffer_min is not None: updated["arrival_buffer_min"] = body.arrival_buffer_min
            if body.max_daily_hours    is not None: updated["max_daily_hours"]    = body.max_daily_hours
            staff_list[i] = updated
            save_staff_raw(CONFIG_DIR, staff_list)
            return {"staff_id": staff_id, "staff": updated}
    raise HTTPException(404, f"Staff '{staff_id}' not found")

@app.delete("/api/staff/{staff_id}")
def deactivate_staff(staff_id: str):
    staff_list = load_staff_raw(CONFIG_DIR)
    for s in staff_list:
        if s["staff_id"] == staff_id:
            s["active"] = False
            save_staff_raw(CONFIG_DIR, staff_list)
            return {"deactivated": staff_id}
    raise HTTPException(404, f"Staff '{staff_id}' not found")


# ── Rules ─────────────────────────────────────────────────────────────────────

@app.get("/api/rules")
def get_rules():
    r = load_rules_raw(CONFIG_DIR)
    return {
        "dentist_preferences":  r.get("dentist_preferences", {}),
        "procedure_skill_map":  r.get("procedure_skill_map", {}),
        "skill_catalogue":      r.get("skill_catalogue", []),
        "fixed_assistants":     r.get("fixed_assistants", {}),
        "assistant_count_by_dentist": r.get("assistant_count_by_dentist", {}),
    }

@app.put("/api/rules/preferences")
def update_preferences(body: PreferencesInput):
    rules = load_rules_raw(CONFIG_DIR)
    rules["dentist_preferences"] = body.preferences
    save_rules_raw(CONFIG_DIR, rules)
    return {"dentist_preferences": body.preferences}

@app.put("/api/rules/procedures")
def update_procedures(body: ProcedureRulesInput):
    rules = load_rules_raw(CONFIG_DIR)
    rules["procedure_skill_map"] = body.procedure_skill_map
    save_rules_raw(CONFIG_DIR, rules)
    return {"procedure_skill_map": body.procedure_skill_map}

class FixedAssistantsInput(BaseModel):
    fixed_assistants: dict[str, list[str]]


@app.put("/api/rules/fixed-assistants")
def update_fixed_assistants(body: FixedAssistantsInput):
    rules = load_rules_raw(CONFIG_DIR)
    rules["fixed_assistants"] = body.fixed_assistants
    save_rules_raw(CONFIG_DIR, rules)
    return {"fixed_assistants": body.fixed_assistants}


class AssistantCountInput(BaseModel):
    assistant_count_by_dentist: dict[str, int]


@app.put("/api/rules/assistant-count")
def update_assistant_count(body: AssistantCountInput):
    rules = load_rules_raw(CONFIG_DIR)
    rules["assistant_count_by_dentist"] = body.assistant_count_by_dentist
    save_rules_raw(CONFIG_DIR, rules)
    return {"assistant_count_by_dentist": body.assistant_count_by_dentist}
