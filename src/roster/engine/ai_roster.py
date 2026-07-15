"""AI Roster Engine (Gemini, google-genai SDK) with deterministic validation."""
from __future__ import annotations
import json
import os
import re
import time

from google import genai
from google.genai import types

from roster.engine.ai_context import RosterContext

MODEL = "gemini-2.5-flash"
MAX_TOKENS = 16000

SYSTEM_PROMPT = """You are an expert dental practice scheduler building a weekly staff roster for a dental clinic.

You receive:
1. DEMAND - every session with booked appointments: which dentists/hygienists work, how many assistants each needs, required skills. FACTS - do not change them.
2. STAFF - each member, role, skills, hour limits, arrival buffers, usual days off. Per-person fields are BINDING.
3. STANDING RULES - the clinic's permanent policies.
4. WEEKLY AVAILABILITY - exceptions for THIS week.
5. MANAGER NOTES - high-priority considerations for THIS week. They override normal preferences but never the ABSOLUTE CONSTRAINTS.
6. available_staff_per_day - for each date, exactly who CAN work that day.

YOUR JOB: assign staff to cover the week, producing a complete roster. CRITICAL: every shift must be justified by the DEMAND data. A dentist appears ONLY on days where DEMAND shows they have booked appointments - NEVER invent shifts for providers with no appointments that day. Appointment-driven staff (Akash) likewise only appear on days the clinic has appointments.

========================================
ABSOLUTE CONSTRAINTS - NEVER break. Re-check each before output; fix any break before responding.
========================================
A0. SHIFT ARITHMETIC: before writing any shift, compute (end - start) in hours and confirm it matches the intended length and does not exceed that person's max_daily_hours. A morning session is ~5h, an afternoon ~4h, a full clinical day ~8-9h - never more. Never output a shift you have not arithmetic-checked, a start earlier than (first patient - arrival_buffer_min), or an end later than the last patient's finish.
A1. DENTIST FACTS: dentist_days_FACTS lists, for each date, exactly which dentists work and their true span (first to last booked patient). Copy these EXACTLY: schedule each listed dentist on that date with that start and end; never add a dentist to a day they are not listed, never omit a listed dentist, never change their times. Assistants serve within their dentist's listed span.
A. WEEKLY HOURS: no one exceeds their max_weekly_hours.
B. DAILY HOURS: no one exceeds their max_daily_hours on any day.
C. PER-DAY CAPS: if a person has e.g. monday_cap_hours, their hours that named day must not exceed it.
D. DAYS OFF: never schedule anyone on a usual day off or a weekly day_off exception. Pick each day's staff ONLY from that day's `can_work` list in available_staff_per_day. Anyone absent from a day's list is OFF and must not appear that day.
E. FIXED SHIFTS: a person with a fixed_shift works exactly those hours, never opener/closer (Nav).
F. SKILLS: a dentist's required session skills must be met by an assigned assistant with that skill.
G. ASSISTANT COUNT: a booked dentist must receive exactly the number of assistants their session requires. EVERY working dentist gets their FULL required count EVERY day they work - this is mandatory and equal priority for all dentists. Dr Mario's required assistants on a day he works are just as mandatory as Dr Pillai's. NEVER leave one dentist short to give another dentist extra assistants. If assistants are scarce, distribute so every dentist hits their minimum before any dentist gets a second beyond requirement. Use all available assistants (including Kalpana on Tue/Thu, who prefers Dr Mario) before leaving any dentist uncovered. ONLY staff with role 'assistant' count toward this number. Sterilization, hygienist, coordinator, front desk, and dentists NEVER count as the required assistants.

RECEPTION OPENER/CLOSER AVAILABILITY: Openers and closers must be chosen ONLY from staff available that day. If the usual opener is off that day, use another available opener. Example: Ziya is off Mondays, so Simran opens on Monday. Every working day with patients needs BOTH an opener and a closer (unless it is a short day covered by one person). ROTATE openers and closers across the week so NO reception person exceeds their max_weekly_hours (40h = five 8-hour shifts). If one opener would reach 40h, give the 6th day's opening shift to another available opener (Ziya, Simran, or Deekshi). Same for closers.

RECEPTION SHIFT MODEL (front desk) - DIFFERS from clinical staff:
 ALL reception times are computed from the DEMAND data for that day: 'first patient' = the day's earliest appointment start in DEMAND; 'clinic close' = the day's latest appointment end in DEMAND. NEVER assume or invent opening/closing times. OPENER = (first patient - 60min) for exactly 8 hours. CLOSER = the 8 hours ending exactly at clinic close. WORKED EXAMPLE: close 17:00 -> closer works 09:00-17:00 (8h ENDING at close). A closer NEVER starts at closing time; 16:00-20:00 or 17:00-21:00 are WRONG. If the day's span (first patient - 60min through close) is 8 hours or fewer, ONE receptionist covers it: (first patient - 60min) to close.

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

DUAL-ROLE STAFF: Some staff have a dual_role (e.g. Deekshi is front_desk with dual_role assistant). Use them in their PRIMARY role normally. Only pull a dual-role person into their secondary role (assisting) when real ASSISTANT-role staff are exhausted and a dentist would otherwise be short. Last resort, not first choice.

CLINICAL STAFF (dentists, and assistants other than the special rules above):
 PER-PROVIDER SPANS: each dentist's day runs from THEIR OWN first appointment to THEIR OWN last appointment (per DEMAND), NOT the clinic-wide span. If Dr Pillai's patients end 17:00, he ends 17:00. Assistants follow THEIR dentist's span, not the clinic's.

    start = first patient minus their arrival_buffer_min; end = last patient's finish.

PREFERENCE RULES (apply on free choice; never break an ABSOLUTE CONSTRAINT for one):
- AVOID-IF-AVAILABLE: if a person has an avoid_if_available partner, prefer not to schedule them when that partner is free (e.g. avoid Rajat on Monday if Likhitha is available).
- Respect dentists' preferred/fixed assistants.
- Kalpana (assistant, Tue & Thu only) preferentially assists Dr Mario when assigned.
- Prefer people on their usual working days. Balance hours fairly.

PRIORITY ORDER when choices remain:
1. Stay within all caps (ABSOLUTE). 2. Shape shifts: 8-9h on first 4 working days, 4-6h on the 5th, nobody over 40h. 3. Preferred/fixed assistant pairings. 4. Avoid-if-available. 5. Usual days. 6. Fair balance. 7. Reception: one opener + one closer per day; 3rd only when 3 doctors + busy gap.

========================================
BACKFILL RULE: if your draft had someone on their day off, do not simply delete them - REPLACE them with an available person of the same role from that day's can_work list. Every working day must end up with: an opener, a closer (or one person on short days), and every working dentist's full assistant count. Check Monday especially: Ziya is off Monday, so Simran opens Monday; if Rishabh is off Monday, use Pari or another available assistant for Dr Pillai.

FINAL SELF-CHECK before output (silent, then output only JSON):
Per person/day: not on a day off (in can_work list); daily hours <= max_daily_hours; named-day cap respected; reception = 8h block; Akash ends 15:00; Nav 09:30-17:30. Per week: hours <= max_weekly_hours; openers/closers rotated so none exceed 40h. Per session: assistant count met by real assistants only, skills covered.
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
'serves' names the dentist an assistant supports (null otherwise). 'serves' must be EXACTLY a dentist's name (e.g. "Dr Mario") or null - never notes like 'specialty: Tue/Thu'; put remarks in 'note'. Use severity 'critical' if a hard requirement could not be met. Output COMPACT JSON to stay within the token limit."""


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
    if getattr(ctx, "dentist_days", None):
        payload["dentist_days_FACTS"] = ctx.dentist_days
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


