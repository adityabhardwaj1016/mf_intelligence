"""
Suitability: does this portfolio's risk profile roughly match this
investor's stated risk appetite, horizon, and goal?

This is deliberately rule-based rather than LLM-based, for the same
reason as everything else in analytics/: the *mapping logic* (e.g. "short
horizon + high equity exposure = flag") is a fixed, explainable rule set,
and applying fixed rules should be applied consistently by every input,
not creatively reinterpreted by an LLM each time. The LLM's role (see
insights/llm_reasoner.py) is to explain *why* a flag raised here matters
to this particular investor, not to decide whether to raise it.
"""

from __future__ import annotations

from dataclasses import dataclass

from schemas import InvestorProfile

# weighted-average riskometer level (1-6) considered "expected" for a given
# risk appetite. These are illustrative bands, not SEBI-official guidance —
# documented as an assumption.
RISK_APPETITE_EXPECTED_RANGE = {
    "conservative": (1.0, 3.0),
    "moderate": (2.5, 4.5),
    "aggressive": (4.0, 6.0),
}


@dataclass
class SuitabilityFlag:
    code: str
    message: str


@dataclass
class SuitabilityResult:
    portfolio_weighted_risk_level: float | None
    equity_weight_pct: float | None
    flags: list[SuitabilityFlag]


def compute_suitability(
    investor: InvestorProfile,
    by_category_pct: dict[str, float],
    weighted_risk_level: float | None,
) -> SuitabilityResult:
    flags: list[SuitabilityFlag] = []
    equity_weight = by_category_pct.get("Equity")

    # Rule 1: risk appetite vs actual portfolio risk level
    if investor.risk_appetite and weighted_risk_level is not None:
        lo, hi = RISK_APPETITE_EXPECTED_RANGE[investor.risk_appetite.value]
        if weighted_risk_level > hi:
            flags.append(SuitabilityFlag(
                code="risk_above_appetite",
                message=(
                    f"Portfolio's weighted risk level ({weighted_risk_level:.1f}/6) is "
                    f"higher than typically expected for a '{investor.risk_appetite.value}' "
                    f"investor (expected up to {hi:.1f}/6)."
                ),
            ))
        elif weighted_risk_level < lo:
            flags.append(SuitabilityFlag(
                code="risk_below_appetite",
                message=(
                    f"Portfolio's weighted risk level ({weighted_risk_level:.1f}/6) is "
                    f"lower than typically expected for a '{investor.risk_appetite.value}' "
                    f"investor (expected at least {lo:.1f}/6) — may be leaving return on the table "
                    f"if the stated risk appetite is accurate."
                ),
            ))

    # Rule 2: short horizon + high equity exposure
    if investor.investment_horizon_years is not None and equity_weight is not None:
        if investor.investment_horizon_years < 3 and equity_weight > 50:
            flags.append(SuitabilityFlag(
                code="short_horizon_high_equity",
                message=(
                    f"Investment horizon is under 3 years but equity exposure is "
                    f"{equity_weight:.0f}% of the portfolio — equity markets can be volatile "
                    f"over short periods, raising the risk of having to sell at a loss."
                ),
            ))

    # Rule 3: goal-specific check — short_term_goal with high equity
    if investor.primary_goal and investor.primary_goal.value == "short_term_goal" and equity_weight and equity_weight > 40:
        flags.append(SuitabilityFlag(
            code="goal_mismatch_short_term",
            message=(
                f"Stated goal is a short-term goal, but {equity_weight:.0f}% of the portfolio "
                f"is in equity — for near-term goals, capital protection is usually prioritised "
                f"over growth."
            ),
        ))

    # Rule 4: age-based sanity check (very simple, illustrative heuristic)
    if investor.age is not None and equity_weight is not None:
        # classic (very rough) heuristic: equity% shouldn't wildly exceed (110 - age)
        heuristic_ceiling = max(110 - investor.age, 20)
        if equity_weight > heuristic_ceiling + 20:
            flags.append(SuitabilityFlag(
                code="age_equity_heuristic",
                message=(
                    f"Equity exposure ({equity_weight:.0f}%) is well above the illustrative "
                    f"'(110 - age)' heuristic ceiling of {heuristic_ceiling}% for a {investor.age}-year-old. "
                    f"This is a rough rule of thumb, not a rule — worth a deliberate gut-check, not automatic action."
                ),
            ))

    return SuitabilityResult(
        portfolio_weighted_risk_level=round(weighted_risk_level, 2) if weighted_risk_level is not None else None,
        equity_weight_pct=equity_weight,
        flags=flags,
    )
