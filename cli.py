"""
cli.py — run an analysis without standing up the API.

Usage:
    python cli.py --demo well_diversified
    python cli.py --demo concentrated
    python cli.py --demo missing_data
    python cli.py --input path/to/request.json
    python cli.py --list-funds
"""

from __future__ import annotations

import argparse
import json
import sys

from data_sources import list_all_scheme_codes, get_fund_metadata
from insights.pipeline import analyze_portfolio
from schemas import AnalysisRequest
from tests.test_cases import DEMO_PORTFOLIOS


def main():
    parser = argparse.ArgumentParser(description="Mutual Fund Portfolio Intelligence System")
    parser.add_argument("--input", type=str, help="Path to a JSON file matching the AnalysisRequest schema")
    parser.add_argument("--demo", type=str, choices=list(DEMO_PORTFOLIOS.keys()),
                         help="Run one of the built-in demo portfolios")
    parser.add_argument("--list-funds", action="store_true", help="List available scheme codes and exit")
    parser.add_argument("--pretty", action="store_true", default=True)
    args = parser.parse_args()

    if args.list_funds:
        for code in list_all_scheme_codes():
            meta = get_fund_metadata(code)
            print(f"{code}  {meta['scheme_name']:<32}  {meta['sub_category']:<20}  risk={meta['risk_level']}")
        return

    if args.input:
        raw = json.loads(open(args.input).read())
        request = AnalysisRequest.model_validate(raw)
    elif args.demo:
        request = DEMO_PORTFOLIOS[args.demo]
    else:
        parser.print_help()
        sys.exit(1)

    response = analyze_portfolio(request)
    print(json.dumps(response.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
