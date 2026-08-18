"""
insights/validator.py

The last line of defense against unsupported claims. Even though the LLM
prompt in llm_reasoner.py instructs it to only use given numbers, prompts
are not guarantees — this module actually checks.

Method: extract every numeric token from an insight's explanation text,
and confirm each one appears (within a small rounding tolerance) among
the numbers in that insight's own evidence list, or among a small
allow-list of investor-profile numbers (age, horizon years) that are
legitimately safe to restate. Any number that doesn't trace back is
treated as an unsupported claim: the insight's confidence is capped low
and it's flagged in data_quality_notes rather than silently trusted.

This is intentionally conservative and a little blunt (e.g. it doesn't
understand that "3" in "top 3 holdings" is a count, not a computed
value) — false positives here just mean an occasional needlessly-lowered
confidence score, which is a much safer failure mode than an
undetected fabricated statistic reaching the investor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from schemas import DataQualityNote, Insight, InvestorProfile

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
TOLERANCE = 0.6  # absolute tolerance for rounding differences


@dataclass
class ValidationResult:
    validated_insights: list[Insight]
    flagged_notes: list[DataQualityNote]


def _numbers_in(text: str) -> list[float]:
    return [float(m) for m in NUMBER_RE.findall(text)]


def _allowed_numbers(insight: Insight, investor: InvestorProfile) -> set[float]:
    allowed: set[float] = set()
    for ev in insight.evidence:
        allowed.update(_numbers_in(ev.value))
        allowed.update(_numbers_in(ev.label))
    if investor.age is not None:
        allowed.add(float(investor.age))
    if investor.investment_horizon_years is not None:
        allowed.add(float(investor.investment_horizon_years))
    # small integers are near-universally safe (counts, list positions,
    # "top 3", "2-4 sentences" style phrasing) — excluding these avoids
    # flagging harmless connective numbers as fabricated statistics.
    allowed.update({0.0, 1.0, 2.0, 3.0, 4.0, 5.0})
    return allowed


def _is_supported(n: float, allowed: set[float]) -> bool:
    return any(abs(n - a) <= TOLERANCE for a in allowed)


def validate_insights(insights: list[Insight], investor: InvestorProfile) -> ValidationResult:
    validated: list[Insight] = []
    flagged: list[DataQualityNote] = []

    for insight in insights:
        allowed = _allowed_numbers(insight, investor)
        found = _numbers_in(insight.explanation)
        unsupported = [n for n in found if not _is_supported(n, allowed)]

        if unsupported:
            insight.confidence = min(insight.confidence, 0.35)
            flagged.append(DataQualityNote(
                scheme_code=None,
                issue=(
                    f"Insight '{insight.title}' contained figure(s) "
                    f"{unsupported} not traceable to computed evidence."
                ),
                impact="Confidence score reduced; review this insight's explanation before trusting it.",
            ))
            # We keep it (rather than silently dropping) so the flag itself
            # is visible, but the deflated confidence + note make the risk
            # visible to any downstream consumer or human reviewer.

        validated.append(insight)

    return ValidationResult(validated_insights=validated, flagged_notes=flagged)