def _repair_json(text: str) -> str:
    """Fix the small syntax slips LLMs commonly make, without altering data.
    Handles: trailing commas before } or ], stray control chars, smart quotes."""
    t = text
    # Smart quotes -> plain (models sometimes emit them in notes)
    t = t.translate({0x201c: 34, 0x201d: 34, 0x2018: 39, 0x2019: 39})
    # Remove trailing commas:  {"a":1,}  or  [1,2,]
    t = re.sub(r",(\s*[}\]])", r"\1", t)
    # Strip raw control characters that are illegal inside JSON strings
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    return t


def _extract_json(text: str) -> dict:
    """Parse a model response into a dict, tolerating fences, prose, and minor
    syntax slips. Raises json.JSONDecodeError if nothing usable is present."""
    t = text.strip()
    _fence = chr(96) * 3
    if _fence in t:
        parts = t.split(_fence)
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                t = p
                break
    # Trim any prose before/after the JSON object
    i = t.find("{")
    if i > 0:
        t = t[i:]
    for candidate in (t, _repair_json(t)):
        try:
            obj, _end = json.JSONDecoder().raw_decode(candidate)
            return obj
        except json.JSONDecodeError as e:
            last = e
    raise last


# Google-side transient errors worth waiting out (overload / rate limit / 5xx).
_TRANSIENT = ("503", "UNAVAILABLE", "overload", "high demand", "429",
              "RESOURCE_EXHAUSTED", "500", "INTERNAL", "deadline", "timeout")

def _is_transient(err: str) -> bool:
    e = err.lower()
    return any(t.lower() in e for t in _TRANSIENT)

def _call_gemini(client, message: str) -> dict:
    response = None
    delays = [2, 5, 10]  # backoff seconds between attempts on transient errors
    for attempt in range(len(delays) + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=message,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=MAX_TOKENS,
                    temperature=0.2,
                    response_mime_type="application/json",
                    # gemini-2.5-flash thinks by default and thinking tokens count
                    # against max_output_tokens -> truncated JSON. Disable it: the
                    # full budget goes to the roster, and responses are much faster.
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            break
        except Exception as e:
            msg = str(e)
            if _is_transient(msg) and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            if _is_transient(msg):
                raise RuntimeError(
                    "Gemini is temporarily busy (Google-side overload). "
                    "Please click Build again in a few seconds.")
            raise RuntimeError(f"Gemini API call failed: {e}")
    return _extract_json(response.text or "")


def _call_gemini_json(client, message: str, tries: int = 3) -> dict:
    """Call Gemini and parse JSON, retrying on malformed/truncated output.
    LLM output varies run-to-run, so a fresh attempt usually succeeds."""
    last = None
    for _ in range(max(1, tries)):
        try:
            return _call_gemini(client, message)
        except json.JSONDecodeError as e:
            last = e
            continue
        except Exception as e:
            raise RuntimeError(f"Gemini API call failed: {e}")
    raise RuntimeError("Gemini returned invalid JSON after retries: " + str(last))


def generate_ai_roster(ctx: RosterContext, cfg=None, weekly=None, dentist_truth=None, max_retries: int = 2) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

    client = genai.Client(api_key=api_key)

    base_message = _build_user_message(ctx)
    result = _call_gemini_json(client, base_message)

    if cfg is None:
        return result

    from roster.engine.validator import validate_roster, build_retry_feedback

    res = validate_roster(cfg, result, weekly=weekly, dentist_truth=dentist_truth)
    attempt = 0
    while res.needs_retry and attempt < max_retries:
        attempt += 1
        feedback = build_retry_feedback(res)
        retry_message = base_message + "\n\n" + feedback
        result = _call_gemini_json(client, retry_message)
        res = validate_roster(cfg, result, weekly=weekly, dentist_truth=dentist_truth)

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


