"""AI Roster Engine (Gemini) with deterministic validation."""
from __future__ import annotations
import json
import os

import google.generativeai as genai

from roster.engine.ai_context import RosterContext

MODEL = "gemini-2.5-flash-lite"
MAX_TOKENS = 8000

SYSTEM_PROMPT = """You are an expert dental practice scheduler building a weekly staff roster for a dental clinic.

You receive:
1. DEMAND — every session that has booked appointments, which dentists are working, how many assistants each needs, and what skills are required. These are FACTS. Do not change them.
2. STAFF — each team member, their role, skills, hour limits, arrival buffers, and usual days off. Per-person fields are BINDING limits.
3. STANDING RULES — the clinic's permanent policies.
4. WEEKLY AVAILABILITY — exceptions for THIS week.
5. MANAGER NOTES — high-priority considerations for THIS week. They override normal preferences but never the ABSOLUTE CONSTRAINTS.

YOUR JOB: assign staff to cover the week, producing a complete roster.

========================================
ABSOLUTE CONSTRAINTS — NEVER break. Re-check each before output; fix any break before responding.
========================================
A. WEEKLY HOURS: no one exceeds their max_weekly_hours.
B. DAILY HOURS: no one exceeds their max_daily_hours on any day.
C. PER-DAY CAPS: if a person has e.g. monday_cap_hours, their hours that named day must not exceed it (even if below their normal daily max).
D. DAYS OFF: never schedule anyone on a usual day off or a weekly day_off exception. The input includes `available_staff_per_day`: for each date it lists exactly who CAN work (`can_work`). You MUST pick each day's staff ONLY from that day's `can_work` list. Anyone absent from a day's list is OFF and must not appear that day.
E. FIXED SHIFTS: a person with a fixed_shift works exactly those hours, never opener/closer (Nav).
F. SKILLS: a dentist's required session skills must be met by an assigned assistant with that skill.
G. ASSISTANT COUNT: a booked dentist gets exactly the number of assistants their session requires.

RECEPTION SHIFT MODEL (front desk) — this DIFFERS from clinical staff:
Reception staff do NOT work open-to-close. Each reception shift is a FIXED 8-HOUR block.
- OPENER: starts 60 min before the first patient; works exactly 8 hours; then leaves.
    Example: first patient 11:00 -> opener 10:00-18:00.
- CLOSER: ends at clinic close (last patient's finish); works the 8 hours up to that.
    Example: clinic closes 19:00 -> closer 11:00-19:00.
- Opener and closer overlap mid-day; each is alone at one end.
- THIRD reception person: ONLY when all three doctors work AND the clinic is busy while
    just one receptionist would be present. Schedule them 4-6 hours to cover that gap.
- SHORT DAYS: if the clinic's patient span is 8 hours or fewer, ONE receptionist covers
    the whole day (no 8-hour rule, no second person unless busy + 3 doctors).
- Each reception person gets one day off per week. Sravani = preferred closer (maximise
    her hours); Ziya and Simran = openers.

SPECIAL STAFF RULES:
- NAV (coordinator): fixed 09:30-17:30 every working day. Never opener/closer. Never change.
- AKASH (assistant): SALARIED / paid monthly. NONE of the hourly caps (daily, weekly, Monday) apply to him. Fixed schedule: arrives 120 min before the first patient and ALWAYS leaves at 15:00 (3 PM). Works Mon-Wed only. Shift = (first patient - 120min) to 15:00. Never flag him for hours.
- RAJAT (assistant): flexible fill-in. He may be brought in for 4-6 hours ONLY when genuinely needed; AVOID using him otherwise (prefer other available assistants first). Keep any Monday hours within his 6h Monday cap. If a skill gap can only be closed by extending Rajat, leave it as a flagged warning rather than forcing him to stay.

CLINICAL STAFF (dentists, and assistants other than the special rules above):
    start = first patient minus their arrival_buffer_min; end = last patient's finish.

PREFERENCE RULES (apply on free choice; never break an ABSOLUTE CONSTRAINT for one):
- AVOID-IF-AVAILABLE: if a person has an avoid_if_available partner, prefer not to schedule
    them when that partner is free (e.g. avoid Rajat on Monday if Likhitha is available).
- Respect dentists' preferred/fixed assistants. Prefer usual working days. Balance hours fairly.

PRIORITY ORDER when choices remain:
1. Stay within all caps (ABSOLUTE).
2. Shape shifts: 8-9h on first 4 working days, 4-6h on the 5th, nobody over 40h.
3. Preferred/fixed assistant pairings. 4. Avoid-if-available. 5. Usual days. 6. Fair balance.
7. Reception: one opener + one closer per day; 3rd only when 3 doctors + busy gap.

========================================
FINAL SELF-CHECK before output (silent, then output only JSON):
Per person/day: not on a day off; daily hours <= max_daily_hours; named-day cap respected;
reception = 8h block (opener first-patient-60min start; closer ends at close); Akash ends 15:00;
Nav 09:30-17:30. Per week: hours <= max_weekly_hours. Per session: assistant count + skills covered.
Fix any failure before outputting. Note unavoidable tradeoffs in "warnings".
========================================

OUTPUT FORMAT: return ONLY valid JSON, no prose, no markdown fences:
{
  "roster": [
    {"date": "2026-06-22", "weekday": "Monday", "staff": [
        {"staff_id": "D_PILLAI", "name": "Dr Pillai", "role": "dentist", "start": "09:00", "end": "17:00", "serves": null, "note": ""},
        {"staff_id": "A_RISHABH", "name": "Rishabh", "role": "assistant", "start": "08:30", "end": "17:00", "serves": "Dr Pillai", "note": "chairside"}
    ]}
  ],
  "warnings": [{"severity": "critical|warning|info", "message": "..."}],
  "summary": "One short paragraph explaining the week's roster and any tradeoffs."
}
'serves' names the dentist an assistant supports (null otherwise). Use severity 'critical' if a hard requirement could not be met. Output COMPACT JSON on as few lines as possible (no unnecessary whitespace or indentation) to stay within the token limit."""


