"""
Scoring engine for assistant assignment.

Priority order (reflected in weights):
  1. Hours headroom     — 40pts  stay well under 40h/week
  2. Shift shape        — 30pts  8h on days 1-4, cap at 6h on day 5
  3. Dentist preference — 20pts  dentist's preferred assistants
  4. Usual day          — 15pts  is this normally their working day?
  5. Fairness           — 10pts  balance hours across staff
  6. Cost               —  5pts  lower cost preferred (tie-breaker)
"""
from __future__ import annotations
from dataclasses import dataclass, field

from roster.config.schema import AppConfig
from roster.domain.models import StaffMember
from roster.engine.availability import Availability
from roster.engine.demand import SessionDemand

MONDAY = 0  # weekday index


@dataclass
class Score:
    hours_headroom_score: float = 0.0
    shift_shape_score:    float = 0.0
    preference_score:     float = 0.0
    usual_day_score:      float = 0.0
    fairness_score:       float = 0.0
    cost_score:           float = 0.0
    total:                float = 0.0
    reasons:              list  = field(default_factory=list)


def score_candidate(
    candidate:          StaffMember,
    av:                 Availability,
    demand:             SessionDemand,
    provider_id:        int,
    cfg:                AppConfig,
    running_hours:      dict[str, float],
    already_assigned:   dict[int, str],
    session_date=None,
    days_worked_this_week: int = 0,
    required_skills_override=None,
) -> Score:
    score = Score()
    w = cfg.rules.scoring_weights
    ss = cfg.rules.shift_shape

    hours_this_session = av.available_hours
    hours_so_far = running_hours.get(candidate.staff_id, 0.0)
    max_weekly = candidate.max_weekly_hours
    projected = hours_so_far + hours_this_session

    # ── 1. Hours headroom (40pts) ─────────────────────────────────────────────
    # Hard filter already applied by assigner (projected > 40h = excluded).
    # Here we reward those with the most headroom remaining.
    headroom = max_weekly - hours_so_far
    headroom_ratio = min(headroom / max_weekly, 1.0) if max_weekly > 0 else 0.0
    score.hours_headroom_score = round(w.get("hours_headroom", 40) * headroom_ratio, 1)
    score.reasons.append(f"headroom {headroom:.1f}h remaining")

    # ── 2. Shift shape (30pts) ────────────────────────────────────────────────
    # Day 5 of their working week: target 4-6h, penalise longer sessions.
    # Days 1-4: target 8h, allow up to 9h without penalty.
    shape_weight = w.get("shift_shape", 30)
    is_fifth_day = (days_worked_this_week >= 4)

    if is_fifth_day:
        cap = ss.fifth_day_cap          # 6h
        target = ss.fifth_day_target    # 5h
        if hours_this_session <= cap:
            # Full score if this session fits within 6h cap
            score.shift_shape_score = round(shape_weight * 1.0, 1)
            score.reasons.append(f"day 5 — fits cap ({hours_this_session}h ≤ {cap}h)")
        else:
            score.shift_shape_score = 0.0
            score.reasons.append(f"day 5 — exceeds cap ({hours_this_session}h > {cap}h)")
    else:
        target = ss.standard_day_hours  # 8h
        max_ok = ss.standard_day_max    # 9h
        if hours_this_session <= max_ok:
            # Reward sessions close to 8h
            proximity = 1.0 - abs(hours_this_session - target) / target
            score.shift_shape_score = round(shape_weight * max(proximity, 0.0), 1)
            score.reasons.append(f"day {days_worked_this_week + 1} — {hours_this_session}h (target {target}h)")
        else:
            score.shift_shape_score = round(shape_weight * 0.3, 1)
            score.reasons.append(f"long day {hours_this_session}h")

    # ── 3. Dentist preference (20pts) ─────────────────────────────────────────
    pref_weight = w.get("preference", 20)
    dentist_by_prov = cfg.dentist_by_provider_id()
    dentist = dentist_by_prov.get(provider_id)
    dentist_sid = dentist.staff_id if dentist else None

    if dentist_sid:
        fixed   = cfg.rules.fixed_assistants.get(dentist_sid, [])
        prefs   = cfg.rules.dentist_preferences.get(dentist_sid, [])

        if candidate.staff_id in fixed:
            score.preference_score = round(pref_weight * 1.0, 1)
            score.reasons.append("fixed assistant")
        elif candidate.staff_id in prefs:
            rank = prefs.index(candidate.staff_id)
            score.preference_score = round(pref_weight * (1.0 - rank * 0.2), 1)
            score.reasons.append(f"preferred #{rank + 1}")
        else:
            score.preference_score = 0.0
            score.reasons.append("not in preference list")
    else:
        score.preference_score = round(pref_weight * 0.5, 1)
        score.reasons.append("no dentist preference configured")

    # ── 4. Usual working day (15pts) ──────────────────────────────────────────
    usual_weight = w.get("usual_day", 15)
    if session_date is not None:
        weekday = session_date.weekday()  # 0=Mon
        if weekday in (candidate.recurring_days_off or []):
            score.usual_day_score = 0.0
            score.reasons.append("not their usual day")
        else:
            score.usual_day_score = round(usual_weight * 1.0, 1)
            score.reasons.append("usual working day")
    else:
        score.usual_day_score = round(usual_weight * 0.5, 1)

    # ── 5. Fairness (10pts) ───────────────────────────────────────────────────
    utilisation = hours_so_far / max_weekly if max_weekly > 0 else 1.0
    score.fairness_score = round(w.get("fairness", 10) * (1.0 - utilisation), 1)
    score.reasons.append(f"utilisation {hours_so_far:.1f}/{max_weekly}h")

    # ── 6. Cost (5pts) ────────────────────────────────────────────────────────
    all_costs = [s.hourly_cost for s in cfg.assistants()]
    max_cost = max(all_costs) if all_costs else candidate.hourly_cost
    score.cost_score = round(
        w.get("cost", 5) * (1.0 - candidate.hourly_cost / max_cost)
        if max_cost > 0 else 0.0, 1
    )
    score.reasons.append(f"cost ${candidate.hourly_cost}/h")

    score.total = round(
        score.hours_headroom_score + score.shift_shape_score +
        score.preference_score + score.usual_day_score +
        score.fairness_score + score.cost_score, 2
    )
    return score
