"""
Deterministic allocation analytics.

Nothing in this file calls an LLM. Percentages are arithmetic. This is
intentional: allocation math has one correct answer, and an LLM has no
business "estimating" it.
"""

from __future__ import annotations

from dataclasses import dataclass

from data_sources import get_fund_metadata
from schemas import Portfolio


@dataclass
class ResolvedHolding:
    scheme_code: str
    value: float
    category: str | None
    sub_category: str | None
    amc: str | None
    weight_pct: float | None = None  # filled in once total is known


@dataclass
class AllocationResult:
    resolved_holdings: list[ResolvedHolding]
    unresolved_scheme_codes: list[str]  # metadata missing entirely
    total_value: float
    by_category: dict[str, float]       # category -> % of total
    by_sub_category: dict[str, float]
    by_amc: dict[str, float]


def resolve_portfolio_value(portfolio: Portfolio) -> tuple[list[ResolvedHolding], list[str]]:
    """
    Turns raw holdings into resolved holdings with known category/AMC.
    A holding is "unresolved" if we have no fund metadata for its scheme
    code at all — that's a data-quality issue, not a calculation to fudge.
    A holding with metadata but no invested_amount is skipped from value
    based analytics (flagged separately by the caller).
    """
    resolved = []
    unresolved = []
    for h in portfolio.holdings:
        meta = get_fund_metadata(h.scheme_code)
        if meta is None:
            unresolved.append(h.scheme_code)
            continue
        if h.invested_amount is None:
            # Known fund, but we can't weight it without a value.
            unresolved.append(h.scheme_code)
            continue
        resolved.append(ResolvedHolding(
            scheme_code=h.scheme_code,
            value=h.invested_amount,
            category=meta["category"],
            sub_category=meta["sub_category"],
            amc=meta["amc"],
        ))
    return resolved, unresolved


def compute_allocation(portfolio: Portfolio) -> AllocationResult:
    resolved, unresolved = resolve_portfolio_value(portfolio)
    total = sum(h.value for h in resolved)

    by_category: dict[str, float] = {}
    by_sub_category: dict[str, float] = {}
    by_amc: dict[str, float] = {}

    if total > 0:
        for h in resolved:
            h.weight_pct = round(h.value / total * 100, 2)
            by_category[h.category] = by_category.get(h.category, 0) + h.weight_pct
            by_sub_category[h.sub_category] = by_sub_category.get(h.sub_category, 0) + h.weight_pct
            by_amc[h.amc] = by_amc.get(h.amc, 0) + h.weight_pct

        by_category = {k: round(v, 2) for k, v in by_category.items()}
        by_sub_category = {k: round(v, 2) for k, v in by_sub_category.items()}
        by_amc = {k: round(v, 2) for k, v in by_amc.items()}

    return AllocationResult(
        resolved_holdings=resolved,
        unresolved_scheme_codes=unresolved,
        total_value=total,
        by_category=by_category,
        by_sub_category=by_sub_category,
        by_amc=by_amc,
    )
