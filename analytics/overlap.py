"""
Overlap analysis: if an investor holds multiple equity funds, how much of
that "diversification" is real vs. illusory because the funds hold the
same underlying stocks?

Method: weighted overlap between two funds' top holdings, defined as
    overlap(A, B) = sum over shared stocks of min(weight_in_A, weight_in_B)

This is a standard, simple, and defensible metric (it's the portion of
each fund that is literally invested in the exact same names, capped at
the smaller of the two exposures). It is NOT the same as correlation of
returns — that's a different (also valid) concept we don't attempt here,
and we say so explicitly rather than conflating the two.

Only funds with known holdings data (equity funds we have fact-sheet-derived
top-10 holdings for) are compared. Funds without holdings data are
explicitly excluded and reported, not silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from data_sources import get_fund_metadata, get_holdings


@dataclass
class PairOverlap:
    scheme_code_a: str
    scheme_code_b: str
    fund_name_a: str
    fund_name_b: str
    overlap_pct: float          # 0-100, share of holdings in common (weighted)
    shared_stocks: list[str]


@dataclass
class OverlapResult:
    pairs: list[PairOverlap]
    excluded_scheme_codes: list[str]   # equity funds held, but no holdings data available


def compute_overlap(scheme_codes: list[str]) -> OverlapResult:
    equity_codes = []
    excluded = []
    for code in scheme_codes:
        meta = get_fund_metadata(code)
        if meta is None or meta["category"] != "Equity":
            continue
        if get_holdings(code) is None:
            excluded.append(code)
            continue
        equity_codes.append(code)

    pairs: list[PairOverlap] = []
    for a, b in combinations(equity_codes, 2):
        holdings_a = {h["stock"]: h["weight_pct"] for h in get_holdings(a)}
        holdings_b = {h["stock"]: h["weight_pct"] for h in get_holdings(b)}
        shared = set(holdings_a) & set(holdings_b)
        if not shared:
            continue
        overlap_pct = round(sum(min(holdings_a[s], holdings_b[s]) for s in shared), 2)
        meta_a, meta_b = get_fund_metadata(a), get_fund_metadata(b)
        pairs.append(PairOverlap(
            scheme_code_a=a,
            scheme_code_b=b,
            fund_name_a=meta_a["scheme_name"],
            fund_name_b=meta_b["scheme_name"],
            overlap_pct=overlap_pct,
            shared_stocks=sorted(shared),
        ))

    pairs.sort(key=lambda p: p.overlap_pct, reverse=True)
    return OverlapResult(pairs=pairs, excluded_scheme_codes=excluded)
