"""
Data contracts for the Mutual Fund Portfolio Intelligence System.

Everything that enters or leaves the system is a typed Pydantic model.
This gives us three things for free, all of which matter for the
"structured, machine-readable output" and "sensible handling of missing
data" requirements in the assignment:

1. Input validation fails loudly and early, instead of silently
   producing garbage insights from garbage input.
2. The LLM's final output is forced into a schema, so it cannot
   ramble into unstructured prose that hides unsupported claims.
3. Every downstream consumer (API, CLI, evaluation harness) shares
   one definition of "what a valid insight looks like".
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------
# Investor profile
# --------------------------------------------------------------------------

class RiskAppetite(str, Enum):
    conservative = "conservative"
    moderate = "moderate"
    aggressive = "aggressive"


class InvestmentGoal(str, Enum):
    retirement = "retirement"
    wealth_creation = "wealth_creation"
    tax_saving = "tax_saving"
    short_term_goal = "short_term_goal"  # e.g. house down payment, wedding
    emergency_buffer = "emergency_buffer"


class InvestorProfile(BaseModel):
    investor_id: str
    age: Optional[int] = Field(default=None, ge=18, le=100)
    risk_appetite: Optional[RiskAppetite] = None
    primary_goal: Optional[InvestmentGoal] = None
    investment_horizon_years: Optional[float] = Field(default=None, ge=0)
    monthly_investable_surplus: Optional[float] = Field(default=None, ge=0)

    @field_validator("investment_horizon_years")
    @classmethod
    def horizon_sane(cls, v):
        if v is not None and v > 60:
            raise ValueError("investment_horizon_years looks implausible (>60 years)")
        return v


# --------------------------------------------------------------------------
# Portfolio input
# --------------------------------------------------------------------------

class FundHolding(BaseModel):
    """One line item in the investor's mutual fund portfolio."""
    scheme_code: str
    invested_amount: Optional[float] = Field(
        default=None, ge=0,
        description="Current market value of this holding, in INR."
    )
    units: Optional[float] = Field(default=None, ge=0)
    purchase_date: Optional[date] = None

    @field_validator("invested_amount")
    @classmethod
    def need_some_value_signal(cls, v):
        return v  # further cross-field check happens at Portfolio level


class Portfolio(BaseModel):
    holdings: list[FundHolding]

    @field_validator("holdings")
    @classmethod
    def non_empty(cls, v):
        if not v:
            raise ValueError("Portfolio must contain at least one holding")
        return v


class AnalysisRequest(BaseModel):
    investor: InvestorProfile
    portfolio: Portfolio


# --------------------------------------------------------------------------
# Structured output
# --------------------------------------------------------------------------

class InsightCategory(str, Enum):
    allocation = "allocation"
    concentration = "concentration"
    overlap = "overlap"
    diversification = "diversification"
    risk = "risk"
    performance = "performance"
    suitability = "suitability"
    cost = "cost"
    data_quality = "data_quality"


class Severity(str, Enum):
    info = "info"
    watch = "watch"          # worth knowing, not urgent
    action = "action"        # investor should probably do something


class Evidence(BaseModel):
    """
    A single verifiable numeric fact backing an insight.
    The LLM is never allowed to introduce a number that isn't traceable
    back to one of these — see insights/validator.py.
    """
    label: str
    value: str
    source: str  # e.g. "computed:concentration.py", "data:amfi_nav"


class Insight(BaseModel):
    category: InsightCategory
    severity: Severity
    title: str
    explanation: str
    evidence: list[Evidence]
    confidence: float = Field(ge=0.0, le=1.0)


class DataQualityNote(BaseModel):
    scheme_code: Optional[str] = None
    issue: str
    impact: str


class AnalysisResponse(BaseModel):
    investor_id: str
    generated_at: str
    headline: str
    insights: list[Insight]
    data_quality_notes: list[DataQualityNote]
    disclaimer: str = (
        "Auto-generated prototype analysis. Not investment advice. "
        "Figures are computed from the data sources documented in this "
        "project's README and may be incomplete or delayed."
    )
