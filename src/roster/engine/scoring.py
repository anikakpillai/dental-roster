"""
Stage 3 of the engine: Scoring.

For each open assistant slot, scores every available candidate.
Higher score = better fit. Every score is explainable.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from roster.config.schema import AppConfig
from roster.domain.models import StaffMember
from roster.engine.availability import Availability
from roster.engine.demand import SessionDemand


@dataclass
class ScoreBreakdown:
    """The score for one candidate for one slot. Fully explainable."""
    staff_id:    str
    total:       float
    reasons:     list[str] = field(default_factory=list)

    # Individual component scores (stored for transparency/debugging)
    preference_score:   float = 0.0
    skill_score:        float = 0.0
    fairness_score:     float = 0.0
    cost_score:         float = 0.0
    continuity_score:   float = 0.0


def score_candidate(
    candidate: StaffMember,
    availability: Availability,
    demand: SessionDemand,
    provider_id: int,
    cfg: AppConfig,
    running_hours: dict[str, float],
    already_assigned: dict[int, str],
) -> ScoreBreakdown:
    """
    Score one assistant candidate for one dentist's slot.

    Args:
        candidate:        The assistant being scored
        availability:     Their availability for this session
        demand:           What this session needs
        provider_id:      The dentist they'd be assisting
        cfg:              Full app config
        running_hours:    Hours already assigned this week {staff_id: hours}
        already_assigned: Which assistant is already paired with each dentist
                          this week {provider_id: staff_id}
    """
    score = ScoreBreakdown(staff_id=candidate.staff_id, total=0.0)

    # ── 1. Preference score (0–40 points) ──
    # Worth the most — dentist preference is the primary driver
    dentist_staff_id = None
    for s in cfg.staff:
        if s.provider_id == provider_id:
            dentist_staff_id = s.staff_id
            break

    prefs = cfg.rules.dentist_preferences.get(dentist_staff_id, [])
    if candidate.staff_id in prefs:
        rank = prefs.index(candidate.staff_id)  # 0 = top preference
        pts = 40 - (rank * 10)  # 1st pref=40, 2nd=30, 3rd=20...
        score.preference_score = pts
        score.reasons.append(f"preferred assistant (rank {rank + 1})")
    else:
        score.reasons.append("not a preferred assistant")

    # ── 2. Skill score (0–30 points) ──
    # Has the right skills for this dentist's procedures?
    required = demand.skills_by_provider.get(provider_id, set())
    if required:
        has = required & candidate.skills
        missing = required - candidate.skills
        if not missing:
            score.skill_score = 30.0
            score.reasons.append(f"has all required skills: {sorted(has)}")
        else:
            # Partial credit for partial skill match
            score.skill_score = round(30.0 * len(has) / len(required), 1)
            score.reasons.append(f"missing skills: {sorted(missing)}")
    else:
        # No special skills needed — full points for any capable assistant
        score.skill_score = 15.0
        score.reasons.append("no special skills required")

    # ── 3. Fairness score (0–15 points) ──
    # Reward assistants with fewer hours so far — spreads load evenly
    hours_so_far = running_hours.get(candidate.staff_id, 0.0)
    max_weekly = candidate.max_weekly_hours
    utilisation = hours_so_far / max_weekly if max_weekly > 0 else 1.0
    score.fairness_score = round(15.0 * (1.0 - utilisation), 1)
    score.reasons.append(f"utilisation {hours_so_far:.1f}/{max_weekly}h")

    # ── 4. Cost score (0–10 points) ──
    # Lower cost = higher score (relative to most expensive assistant)
    all_costs = [s.hourly_cost for s in cfg.staff_by_role(
        __import__('roster.domain.models', fromlist=['Role']).Role.ASSISTANT)]
    max_cost = max(all_costs) if all_costs else candidate.hourly_cost
    score.cost_score = round(10.0 * (1.0 - candidate.hourly_cost / max_cost), 1)
    score.reasons.append(f"cost ${candidate.hourly_cost}/h")

    # ── 5. Continuity score (0–5 points) ──
    # Already working with this dentist this week? Keep the pairing.
    if already_assigned.get(provider_id) == candidate.staff_id:
        score.continuity_score = 5.0
        score.reasons.append("continuity — already paired this week")

    score.total = round(
        score.preference_score +
        score.skill_score +
        score.fairness_score +
        score.cost_score +
        score.continuity_score,
        2
    )
    return score