DAY_NAMES_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _available_staff_per_day(ctx) -> dict:
    """Per-date list of staff who CAN work that day, from usual days off +
    this week's day_off exceptions. The AI must pick only from these pools."""
    from datetime import date as _date
    # weekly day_off exceptions -> {(name, iso_date)}
    exc_off = set()
    for item in ctx.weekly_availability:
        if item.get("type") == "day_off":
            exc_off.add((item.get("staff"), item.get("date")))

    out = {}
    ws = _date.fromisoformat(ctx.week_start)
    we = _date.fromisoformat(ctx.week_end)
    cur = ws
    while cur <= we:
        wd_name = DAY_NAMES_FULL[cur.weekday()]
        iso = cur.isoformat()
        can = []
        for s in ctx.staff_briefing:
            if wd_name in (s.get("usual_days_off") or []):
                continue
            if (s.get("name"), iso) in exc_off:
                continue
            can.append(s.get("staff_id"))
        out[iso] = {"weekday": wd_name, "can_work": can}
        cur = _date.fromordinal(cur.toordinal() + 1)
    return out


def _build_user_message(ctx: RosterContext) -> str:
    payload = {
        "week_start": ctx.week_start,
        "week_end": ctx.week_end,
        "clinic": ctx.clinic_name,
        "demand": ctx.demand_summary,
        "staff": ctx.staff_briefing,
        "standing_rules": ctx.standing_rules,
        "weekly_availability": ctx.weekly_availability,
        "available_staff_per_day": _available_staff_per_day(ctx),
        "manager_notes": ctx.manager_notes or "(none this week)",
    }
    return (
        "Build the roster for this week using the data below. "
        "Obey every ABSOLUTE CONSTRAINT and the RECEPTION SHIFT MODEL, and run the "
        "FINAL SELF-CHECK before responding. Pay special attention to MANAGER NOTES.\n\n"
        + json.dumps(payload, indent=2)
    )


def _call_gemini(model, message: str) -> dict:
    try:
        response = model.generate_content(message)
    except Exception as e:
        raise RuntimeError(f"Gemini API call failed: {e}")
    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        # raw_decode parses the first valid JSON object and ignores any
        # trailing junk the model may append after the closing brace.
        obj, _end = json.JSONDecoder().raw_decode(text)
        return obj
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned invalid JSON: {e}\nFirst 500 chars:\n{text[:500]}")


def generate_ai_roster(ctx: RosterContext, cfg=None, max_retries: int = 2) -> dict:
    """AI proposes, the validator enforces hard rules. Pass cfg in production."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=SYSTEM_PROMPT,
        generation_config={
            "max_output_tokens": MAX_TOKENS,
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

    base_message = _build_user_message(ctx)
    result = _call_gemini(model, base_message)

    if cfg is None:
        return result

    from roster.engine.validator import validate_roster, build_retry_feedback

    res = validate_roster(cfg, result)
    attempt = 0
    while res.needs_retry and attempt < max_retries:
        attempt += 1
        feedback = build_retry_feedback(res)
        retry_message = base_message + "\n\n" + feedback
        result = _call_gemini(model, retry_message)
        res = validate_roster(cfg, result)

    result = res.corrected_roster
    result.setdefault("warnings", [])
    for v in res.violations:
        result["warnings"].append({
            "severity": v.severity,
            "message": (f"[{v.rule}] " + v.message + (f" ({v.day})" if v.day else "")),
        })
    if res.needs_retry:
        result["warnings"].insert(0, {
            "severity": "critical",
            "message": (f"Some hard rules could not be satisfied automatically after "
                        f"{max_retries} retry attempt(s). Review the critical warnings below."),
        })
    return result
