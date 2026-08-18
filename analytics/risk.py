"""
Risk metrics computed directly from NAV history. Pure arithmetic — no
LLM involvement, because these are well-defined formulas with one right
answer.

Every metric here explicitly checks it has enough data points before
computing anything. If it doesn't, the field is returned as None with a
reason, rather than computed on too little data and presented as if it
were reliable. This is the concrete implementation of the assignment's
"a calculation cannot be performed reliably" edge case.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from data_sources import get_nav_history

MIN_DAYS_FOR_VOLATILITY = 60        # ~3 months of trading days
MIN_DAYS_FOR_DRAWDOWN = 60
RISK_FREE_RATE_ANNUAL = 0.065        # approx India short-term T-bill / repo-adjacent rate, documented assumption


@dataclass
class RiskMetrics:
    scheme_code: str
    annualised_volatility_pct: float | None
    max_drawdown_pct: float | None
    sharpe_ratio: float | None
    data_points_used: int
    insufficient_data_reason: str | None


def _daily_returns(nav_series: list[dict]) -> list[float]:
    navs = [row["nav"] for row in nav_series]
    return [(navs[i] / navs[i - 1]) - 1 for i in range(1, len(navs))]


def compute_risk_metrics(scheme_code: str) -> RiskMetrics:
    nav_series = get_nav_history(scheme_code)

    if nav_series is None:
        return RiskMetrics(scheme_code, None, None, None, 0,
                            "NAV history unavailable for this scheme.")

    if len(nav_series) < MIN_DAYS_FOR_VOLATILITY:
        return RiskMetrics(scheme_code, None, None, None, len(nav_series),
                            f"Only {len(nav_series)} NAV data points available; "
                            f"need at least {MIN_DAYS_FOR_VOLATILITY} for a reliable volatility estimate.")

    returns = _daily_returns(nav_series)
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    daily_vol = math.sqrt(variance)
    annualised_vol = daily_vol * math.sqrt(252) * 100  # percent

    # Max drawdown
    navs = [row["nav"] for row in nav_series]
    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        peak = max(peak, v)
        dd = (v - peak) / peak
        max_dd = min(max_dd, dd)
    max_dd_pct = round(max_dd * 100, 2)

    # Sharpe ratio (annualised return vs risk-free, divided by annualised vol)
    n_years = len(nav_series) / 252
    total_return = navs[-1] / navs[0] - 1
    annualised_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else None
    sharpe = None
    if annualised_return is not None and annualised_vol > 0:
        sharpe = round((annualised_return - RISK_FREE_RATE_ANNUAL) / (annualised_vol / 100), 2)

    return RiskMetrics(
        scheme_code=scheme_code,
        annualised_volatility_pct=round(annualised_vol, 2),
        max_drawdown_pct=max_dd_pct,
        sharpe_ratio=sharpe,
        data_points_used=len(nav_series),
        insufficient_data_reason=None,
    )
