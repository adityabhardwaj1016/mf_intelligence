"""
insights/prioritizer.py

Turns the AnalysisBundle into a ranked list of CandidateInsight objects.
Both *which* candidate insights exist and their severity/priority score
are decided here by fixed rules — not by the LLM. This directly answers
the assignment's "insights should be prioritised" requirement in a way
that's consistent and auditable: the same bundle always produces the
same ranked candidates, regardless of which LLM (or whether an LLM at
all) explains them afterwards.

The LLM's job downstream (llm_reasoner.py) is strictly to turn each
candidate's `raw_facts` into readable `title` / `explanation` text, and
to decide which of the top-ranked candidates are worth surfacing to this
particular investor (a judgment call on relevance/redundancy) — never to
invent new facts or override the severity assigned here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from insights.engine import AnalysisBundle
from schemas import InsightCategory, Severity


@dataclass
class CandidateInsight:
    category: InsightCategory
    severity: Severity
    priority_score: float          # higher = more important, used for ranking only
    raw_facts: dict                # structured facts the LLM must ground its text in
    evidence: list[dict]           # [{label, value, source}, ...] — becomes schemas.Evidence


SEVERITY_BASE_SCORE = {Severity.action: 30, Severity.watch: 15, Severity.info: 5}


def build_candidates(bundle: AnalysisBundle) -> list[CandidateInsight]:
    candidates: list[CandidateInsight] = []

    # ---- Concentration -----------------------------------------------
    c = bundle.concentration
    if c.hhi is not None:
        if c.hhi >= 2500:
            severity = Severity.action
        elif c.hhi >= 1500:
            severity = Severity.watch
        else:
            severity = Severity.info
        candidates.append(CandidateInsight(
            category=InsightCategory.concentration,
            severity=severity,
            priority_score=SEVERITY_BASE_SCORE[severity] + (c.hhi / 200),
            raw_facts={
                "hhi": c.hhi,
                "interpretation": c.hhi_interpretation,
                "top_holding_weight_pct": c.top_holding_weight_pct,
                "top3_weight_pct": c.top3_weight_pct,
                "n_holdings": c.n_holdings,
            },
            evidence=[
                {"label": "Herfindahl-Hirschman Index (concentration)", "value": str(c.hhi), "source": "computed:analytics/concentration.py"},
                {"label": "Top holding weight", "value": f"{c.top_holding_weight_pct}%", "source": "computed:analytics/concentration.py"},
                {"label": "Top 3 holdings weight", "value": f"{c.top3_weight_pct}%", "source": "computed:analytics/concentration.py"},
            ],
        ))

    # ---- Overlap --------------------------------------------------------
    if bundle.overlap is not None:
        for pair in bundle.overlap.pairs[:3]:  # top 3 worst overlaps
            if pair.overlap_pct < 15:
                continue  # not material enough to surface
            severity = Severity.action if pair.overlap_pct >= 40 else Severity.watch
            candidates.append(CandidateInsight(
                category=InsightCategory.overlap,
                severity=severity,
                priority_score=SEVERITY_BASE_SCORE[severity] + pair.overlap_pct / 2,
                raw_facts={
                    "fund_a": pair.fund_name_a,
                    "fund_b": pair.fund_name_b,
                    "overlap_pct": pair.overlap_pct,
                    "shared_stocks": pair.shared_stocks,
                },
                evidence=[
                    {"label": f"Weighted holdings overlap: {pair.fund_name_a} vs {pair.fund_name_b}",
                     "value": f"{pair.overlap_pct}%", "source": "computed:analytics/overlap.py"},
                    {"label": "Shared top holdings", "value": ", ".join(pair.shared_stocks),
                     "source": "computed:analytics/overlap.py"},
                ],
            ))

    # ---- Suitability ------------------------------------------------
    for flag in bundle.suitability.flags:
        candidates.append(CandidateInsight(
            category=InsightCategory.suitability,
            severity=Severity.action,
            priority_score=SEVERITY_BASE_SCORE[Severity.action] + 5,
            raw_facts={"flag_code": flag.code, "message": flag.message},
            evidence=[
                {"label": "Suitability rule triggered", "value": flag.code, "source": "computed:analytics/suitability.py"},
                {"label": "Detail", "value": flag.message, "source": "computed:analytics/suitability.py"},
            ],
        ))

    # ---- Risk / performance outliers per fund ------------------------
    for code, perf in bundle.performance_by_scheme.items():
        if perf.vs_category_1yr_gap_pct is None:
            continue
        if abs(perf.vs_category_1yr_gap_pct) < 4:
            continue  # not a material gap
        severity = Severity.watch if perf.vs_category_1yr_gap_pct < 0 else Severity.info
        from data_sources import get_fund_metadata
        meta = get_fund_metadata(code)
        fund_name = meta["scheme_name"] if meta else code
        candidates.append(CandidateInsight(
            category=InsightCategory.performance,
            severity=severity,
            priority_score=SEVERITY_BASE_SCORE[severity] + abs(perf.vs_category_1yr_gap_pct),
            raw_facts={
                "fund_name": fund_name,
                "scheme_code": code,
                "return_1yr_pct": perf.return_1yr_pct,
                "category_typical_1yr_pct": perf.category_typical_1yr_pct,
                "gap_pct": perf.vs_category_1yr_gap_pct,
            },
            evidence=[
                {"label": f"{fund_name} 1yr return", "value": f"{perf.return_1yr_pct}%", "source": "computed:analytics/performance.py"},
                {"label": "Category typical 1yr return", "value": f"{perf.category_typical_1yr_pct}%", "source": "data:category_benchmarks"},
                {"label": "Gap vs category", "value": f"{perf.vs_category_1yr_gap_pct} percentage points", "source": "computed:analytics/performance.py"},
            ],
        ))

    # ---- Cost (expense ratio) ------------------------------------------
    if bundle.weighted_expense_ratio_pct is not None and bundle.weighted_expense_ratio_pct > 1.15:
        candidates.append(CandidateInsight(
            category=InsightCategory.cost,
            severity=Severity.watch,
            priority_score=SEVERITY_BASE_SCORE[Severity.watch] + bundle.weighted_expense_ratio_pct,
            raw_facts={"weighted_expense_ratio_pct": bundle.weighted_expense_ratio_pct},
            evidence=[
                {"label": "Portfolio-weighted expense ratio", "value": f"{bundle.weighted_expense_ratio_pct}%",
                 "source": "computed:insights/engine.py"},
            ],
        ))

    # ---- Data quality (always surfaced, low severity by default) -----
    if bundle.data_quality_notes:
        candidates.append(CandidateInsight(
            category=InsightCategory.data_quality,
            severity=Severity.info,
            priority_score=SEVERITY_BASE_SCORE[Severity.info] + len(bundle.data_quality_notes),
            raw_facts={"notes": [f"{n.issue} ({n.impact})" for n in bundle.data_quality_notes]},
            evidence=[
                {"label": f"Data quality issue #{i+1}", "value": n.issue, "source": "system"}
                for i, n in enumerate(bundle.data_quality_notes)
            ],
        ))

    candidates.sort(key=lambda c: c.priority_score, reverse=True)
    return candidates
