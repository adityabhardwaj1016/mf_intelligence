"""
insights/engine.py — the orchestrator.

This is the one place that knows how to call every analytics/ module and
assemble their outputs into a single AnalysisBundle. It is deliberately
*not* where any insight text or prioritization decision gets made — this
module only computes and collects facts. Deciding which facts matter
(prioritizer.py) and explaining them in language (llm_reasoner.py) are
separate steps, so each piece stays independently testable.

This is also where "the system decides which calculations are even
relevant" lives — e.g. overlap analysis is skipped entirely (not run
with fabricated data) if the investor holds zero or one equity fund.
That's the lightweight "agentic" decision the assignment mentions:
choosing which tools/calculations to invoke based on the shape of the
input, rather than always running a fixed pipeline blindly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from analytics.allocation import compute_allocation, AllocationResult
from analytics.concentration import compute_concentration, ConcentrationResult
from analytics.overlap import compute_overlap, OverlapResult
from analytics.risk import compute_risk_metrics, RiskMetrics
from analytics.performance import compute_performance, PerformanceResult
from analytics.suitability import compute_suitability, SuitabilityResult
from data_sources import get_fund_metadata, cross_check_latest_nav
from schemas import AnalysisRequest, DataQualityNote


@dataclass
class AnalysisBundle:
    allocation: AllocationResult
    concentration: ConcentrationResult
    overlap: OverlapResult | None
    risk_by_scheme: dict[str, RiskMetrics]
    performance_by_scheme: dict[str, PerformanceResult]
    suitability: SuitabilityResult
    weighted_expense_ratio_pct: float | None
    data_quality_notes: list[DataQualityNote] = field(default_factory=list)


def _weighted_risk_level(allocation: AllocationResult) -> float | None:
    if allocation.total_value <= 0:
        return None
    total_weighted = 0.0
    total_weight = 0.0
    for h in allocation.resolved_holdings:
        meta = get_fund_metadata(h.scheme_code)
        if meta is None or h.weight_pct is None:
            continue
        total_weighted += meta["risk_level"] * h.weight_pct
        total_weight += h.weight_pct
    if total_weight == 0:
        return None
    return total_weighted / total_weight


def _weighted_expense_ratio(allocation: AllocationResult) -> float | None:
    if allocation.total_value <= 0:
        return None
    total_weighted = 0.0
    total_weight = 0.0
    for h in allocation.resolved_holdings:
        meta = get_fund_metadata(h.scheme_code)
        if meta is None or h.weight_pct is None:
            continue
        total_weighted += meta["expense_ratio_pct"] * h.weight_pct
        total_weight += h.weight_pct
    if total_weight == 0:
        return None
    return round(total_weighted / total_weight, 2)


def run_analysis(request: AnalysisRequest) -> AnalysisBundle:
    notes: list[DataQualityNote] = []

    allocation = compute_allocation(request.portfolio)

    for code in allocation.unresolved_scheme_codes:
        meta = get_fund_metadata(code)
        if meta is None:
            notes.append(DataQualityNote(
                scheme_code=code,
                issue="Scheme code not found in fund catalog.",
                impact="This holding is excluded from all allocation, concentration, and suitability calculations.",
            ))
        else:
            notes.append(DataQualityNote(
                scheme_code=code,
                issue="Fund identified, but no invested amount / value provided.",
                impact="This holding is excluded from allocation-weighted calculations; "
                       "its risk/performance can still be reported standalone.",
            ))

    concentration = compute_concentration(allocation.resolved_holdings)

    all_scheme_codes = [h.scheme_code for h in request.portfolio.holdings]
    equity_holding_count = sum(
        1 for c in all_scheme_codes
        if (m := get_fund_metadata(c)) and m["category"] == "Equity"
    )
    overlap = None
    if equity_holding_count >= 2:
        overlap = compute_overlap(all_scheme_codes)
        for code in overlap.excluded_scheme_codes:
            notes.append(DataQualityNote(
                scheme_code=code,
                issue="No holdings-level data available for this equity fund "
                      "(would require fact-sheet ingestion — see README limitations).",
                impact="Excluded from overlap analysis; other funds may still be compared pairwise.",
            ))

    risk_by_scheme: dict[str, RiskMetrics] = {}
    performance_by_scheme: dict[str, PerformanceResult] = {}
    for code in set(all_scheme_codes):
        conflict = cross_check_latest_nav(code)
        if conflict:
            notes.append(DataQualityNote(
                scheme_code=code,
                issue=f"Conflicting NAV data between sources: {conflict}",
                impact="AMFI's value is treated as source of truth for this scheme; "
                       "figures derived from the other source may be slightly stale.",
            ))
        rm = compute_risk_metrics(code)
        risk_by_scheme[code] = rm
        if rm.insufficient_data_reason:
            notes.append(DataQualityNote(
                scheme_code=code,
                issue=rm.insufficient_data_reason,
                impact="Risk metrics (volatility, drawdown, Sharpe) omitted for this fund.",
            ))
        pm = compute_performance(code)
        performance_by_scheme[code] = pm
        if pm.insufficient_data_reason:
            notes.append(DataQualityNote(
                scheme_code=code,
                issue=pm.insufficient_data_reason,
                impact="Return figures omitted for this fund.",
            ))

    weighted_risk_level = _weighted_risk_level(allocation)
    weighted_expense = _weighted_expense_ratio(allocation)

    suitability = compute_suitability(
        investor=request.investor,
        by_category_pct=allocation.by_category,
        weighted_risk_level=weighted_risk_level,
    )

    if request.investor.risk_appetite is None:
        notes.append(DataQualityNote(
            scheme_code=None,
            issue="Investor risk appetite not provided.",
            impact="Suitability checks against stated risk appetite are skipped.",
        ))
    if request.investor.investment_horizon_years is None:
        notes.append(DataQualityNote(
            scheme_code=None,
            issue="Investment horizon not provided.",
            impact="Horizon-based suitability checks (e.g. short horizon + high equity) are skipped.",
        ))

    return AnalysisBundle(
        allocation=allocation,
        concentration=concentration,
        overlap=overlap,
        risk_by_scheme=risk_by_scheme,
        performance_by_scheme=performance_by_scheme,
        suitability=suitability,
        weighted_expense_ratio_pct=weighted_expense,
        data_quality_notes=notes,
    )
