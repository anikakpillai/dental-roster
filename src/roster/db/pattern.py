"""
Open Dental stores appointment timing as a 'Pattern' string.
Each character = 5 minutes.
  'X' or 'x' = provider (dentist) time
  '/'        = assistant time
Example: '//XXXX//' = 8 chars = 40 min total, 20 min provider, 20 min assistant.
"""
from __future__ import annotations
from dataclasses import dataclass

INCREMENT_MIN = 5


@dataclass
class PatternTiming:
    total_min: int
    provider_min: int
    assistant_min: int


def parse_pattern(pattern: str | None) -> PatternTiming:
    if not pattern:
        return PatternTiming(0, 0, 0)
    pattern = pattern.strip()
    total = len(pattern) * INCREMENT_MIN
    provider = sum(1 for c in pattern if c in ("X", "x")) * INCREMENT_MIN
    assistant = sum(1 for c in pattern if c == "/") * INCREMENT_MIN
    return PatternTiming(total, provider, assistant)
