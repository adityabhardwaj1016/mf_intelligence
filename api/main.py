"""
api/main.py — thin FastAPI wrapper around insights.pipeline.analyze_portfolio.

Run with: uvicorn api.main:app --reload --app-dir mf_intelligence
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from data_sources import data_mode, list_all_scheme_codes, get_fund_metadata
from insights.pipeline import analyze_portfolio
from schemas import AnalysisRequest, AnalysisResponse

app = FastAPI(
    title="Mutual Fund Portfolio Intelligence System",
    description="Prototype: turns an investor profile + mutual fund portfolio "
                "into a small set of prioritized, evidence-backed insights.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # prototype-scope: permissive for local/demo use
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "data_mode": data_mode()}


@app.get("/funds")
def list_funds():
    """Full fund metadata (not just scheme codes) so the frontend can build
    a picker without extra round trips."""
    funds = []
    for code in list_all_scheme_codes():
        meta = get_fund_metadata(code)
        funds.append({
            "scheme_code": code,
            "scheme_name": meta["scheme_name"],
            "category": meta["category"],
            "sub_category": meta["sub_category"],
            "amc": meta["amc"],
            "expense_ratio_pct": meta["expense_ratio_pct"],
            "risk_level": meta["risk_level"],
        })
    return {"funds": funds}


@app.post("/analyze", response_model=AnalysisResponse)
def analyze(request: AnalysisRequest):
    try:
        return analyze_portfolio(request)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # A financial intelligence system should fail loudly and safely,
        # never return a partially-broken/garbled response.
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")


# Serve the frontend last: this is a catch-all mount, so every API route
# above must be registered before it or it would shadow them. Starlette
# matches routes in registration order, so /health, /funds, /analyze all
# take priority over this mount for their exact paths.
import os
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
