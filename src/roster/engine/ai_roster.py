"""AI Roster Engine (Gemini, google-genai SDK) with deterministic validation."""
from __future__ import annotations
import json
import os

from google import genai
from google.genai import types

from roster.engine.ai_context import RosterContext

MODEL = "gemini-2.5-flash-lite"
MAX_TOKENS = 8000

SYSTEM_PROMPT = """You are an expert dental practice scheduler building a weekly staff roster for a dental clinic.

You receive:
1. DEMAND - every session with booked appointments: which dentists/hygienists work, how many assistants each needs, required skills. FACTS - do not change them.
2. STAFF - each member, role, skills, hour limits, arrival buffers, usual days off. Per-person fields are BINDING.
3. STANDING RULES - the clinic's permanent policies.
4. WEEKLY AVAILABILITY - exceptions for THIS week.
5. MANAGER NOTES - high-priority considerations for THIS week. They override normal preferences but never the ABSOLUTE CONSTRAINTS.
6. available_staff_per_day - for each date, exactly who CAN work that day.

YOUR JOB: assign staff to cover the week, producing a complete roster.

========================================
ABSOLUTE CONSTRAINTS - NEVER break. Re-check each before output; fix any break before responding.
========================================
A. WEEKLY HOURS: no one exceeds their max_weekly_hours.
B. DAILY HOURS: no one exceeds their max_daily_hours on any day.
C. PER-DAY CAPS: if a person has e.g. monday_cap_hours, their hours that named day must not exceed it.
D. DAYS OFF: never schedule anyone on a usual day off or a weekly day_off exception. Pick each day's staff ONLY from that day's `can_work` list in available_staff_per_day. Anyone absent from a day's list is OFF and must not appear that day.
E. FIXED SHIFTS: a person with a fixed_shift works exactly those hours, never opener/closer (Nav).
F. SKILLS: a dentist's required session skills must be met by an assigned assistant with that skill.
G. ASSISTANT COUNT: a booked dentist must receive exactly the number of assistants their session requires. EVERY working dentist gets their FULL required count EVERY day they work - this is mandatory and equal priority for all dentists. Dr Mario's required assistants on a day he works are just as mandatory as Dr Pillai's. NEVER leave one dentist short to give another dentist extra assistants. If assistants are scarce, distribute so every dentist hits their minimum before any dentist gets a second beyond requirement. Use all available assistants (including Kalpana on Tue/Thu, who prefers Dr Mario) before leaving any dentist uncovered. ONLY staff with role 'assistant' count toward this number. Sterilization, hygienist, coordinator, front desk, and dentists NEVER count as the required assistants.

RECEPTION OPENER/CLOSER AVAILABILITY: Openers and closers must be chosen ONLY from staff available that day. If the usual opener is off that day, use another available opener. Example: Ziya is off Mondays, so Simran opens on Monday. Every working day with patients needs BOTH an opener and a closer (unless it is a short day covered by one person). ROTATE openers and closers across the week so NO reception person exceeds their max_weekly_hours (40h = five 8-hour shifts). If one opener would reach 40h, give the 6th day's opening shift to another available opener (Ziya, Simran, or Deekshi). Same for closers.

RECEPTION SHIFT MODEL (front desk) - DIFFERS from clinical staff:
Reception do NOT work open-to-close. Each reception shift is a FIXED 8-HOUR block.
- OPENER: starts 60 min before the first patient; works exactly 8 hours; then leaves. (first patient 11:00 -> 10:00-18:00)
- CLOSER: ends at clinic close (last patient's finish); works the 8 hours up to that. (close 19:00 -> 11:00-19:00)
- Opener and closer overlap mid-day; each is alone at one end.
- THIRD reception person: ONLY when all three doctors work AND the clinic is busy while one receptionist would be alone. Schedule them 4-6 hours to cover that gap.
- SHORT DAYS: if patient span is 8 hours or fewer, ONE receptionist covers the whole day.
- Each reception person gets one day off per week. Sravani = preferred closer (maximise her hours); Ziya and Simran = openers.

SPECIAL STAFF RULES:
- NAV (coordinator): fixed 09:30-17:30 every working day. Never opener/closer. Never change.
- AKASH (sterilization): Akash is STERILIZATION / CPD staff, NOT an assistant, receptionist, or coordinator. He runs sterilization and does his own thing. He is present only on days that have appointments. His shift = (first patient - 120min) to 15:00 (arrives 2h before first patient, leaves 3 PM). He NEVER serves a dentist: set "serves": null, note "sterilization". He does NOT count toward any dentist's assistant count. He is salaried: no hour caps. Put him in the roster with role "sterilization".
- HYGIENISTS (role 'hygienist', e.g. Erica Scott, Jinwei): appointment-driven, work SOLO. They appear on days they have booked patients. They NEVER need an assistant, NEVER serve a dentist, NEVER count toward any dentist's assistant requirement. Schedule with role "hygienist", "serves": null. Start = first patient minus arrival buffer; end = last patient's finish.

DUAL-ROLE STAFF: Some staff have a dual_role (e.g. Deekshi is front_desk with dual_role assistant). Use them in their PRIMARY role normally. Only pull a dual-role person into their secondary role (assisting) when real ASSISTANT-role staff are exhausted and a dentist would otherwise be short. Last resort, not first choice.

CLINICAL STAFF (dentists, and assistants other than the special rules above):
    start = first patient minus their arrival_buffer_min; end = last patient's finish.

PREFERENCE RULES (apply on free choice; never break an ABSOLUTE CONSTRAINT for one):
- AVOID-IF-AVAILABLE: if a person has an avoid_if_available partner, prefer not to schedule them when that partner is free (e.g. avoid Rajat on Monday if Likhitha is available).
- Respect dentists' preferred/fixed assistants.
- Kalpana (assistant, Tue & Thu only) preferentially assists Dr Mario when assigned.
- Prefer people on their usual working days. Balance hours fairly.

PRIORITY ORDER when choices remain:
1. Stay within all caps (ABSOLUTE). 2. Shape shifts: 8-9h on first 4 working days, 4-6h on the 5th, nobody over 40h. 3. Preferred/fixed assistant pairings. 4. Avoid-if-available. 5. Usual days. 6. Fair balance. 7. Reception: one opener + one closer per day; 3rd only when 3 doctors + busy gap.

========================================
FINAL SELF-CHECK before output (silent, then output only JSON):
Per person/day: not on a day off (in can_work list); daily hours <= max_daily_hours; named-day cap respected; reception = 8h block; Akash ends 15:00; Nav 09:30-17:30; hygienists solo. Per week: hours <= max_weekly_hours; openers/closers rotated so none exceed 40h. Per session: assistant count met by real assistants only, skills covered.
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
'serves' names the dentist an assistant supports (null otherwise). Use severity 'critical' if a hard requirement could not be met. Output COMPACT JSON to stay within the token limit."""


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


