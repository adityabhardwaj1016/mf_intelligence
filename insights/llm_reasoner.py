"""
insights/llm_reasoner.py

This is the ONLY module in the whole project that talks to an LLM. Its
job is narrow and deliberate: turn a list of already-computed,
already-scored CandidateInsight objects into readable, personalized
title/explanation text — and decide which of the top-ranked candidates
are actually worth surfacing together (e.g. skip a candidate if it's
redundant with a higher-priority one already selected).

What the LLM is explicitly NOT allowed to do:
  - Invent a number. It receives only the `raw_facts` / `evidence`
    already computed deterministically, and is instructed to reference
    only those. insights/validator.py then checks this after the fact
    by extracting every number in the generated text and confirming it
    traces back to a known evidence value.
  - Change severity or reorder priority. Those come from prioritizer.py.
  - Add a new insight category not already in the candidate list.

Structured output is enforced via Anthropic tool-calling (the model must
call `emit_insights` with arguments matching our schema) rather than
asking it to "please return JSON" and hoping — tool-use forces the shape.

FALLBACK MODE: if no ANTHROPIC_API_KEY is configured, or the API call
fails for any reason (network, rate limit, malformed response), this
module falls back to deterministic templated explanations built directly
from raw_facts. The system stays fully functional without an LLM — which
is itself a deliberate demonstration of "using more AI does not make the
solution better": the LLM adds fluency and personalization, but the
insights themselves already exist without it.
"""

from __future__ import annotations

import json
import os
import re

from schemas import Evidence, Insight, InsightCategory, InvestorProfile, Severity
from insights.prioritizer import CandidateInsight

MAX_INSIGHTS_SURFACED = 6

EMIT_INSIGHTS_TOOL = {
    "name": "emit_insights",
    "description": "Emit the final, investor-facing set of insights.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "One sentence summarising the single most important takeaway for this investor.",
            },
            "insights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_index": {
                            "type": "integer",
                            "description": "Index into the provided candidate list this insight corresponds to.",
                        },
                        "title": {"type": "string", "description": "Short, specific, under 12 words."},
                        "explanation": {
                            "type": "string",
                            "description": "2-4 sentences. Must reference ONLY numbers present in that "
                                           "candidate's evidence/raw_facts. Explain why it matters to THIS investor.",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "0.0-1.0. Lower if the underlying data was thin or an assumption was needed.",
                        },
                        "keep": {
                            "type": "boolean",
                            "description": "False if this candidate is redundant with a higher-priority one "
                                           "already included, or not meaningfully actionable for this investor.",
                        },
                    },
                    "required": ["candidate_index", "title", "explanation", "confidence", "keep"],
                },
            },
        },
        "required": ["headline", "insights"],
    },
}


def _build_prompt(investor: InvestorProfile, candidates: list[CandidateInsight]) -> str:
    investor_json = investor.model_dump(mode="json")
    candidates_json = [
        {
            "index": i,
            "category": c.category.value,
            "severity": c.severity.value,
            "raw_facts": c.raw_facts,
        }
        for i, c in enumerate(candidates)
    ]
    return f"""You are the reasoning layer of a mutual fund portfolio intelligence system.
You will be given an investor profile and a list of pre-computed, pre-prioritized
candidate insights (the numbers were computed by deterministic financial code,
not by you). Your job is ONLY to:

1. Write a short, specific title and a 2-4 sentence explanation for each candidate
   worth surfacing, personalized to this investor's profile.
2. Decide which candidates to keep vs drop (drop if redundant with a
   higher-severity candidate already kept, or not meaningful for this investor).
3. Write one headline sentence capturing the single most important takeaway.

STRICT RULES:
- Never state a number that is not present in that candidate's raw_facts.
- Never invent a fact about a fund, category, or the investor not given to you.
- If raw_facts don't give you enough to say anything specific, set confidence low
  and keep the explanation general rather than fabricating specifics.
- Do not give explicit buy/sell/switch instructions — describe what the data
  shows and why it's worth the investor's attention, and let them decide.

INVESTOR PROFILE:
{json.dumps(investor_json, indent=2)}

CANDIDATE INSIGHTS (already prioritized, ordered by importance):
{json.dumps(candidates_json, indent=2)}

Call emit_insights with your result. Surface at most {MAX_INSIGHTS_SURFACED} insights."""


