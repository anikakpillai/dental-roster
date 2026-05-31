"""
The 'what to ask' layer.

Pulls providers and appointments out of Open Dental and converts them
into clean domain models. PII protection lives here: we only SELECT the
columns we actually need — never patient name, DOB, phone, fee, or notes.
"""
from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import text

from roster.db.connection import get_engine
from roster.db.pattern import parse_pattern
from roster.domain.models import AppointmentMeta, DayPart

_ACTIVE_STATUSES = (1, 2)   # 1=Scheduled, 2=Complete
_MORNING_CUTOFF_HOUR = 13


def _daypart_for(dt: datetime) -> DayPart:
    return DayPart.MORNING if dt.hour < _MORNING_CUTOFF_HOUR else DayPart.AFTERNOON


def _session_key(dt: datetime) -> str:
    return f"{dt.date().isoformat()}|{_daypart_for(dt).value}"


def get_providers() -> list[dict]:
    """Return active providers (dentists + hygienists)."""
    sql = text("""
        SELECT ProvNum, Abbr, FName, LName, IsHygienist
        FROM provider
        WHERE IsHidden = 0
        ORDER BY ProvNum
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql).mappings().all()
    return [
        {
            "provider_id": r["ProvNum"],
            "abbr": r["Abbr"],
            "name": f"{r['FName']} {r['LName']}".strip(),
            "is_hygienist": bool(r["IsHygienist"]),
        }
        for r in rows
    ]


def get_week_appointments(week_start: date, week_end: date) -> list[AppointmentMeta]:
    """
    Return scheduling metadata for every active appointment in the range.
    Only metadata columns are selected — zero patient identifiers.
    """
    sql = text("""
        SELECT AptNum, AptStatus, AptDateTime, Pattern, Op,
               ProvNum, ProvHyg, ProcDescript
        FROM appointment
        WHERE AptStatus IN :statuses
          AND DATE(AptDateTime) BETWEEN :start AND :end
        ORDER BY AptDateTime
    """).bindparams(__import__("sqlalchemy").bindparam("statuses", expanding=True))

    with get_engine().connect() as conn:
        rows = conn.execute(
            sql,
            {"statuses": list(_ACTIVE_STATUSES), "start": week_start, "end": week_end},
        ).mappings().all()

    appointments: list[AppointmentMeta] = []
    for r in rows:
        dt: datetime = r["AptDateTime"]
        timing = parse_pattern(r["Pattern"])
        prov = r["ProvNum"] if r["ProvNum"] and r["ProvNum"] != 0 else None
        hyg = r["ProvHyg"] if r["ProvHyg"] and r["ProvHyg"] != 0 else None
        appointments.append(
            AppointmentMeta(
                apt_id=r["AptNum"],
                session_key=_session_key(dt),
                provider_id=prov,
                hygienist_id=hyg,
                operatory=str(r["Op"]),
                duration_min=timing.total_min,
                assistant_min=timing.assistant_min,
                procedure_category=r["ProcDescript"],
            )
        )
    return appointments
