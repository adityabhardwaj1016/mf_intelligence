"""
Concentration risk: how much of the portfolio rides on a small number of
bets. Two complementary deterministic measures are used:

1. Top-N weight — simplest, most intuitive for an investor ("your top 3
   funds are 68% of your money").
2. Herfindahl-Hirschman Index (HHI) — standard concentration measure
   (sum of squared weights). Used widely in finance/antitrust to
   quantify concentration in a single number. HHI on fractional weights
   (0-1 scale) ranges from 1/n (perfectly even) to 1 (single holding).
   We report it 0-10000 scale (the conventional one) for interpretability.
"""

from __future__ import annotations

from dataclasses import dataclass

from analytics.allocation import ResolvedHolding


@dataclass
class ConcentrationResult:
    top_holding_weight_pct: float | None
    top3_weight_pct: float | None
    hhi: float | None            # 0 (max diversified) - 10000 (single holding)
    hhi_interpretation: str | None
    n_holdings: int


def compute_concentration(resolved_holdings: list[ResolvedHolding]) -> ConcentrationResult:
    n = len(resolved_holdings)
    if n == 0:
        return ConcentrationResult(None, None, None, None, 0)

    weights_sorted = sorted((h.weight_pct or 0 for h in resolved_holdings), reverse=True)
    top1 = round(weights_sorted[0], 2)
    top3 = round(sum(weights_sorted[:3]), 2)

    hhi = round(sum(w ** 2 for w in weights_sorted), 2)  # weights already in % (0-100), so this is naturally 0-10000 scale

    if hhi < 1500:
        interpretation = "well diversified across holdings"
    elif hhi < 2500:
        interpretation = "moderately concentrated"
    else:
        interpretation = "highly concentrated in a small number of holdings"

    return ConcentrationResult(
        top_holding_weight_pct=top1,
        top3_weight_pct=top3,
        hhi=hhi,
        hhi_interpretation=interpretation,
        n_holdings=n,
    )
