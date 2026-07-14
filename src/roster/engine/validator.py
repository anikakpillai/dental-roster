"""Deterministic roster validator. AI proposes; this ENFORCES + AUTO-CORRECTS hard rules."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date

from roster.config.schema import AppConfig

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_CAP_FIELDS = {0: "monday_cap_hours"}

# Salaried/monthly: fixed schedule, no hourly caps. Day-off still applies.
SALARIED_EXEMPT = {"A_AKASH"}


@dataclass
class Violation:
    severity: str
    staff_id: str
    name: str
    day: str
    rule: str
    message: str


@dataclass
class ValidationResult:
    violations: list = field(default_factory=list)
    corrected_roster: dict = field(default_factory=dict)
    needs_retry: bool = False

    @property
    def criticals(self):
        return [v for v in self.violations if v.severity == "critical"]


def _hm(s: str) -> int:
    """Time string 'HH:MM' -> minutes since midnight (for comparisons)."""
    try:
        hh, mm = [int(x) for x in str(s).split(":")]
        return hh * 60 + mm
    except Exception:
        return 0


def _parse_hours(start: str, end: str) -> float:
    try:
        sh, sm = [int(x) for x in str(start).split(":")]
        eh, em = [int(x) for x in str(end).split(":")]
        h = (eh + em / 60.0) - (sh + sm / 60.0)
        return round(h if h >= 0 else h + 24, 2)
    except Exception:
        return 0.0


def _trim_end(start: str, cap_hours: float) -> str:
    """Return an end time so that end-start == cap_hours."""
    try:
        sh, sm = [int(x) for x in str(start).split(":")]
        total = sh * 60 + sm + int(round(cap_hours * 60))
        eh, em = divmod(total, 60)
        return f"{eh:02d}:{em:02d}"
    except Exception:
        return start


def validate_roster(cfg: AppConfig, ai_result: dict, weekly=None) -> ValidationResult:
    staff_by_id = cfg.staff_by_id()
    res = ValidationResult(corrected_roster=ai_result, needs_retry=False)
    weekly_hours = {}

    for day in ai_result.get("roster", []):
        day_iso = day.get("date", "")
        try:
            day_date = date.fromisoformat(day_iso)
            weekday = day_date.weekday()
        except Exception:
            day_date = None
            weekday = None

        kept = []
        for entry in day.get("staff", []):
            sid = entry.get("staff_id", "")
            staff = staff_by_id.get(sid)
            name = entry.get("name", sid)
            start = entry.get("start", "")
            end = entry.get("end", "")
            hours = _parse_hours(start, end)

            if staff is None:
                res.violations.append(Violation(
                    "warning", sid, name, day_iso, "UNKNOWN_STAFF",
                    f"{name} ({sid}) is not in the staff config."))
                kept.append(entry)
                continue

            role = getattr(staff, "role", None)
            role_val = getattr(role, "value", str(role))
            is_dentist = role_val == "dentist"
            exempt_hours = is_dentist or sid in SALARIED_EXEMPT

            # Fixed shift auto-correct (Nav)
            shift_start = getattr(staff, "shift_start", None)
            shift_end = getattr(staff, "shift_end", None)
            if shift_start and shift_end and (start != shift_start or end != shift_end):
                res.violations.append(Violation(
                    "warning", sid, name, day_iso, "FIXED_SHIFT",
                    f"{name} fixed shift {shift_start}-{shift_end}; was {start}-{end}. Auto-corrected."))
                entry["start"], entry["end"] = shift_start, shift_end
                start, end = shift_start, shift_end
                hours = _parse_hours(start, end)

            # DAY OFF -> auto-remove (dentists exempt: their book is truth)
            days_off = getattr(staff, "recurring_days_off", None) or []
            if not is_dentist and weekday is not None and weekday in days_off:
                res.violations.append(Violation(
                    "critical", sid, name, day_iso, "DAY_OFF_REMOVED",
                    f"{name} was scheduled on {DAY_NAMES[weekday]} (their day off) and was removed. "
                    f"Replace them with an available person of the same role so {DAY_NAMES[weekday]} stays covered."))
                continue  # drop entry

            # WEEKLY EXCEPTIONS (manager overrides for THIS week).
            #   Support staff: exception is authoritative (they are NOT in Open Dental).
            #   Dentists: Open Dental wins (their booked patients are truth) -> keep + flag.
            if weekly is not None and day_date is not None:
                if weekly.is_off(sid, day_date):
                    if is_dentist:
                        res.violations.append(Violation(
                            "warning", sid, name, day_iso, "EXCEPTION_CONFLICT",
                            f"You marked {name} OFF on {DAY_NAMES[weekday]}, but Open Dental shows "
                            f"them with booked appointments. Kept per Open Dental — resolve in OD if they are truly off."))
                    else:
                        res.violations.append(Violation(
                            "critical", sid, name, day_iso, "EXCEPTION_DAY_OFF_REMOVED",
                            f"{name} was marked OFF this {DAY_NAMES[weekday]} (weekly exception) and was removed. "
                            f"Replace with an available person of the same role so {DAY_NAMES[weekday]} stays covered."))
                        continue  # drop entry

                # Late start: don't begin before the exception time (support staff only).
                lt = weekly.late_start(sid, day_date)
                if lt is not None and not is_dentist:
                    lt_s = lt.strftime("%H:%M")
                    if _hm(start) < _hm(lt_s):
                        res.violations.append(Violation(
                            "warning", sid, name, day_iso, "EXCEPTION_LATE_START",
                            f"{name} starts no earlier than {lt_s} this {DAY_NAMES[weekday]} (weekly exception); "
                            f"was {start}. Adjusted to {lt_s}-{end}."))
                        entry["start"] = lt_s
                        start = lt_s
                        hours = _parse_hours(start, end)

                # Early finish: don't run past the exception time (support staff only).
                ef = weekly.early_finish(sid, day_date)
                if ef is not None and not is_dentist:
                    ef_s = ef.strftime("%H:%M")
                    if _hm(end) > _hm(ef_s):
                        res.violations.append(Violation(
                            "warning", sid, name, day_iso, "EXCEPTION_EARLY_FINISH",
                            f"{name} finishes by {ef_s} this {DAY_NAMES[weekday]} (weekly exception); "
                            f"was {end}. Adjusted to {start}-{ef_s}."))
                        entry["end"] = ef_s
                        end = ef_s
                        hours = _parse_hours(start, end)

            # Hour caps (skip dentists + salaried)
            if not exempt_hours:
                max_daily = getattr(staff, "max_daily_hours", None)
                if max_daily and hours > max_daily + 0.01:
                    new_end = _trim_end(start, max_daily)
                    res.violations.append(Violation(
                        "warning", sid, name, day_iso, "DAILY_CAP_TRIMMED",
                        f"{name} was {hours}h on {DAY_NAMES[weekday]}, over daily max {max_daily}h; "
                        f"trimmed to {start}-{new_end}."))
                    entry["end"] = new_end
                    end = new_end
                    hours = _parse_hours(start, end)

                if weekday is not None and weekday in DAY_CAP_FIELDS:
                    cap = getattr(staff, DAY_CAP_FIELDS[weekday], None)
                    if cap and hours > cap + 0.01:
                        new_end = _trim_end(start, cap)
                        res.violations.append(Violation(
                            "warning", sid, name, day_iso, "DAY_CAP_TRIMMED",
                            f"{name} was {hours}h on {DAY_NAMES[weekday]}, over {DAY_NAMES[weekday]} "
                            f"cap {cap}h; trimmed to {start}-{new_end}."))
                        entry["end"] = new_end
                        end = new_end
                        hours = _parse_hours(start, end)

            weekly_hours[sid] = weekly_hours.get(sid, 0.0) + hours
            kept.append(entry)

        day["staff"] = kept

    # WEEKLY CAP (skip dentists + salaried) -> flag for retry
    for sid, total in weekly_hours.items():
        staff = staff_by_id.get(sid)
        if not staff or sid in SALARIED_EXEMPT:
            continue
        role_val = getattr(getattr(staff, "role", None), "value", "")
        if role_val == "dentist":
            continue
        max_weekly = getattr(staff, "max_weekly_hours", None)
        if max_weekly and total > max_weekly + 0.01:
            res.violations.append(Violation(
                "critical", sid, staff.name, "", "WEEKLY_CAP",
                f"{staff.name} is scheduled {round(total,1)}h this week, over weekly max {max_weekly}h."))

    res.needs_retry = len(res.criticals) > 0
    return res


def build_retry_feedback(res: ValidationResult) -> str:
    if not res.criticals:
        return ""
    lines = [
        "Your previous roster broke these HARD rules. Produce a corrected roster "
        "that fixes every one while keeping other assignments as close as possible:",
    ]
    for v in res.criticals:
        where = f" on {v.day}" if v.day else ""
        lines.append(f"- {v.message}{where}")
    lines.append("\nReassign to other available staff. Do not introduce new violations. "
                 "Return the full corrected roster JSON.")
    return "\n".join(lines)