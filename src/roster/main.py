"""
Dental Roster API

The web layer. Thin shell over the engine — no business logic lives here.
Every endpoint does the same three things:
  1. Parse the request
  2. Call the engine
  3. Return the result as JSON
"""
from __future__ import annotations
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from roster.config.loader import load_config_dir
from roster.engine.availability import WeeklyInput
from roster.engine.roster_service import build_roster

app = FastAPI(
    title="Dental Roster API",
    description="Automated rostering for dental clinics. Powered by Open Dental data.",
    version="1.0.0",
)

# Allow the frontend (running on a different port) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_DIR = "config"


# ── Request models ──────────────────────────────────────────────────────────

class DayOffInput(BaseModel):
    staff_id: str
    date:     date


class LateStartInput(BaseModel):
    staff_id:   str
    date:       date
    start_time: str   # "HH:MM"


class EarlyFinishInput(BaseModel):
    staff_id:   str
    date:       date
    end_time:   str   # "HH:MM"


class WeeklyExceptionsInput(BaseModel):
    days_off:       list[DayOffInput]      = []
    late_starts:    list[LateStartInput]   = []
    early_finishes: list[EarlyFinishInput] = []
    notes:          list[str]              = []


# ── Helpers ─────────────────────────────────────────────────────────────────

def _parse_time(s: str):
    from datetime import time
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def _build_weekly(exc: WeeklyExceptionsInput) -> WeeklyInput:
    return WeeklyInput(
        days_off=[
            (d.staff_id, d.date) for d in exc.days_off
        ],
        late_starts=[
            (l.staff_id, l.date, _parse_time(l.start_time))
            for l in exc.late_starts
        ],
        early_finishes=[
            (e.staff_id, e.date, _parse_time(e.end_time))
            for e in exc.early_finishes
        ],
        notes=exc.notes,
    )


def _serialise_roster(roster) -> dict:
    return {
        "summary": roster.summary(),
        "assignments": [
            {
                "session_key":        a.session_key,
                "staff_id":           a.staff_id,
                "staff_name":         a.staff_name,
                "role":               a.role.value,
                "hours":              a.hours,
                "serves_provider_id": a.serves_provider_id,
                "reasons":            a.reasons,
            }
            for a in roster.assignments
        ],
        "vacancies": [
            {
                "session_key":        v.session_key,
                "serves_provider_id": v.serves_provider_id,
                "reason":             v.reason,
            }
            for v in roster.vacancies
        ],
        "hours": [
            {
                "staff_id":       h.staff_id,
                "staff_name":     h.staff_name,
                "role":           h.role.value,
                "total_hours":    h.total_hours,
                "max_hours":      h.max_hours,
                "overtime_hours": h.overtime_hours,
                "cost":           h.cost,
            }
            for h in roster.hours
        ],
        "notes": roster.notes,
        "total_cost": roster.total_cost,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config/staff")
def get_staff():
    """Return all staff with their skills and roles — used by the UI."""
    cfg = load_config_dir(CONFIG_DIR)
    return {
        "staff": [
            {
                "staff_id":         s.staff_id,
                "name":             s.name,
                "role":             s.role.value,
                "skills":           sorted(s.skills),
                "max_weekly_hours": s.max_weekly_hours,
                "hourly_cost":      s.hourly_cost,
            }
            for s in cfg.staff
        ]
    }


@app.get("/api/roster")
def get_roster(
    week_start: date = Query(..., description="Monday of the week e.g. 2026-06-01"),
    week_end:   date = Query(..., description="Saturday of the week e.g. 2026-06-06"),
):
    """Generate a roster for the given week with no exceptions."""
    try:
        cfg    = load_config_dir(CONFIG_DIR)
        roster = build_roster(cfg, week_start, week_end)
        return _serialise_roster(roster)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/roster")
def get_roster_with_exceptions(
    week_start: date = Query(...),
    week_end:   date = Query(...),
    body: WeeklyExceptionsInput = None,
):
    """Generate a roster with weekly exceptions (days off, late starts, etc.)."""
    try:
        cfg    = load_config_dir(CONFIG_DIR)
        weekly = _build_weekly(body) if body else WeeklyInput()
        roster = build_roster(cfg, week_start, week_end, weekly=weekly)
        return _serialise_roster(roster)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))