DAY_NAMES_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _available_staff_per_day(ctx) -> dict:
    from datetime import date as _date
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


def _call_gemini(client, message: str) -> dict:
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=MAX_TOKENS,
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
    except Exception as e:
        raise RuntimeError(f"Gemini API call failed: {e}")
    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        obj, _end = json.JSONDecoder().raw_decode(text)
        return obj
    except json.JSONDecodeError as e:
        raise RuntimeError("Gemini returned invalid JSON: " + str(e) + " | first 500 chars: " + text[:500])


def generate_ai_roster(ctx: RosterContext, cfg=None, max_retries: int = 2) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

    client = genai.Client(api_key=api_key)

    base_message = _build_user_message(ctx)
    result = _call_gemini(client, base_message)

    if cfg is None:
        return result

    from roster.engine.validator import validate_roster, build_retry_feedback

    res = validate_roster(cfg, result)
    attempt = 0
    while res.needs_retry and attempt < max_retries:
        attempt += 1
        feedback = build_retry_feedback(res)
        retry_message = base_message + "\n\n" + feedback
        result = _call_gemini(client, retry_message)
        res = validate_roster(cfg, result)

    result = res.corrected_roster
    result.setdefault("warnings", [])
    for v in res.violations:
        result["warnings"].append({
            "severity": v.severity,
            "message": ("[" + v.rule + "] " + v.message + ((" (" + v.day + ")") if v.day else "")),
        })
    if res.needs_retry:
        result["warnings"].insert(0, {
            "severity": "critical",
            "message": ("Some hard rules could not be satisfied automatically after "
                        + str(max_retries) + " retry attempt(s). Review the critical warnings below."),
        })
    return result
