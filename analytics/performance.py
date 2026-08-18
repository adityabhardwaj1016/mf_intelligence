"""
Historical performance: absolute returns, CAGR over different windows,
and comparison against the fund's own category benchmark (also
deterministic — pulled from category_benchmarks data, not asked of an LLM).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from data_sources import get_fund_metadata, get_category_benchmark, get_nav_history


@dataclass
class PerformanceResult:
    scheme_code: str
    return_1yr_pct: float | None
    cagr_3yr_pct: float | None
    cagr_5yr_pct: float | None
    category_typical_1yr_pct: float | None
    category_typical_3yr_cagr_pct: float | None
    vs_category_1yr_gap_pct: float | None   # positive = outperforming category
    insufficient_data_reason: str | None


def _nav_on_or_before(nav_series: list[dict], target: date) -> float | None:
    candidates = [row for row in nav_series if date.fromisoformat(row["date"]) <= target]
    if not candidates:
        return None
    return candidates[-1]["nav"]


def compute_performance(scheme_code: str) -> PerformanceResult:
    nav_series = get_nav_history(scheme_code)
    meta = get_fund_metadata(scheme_code)

    if nav_series is None or len(nav_series) < 30:
        return PerformanceResult(scheme_code, None, None, None, None, None, None,
                                  "Insufficient NAV history to compute returns.")

    latest = nav_series[-1]
    latest_date = date.fromisoformat(latest["date"])
    latest_nav = latest["nav"]

    def cagr_over(years: float) -> float | None:
        target = latest_date - timedelta(days=int(years * 365.25))
        past_nav = _nav_on_or_before(nav_series, target)
        if past_nav is None or past_nav <= 0:
            return None
        growth = latest_nav / past_nav
        return round((growth ** (1 / years) - 1) * 100, 2)

    def simple_return_over(years: float) -> float | None:
        target = latest_date - timedelta(days=int(years * 365.25))
        past_nav = _nav_on_or_before(nav_series, target)
        if past_nav is None or past_nav <= 0:
            return None
        return round((latest_nav / past_nav - 1) * 100, 2)

    return_1yr = simple_return_over(1)
    cagr_3yr = cagr_over(3)
    cagr_5yr = cagr_over(5)

    cat_1yr = cat_3yr = gap = None
    if meta:
        bench = get_category_benchmark(meta["sub_category"])
        if bench:
            cat_1yr = bench["typical_1yr_return_pct"]
            cat_3yr = bench["typical_3yr_cagr_pct"]
            if return_1yr is not None:
                gap = round(return_1yr - cat_1yr, 2)

    return PerformanceResult(
        scheme_code=scheme_code,
        return_1yr_pct=return_1yr,
        cagr_3yr_pct=cagr_3yr,
        cagr_5yr_pct=cagr_5yr,
        category_typical_1yr_pct=cat_1yr,
        category_typical_3yr_cagr_pct=cat_3yr,
        vs_category_1yr_gap_pct=gap,
        insufficient_data_reason=None,
    )
