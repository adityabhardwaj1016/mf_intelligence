"""
tests/test_cases.py

Defines the demo portfolios used both by cli.py (--demo flag) and by
run_eval.py (automated evaluation). Each case has an explicit
"expected" block describing what a correct analysis MUST and MUST NOT
contain — this is what makes tests/run_eval.py a real evaluation rather
than eyeballed sample output.
"""

from __future__ import annotations

from schemas import (
    AnalysisRequest, FundHolding, InvestorProfile, InvestmentGoal,
    Portfolio, RiskAppetite,
)

# --------------------------------------------------------------------------
# Case 1: Well-diversified portfolio, moderate investor.
# Different AMCs, different categories, no single dominant holding.
# Expectation: NO high-severity concentration/overlap/suitability flags.
# --------------------------------------------------------------------------

well_diversified = AnalysisRequest(
    investor=InvestorProfile(
        investor_id="demo_diversified_001",
        age=32,
        risk_appetite=RiskAppetite.moderate,
        primary_goal=InvestmentGoal.wealth_creation,
        investment_horizon_years=8,
        monthly_investable_surplus=25000,
    ),
    portfolio=Portfolio(holdings=[
        FundHolding(scheme_code="100001", invested_amount=150000),  # Large cap
        FundHolding(scheme_code="100007", invested_amount=100000),  # Mid cap
        FundHolding(scheme_code="100013", invested_amount=80000),   # ELSS
        FundHolding(scheme_code="100016", invested_amount=90000),   # Hybrid aggressive
        FundHolding(scheme_code="100018", invested_amount=80000),   # Debt short duration
    ]),
)

# --------------------------------------------------------------------------
# Case 2: Concentrated + overlapping portfolio.
# Three large-cap-heavy funds (large cap + 2 flexi cap, which lean
# large-cap), one dominant holding.
# Expectation: HIGH concentration flag, overlap flags between the equity funds.
# --------------------------------------------------------------------------

concentrated_overlapping = AnalysisRequest(
    investor=InvestorProfile(
        investor_id="demo_concentrated_002",
        age=29,
        risk_appetite=RiskAppetite.aggressive,
        primary_goal=InvestmentGoal.wealth_creation,
        investment_horizon_years=10,
    ),
    portfolio=Portfolio(holdings=[
        FundHolding(scheme_code="100001", invested_amount=400000),  # Large cap - dominant
        FundHolding(scheme_code="100004", invested_amount=60000),   # Flexi cap
        FundHolding(scheme_code="100005", invested_amount=40000),   # Flexi cap
    ]),
)

# --------------------------------------------------------------------------
# Case 3: Missing / incomplete data.
# One unknown scheme code, one known fund with no invested_amount given.
# Expectation: data_quality insight present, no crash, partial analysis
# still returned for the resolvable holding.
# --------------------------------------------------------------------------

missing_data = AnalysisRequest(
    investor=InvestorProfile(
        investor_id="demo_missing_003",
        risk_appetite=RiskAppetite.conservative,
    ),
    portfolio=Portfolio(holdings=[
        FundHolding(scheme_code="999999", invested_amount=50000),   # unknown scheme code
        FundHolding(scheme_code="100020", invested_amount=None),    # known fund, no value given
        FundHolding(scheme_code="100019", invested_amount=200000),  # valid, resolvable
    ]),
)

# --------------------------------------------------------------------------
# Case 4: Suitability mismatch — short horizon, short-term goal, high equity.
# Expectation: suitability action flags for short_horizon_high_equity and
# goal_mismatch_short_term.
# --------------------------------------------------------------------------

suitability_mismatch = AnalysisRequest(
    investor=InvestorProfile(
        investor_id="demo_suitability_004",
        age=45,
        risk_appetite=RiskAppetite.conservative,
        primary_goal=InvestmentGoal.short_term_goal,
        investment_horizon_years=1.5,
    ),
    portfolio=Portfolio(holdings=[
        FundHolding(scheme_code="100010", invested_amount=200000),  # Small cap
        FundHolding(scheme_code="100011", invested_amount=150000),  # Small cap
        FundHolding(scheme_code="100007", invested_amount=100000),  # Mid cap
    ]),
)

# --------------------------------------------------------------------------
# Case 5: Single holding — edge case with no possible overlap analysis
# (fewer than 2 equity funds) and trivial concentration (100% in one fund).
# --------------------------------------------------------------------------

single_holding = AnalysisRequest(
    investor=InvestorProfile(investor_id="demo_single_005", age=40),
    portfolio=Portfolio(holdings=[
        FundHolding(scheme_code="100001", invested_amount=100000),
    ]),
)


DEMO_PORTFOLIOS = {
    "well_diversified": well_diversified,
    "concentrated": concentrated_overlapping,
    "missing_data": missing_data,
    "suitability_mismatch": suitability_mismatch,
    "single_holding": single_holding,
}


# --------------------------------------------------------------------------
# Expected-outcome assertions, consumed by tests/run_eval.py
# --------------------------------------------------------------------------

EXPECTATIONS = {
    "well_diversified": {
        "must_not_have_categories_at_severity": [("concentration", "action")],
        "max_hhi": 3000,  # sanity ceiling, not tuned to be trivially true
        "min_insights": 0,  # zero material insights is a valid, honest outcome
    },
    "concentrated": {
        "must_have_categories": ["concentration", "overlap"],
        "min_hhi": 2000,
    },
    "missing_data": {
        "must_have_categories": ["data_quality"],
        "must_not_crash": True,
        "min_data_quality_notes": 2,  # unknown scheme + missing value
    },
    "suitability_mismatch": {
        "must_have_categories": ["suitability"],
        "min_suitability_flags": 1,
    },
    "single_holding": {
        "must_not_crash": True,
        "overlap_should_be_none": True,
    },
}