def _call_claude(prompt: str) -> dict | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            tools=[EMIT_INSIGHTS_TOOL],
            tool_choice={"type": "tool", "name": "emit_insights"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "emit_insights":
                return block.input
        return None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Deterministic fallback (no LLM) — templated explanations from raw_facts
# --------------------------------------------------------------------------

def _template_explanation(c: CandidateInsight) -> tuple[str, str]:
    f = c.raw_facts
    if c.category == InsightCategory.concentration:
        return (
            f"Portfolio concentration is {f['interpretation']}",
            f"Your top holding is {f['top_holding_weight_pct']}% of the portfolio and your top 3 "
            f"holdings together make up {f['top3_weight_pct']}% across {f['n_holdings']} funds "
            f"(HHI: {f['hhi']}).",
        )
    if c.category == InsightCategory.overlap:
        return (
            f"{f['fund_a']} and {f['fund_b']} overlap significantly",
            f"These two funds share {f['overlap_pct']}% weighted exposure to the same holdings "
            f"({', '.join(f['shared_stocks'][:5])}{'...' if len(f['shared_stocks']) > 5 else ''}), "
            f"meaning holding both provides less diversification benefit than it may appear.",
        )
    if c.category == InsightCategory.suitability:
        return ("Suitability check flagged", f["message"])
    if c.category == InsightCategory.performance:
        return (
            f"{f['fund_name']}: 1yr return vs category",
            f"{f['fund_name']} returned {f['return_1yr_pct']}% over the last year vs a typical "
            f"{f['category_typical_1yr_pct']}% for its category, a gap of {f['gap_pct']} percentage points.",
        )
    if c.category == InsightCategory.cost:
        return (
            "Portfolio-weighted expense ratio is on the higher side",
            f"Your portfolio's asset-weighted expense ratio is {f['weighted_expense_ratio_pct']}%, "
            f"which compounds over long holding periods.",
        )
    if c.category == InsightCategory.data_quality:
        return ("Some data gaps affected this analysis", "; ".join(f["notes"][:3]))
    return ("Insight", "See evidence for details.")


def _fallback_reasoning(candidates: list[CandidateInsight]) -> dict:
    top = candidates[:MAX_INSIGHTS_SURFACED]
    insights = []
    for i, c in enumerate(top):
        title, explanation = _template_explanation(c)
        insights.append({
            "candidate_index": i,
            "title": title,
            "explanation": explanation,
            "confidence": 0.75,  # templated from verified facts, but not personalized by an LLM
            "keep": True,
        })
    headline = (
        _template_explanation(top[0])[0] if top else "No material insights found for this portfolio."
    )
    return {"headline": headline, "insights": insights}


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def reason_over_candidates(
    investor: InvestorProfile, candidates: list[CandidateInsight]
) -> tuple[str, list[Insight], str]:
    """
    Returns (headline, list[Insight], mode) where mode is "llm" or "fallback_template".
    """
    if not candidates:
        return (
            "No material insights were found for this portfolio with the data available.",
            [],
            "fallback_template",
        )

    top_candidates = candidates[: max(MAX_INSIGHTS_SURFACED * 2, 10)]  # give the LLM some to drop from
    prompt = _build_prompt(investor, top_candidates)
    llm_result = _call_claude(prompt)
    mode = "llm"
    if llm_result is None:
        llm_result = _fallback_reasoning(top_candidates)
        mode = "fallback_template"

    insights: list[Insight] = []
    for item in llm_result.get("insights", []):
        if not item.get("keep", True):
            continue
        idx = item.get("candidate_index")
        if idx is None or not (0 <= idx < len(top_candidates)):
            continue
        candidate = top_candidates[idx]
        evidence = [Evidence(**e) for e in candidate.evidence]
        insights.append(Insight(
            category=candidate.category,
            severity=candidate.severity,
            title=item["title"],
            explanation=item["explanation"],
            evidence=evidence,
            confidence=float(item.get("confidence", 0.7)),
        ))

    headline = llm_result.get("headline", "Portfolio analysis complete.")
    return headline, insights, mode
