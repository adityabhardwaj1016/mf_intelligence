"""
tests/run_eval.py

The "how do you know the system actually works" deliverable. Three kinds
of checks, run against every demo case:

1. Structural validity — output parses as AnalysisResponse (schema
   validation is not optional; a malformed response is an automatic fail).
2. Expectation checks — from EXPECTATIONS in test_cases.py, e.g. "the
   concentrated portfolio MUST surface a concentration insight",
   "the well-diversified one must NOT surface a high-severity one".
3. Engineered failure cases — inputs designed to break a naive
   implementation (bad scheme code, no invested_amount, single holding,
   empty-ish data) and confirmed to degrade gracefully instead of
   crashing or fabricating.

Run: python -m tests.run_eval
"""

from __future__ import annotations

import sys

from insights.pipeline import analyze_portfolio
from schemas import AnalysisResponse
from tests.test_cases import DEMO_PORTFOLIOS, EXPECTATIONS

PASS = "PASS"
FAIL = "FAIL"

results = []


def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail and status == FAIL else ""))


def run_case(case_name: str):
    request = DEMO_PORTFOLIOS[case_name]
    expectations = EXPECTATIONS.get(case_name, {})

    try:
        response = analyze_portfolio(request)
    except Exception as e:
        check(f"{case_name}: does not crash", False, f"raised {type(e).__name__}: {e}")
        return

    check(f"{case_name}: does not crash", True)

    # 1. Structural validity — round-trip through the schema
    try:
        AnalysisResponse.model_validate(response.model_dump(mode="json"))
        check(f"{case_name}: output matches AnalysisResponse schema", True)
    except Exception as e:
        check(f"{case_name}: output matches AnalysisResponse schema", False, str(e))

    categories_present = {i.category.value for i in response.insights}
    severities_by_category = {}
    for i in response.insights:
        severities_by_category.setdefault(i.category.value, []).append(i.severity.value)

    if "must_have_categories" in expectations:
        for cat in expectations["must_have_categories"]:
            check(f"{case_name}: has '{cat}' insight",
                  cat in categories_present,
                  f"present categories: {categories_present}")

    if "must_not_have_categories_at_severity" in expectations:
        for cat, sev in expectations["must_not_have_categories_at_severity"]:
            bad = sev in severities_by_category.get(cat, [])
            check(f"{case_name}: no '{cat}' insight at severity '{sev}'", not bad)

    if "min_data_quality_notes" in expectations:
        n = len(response.data_quality_notes)
        check(f"{case_name}: at least {expectations['min_data_quality_notes']} data quality notes",
              n >= expectations["min_data_quality_notes"], f"got {n}")

    # 2. Every insight's evidence list must be non-empty (no unsupported insight)
    for i, insight in enumerate(response.insights):
        check(f"{case_name}: insight[{i}] '{insight.title[:40]}' has evidence",
              len(insight.evidence) > 0)

    # 3. Confidence must be within bounds (schema enforces this too, belt & braces)
    for i, insight in enumerate(response.insights):
        check(f"{case_name}: insight[{i}] confidence in [0,1]",
              0.0 <= insight.confidence <= 1.0)

    # 4. Hallucination guard regression check: every number in an insight's
    # explanation must trace back to that insight's own evidence (or a small
    # set of universally-safe connective numbers / investor-profile numbers).
    # This directly tests insights/validator.py end-to-end, and would have
    # caught the "gap_pct missing from evidence" bug found during development.
    from insights.validator import _numbers_in, _allowed_numbers
    for i, insight in enumerate(response.insights):
        allowed = _allowed_numbers(insight, request.investor)
        found = _numbers_in(insight.explanation)
        unsupported = [n for n in found if not any(abs(n - a) <= 0.6 for a in allowed)]
        check(f"{case_name}: insight[{i}] explanation fully grounded in evidence",
              len(unsupported) == 0, f"unsupported numbers: {unsupported}")

    return response


def run_failure_case_bad_input():
    """A portfolio with zero holdings should fail validation, not crash deep
    inside the pipeline with a confusing stack trace."""
    from pydantic import ValidationError
    from schemas import AnalysisRequest, InvestorProfile, Portfolio
    try:
        AnalysisRequest(
            investor=InvestorProfile(investor_id="empty_test"),
            portfolio=Portfolio(holdings=[]),
        )
        check("empty portfolio: rejected at validation layer", False, "did not raise")
    except ValidationError:
        check("empty portfolio: rejected at validation layer", True)


def run_failure_case_unresolvable_investor_age():
    """Age far outside plausible bounds should be rejected by schema validation."""
    from pydantic import ValidationError
    from schemas import InvestorProfile
    try:
        InvestorProfile(investor_id="bad_age", age=250)
        check("implausible age: rejected at validation layer", False, "did not raise")
    except ValidationError:
        check("implausible age: rejected at validation layer", True)


def main():
    for case_name in DEMO_PORTFOLIOS:
        run_case(case_name)

    run_failure_case_bad_input()
    run_failure_case_unresolvable_investor_age()

    n_pass = sum(1 for _, s, _ in results if s == PASS)
    n_fail = sum(1 for _, s, _ in results if s == FAIL)
    print(f"\n{'='*60}\n{n_pass} passed, {n_fail} failed, {len(results)} total checks\n{'='*60}")

    if n_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
