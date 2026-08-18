"""
Generates the local sample dataset used by this prototype.

WHY THIS FILE EXISTS (read this — it's the most important limitation
in the whole project, and it's documented here AND in the README):

This project was built in a sandboxed environment with no network access
to amfiindia.com, api.mfapi.in, or kaggle.com. In a real deployment, the
functions in `data_sources.py` marked `# LIVE` would be used instead of
this file. To keep the prototype runnable and demonstrable end-to-end
without external network access, this script generates a LOCAL,
STRUCTURALLY REALISTIC dataset:

  - Fund catalog shaped exactly like what AMFI + a fact-sheet aggregator
    would give you (scheme code, category, sub-category, AMC, expense
    ratio, risk level, launch date).
  - Daily NAV history generated via a random walk calibrated to
    category-typical drift/volatility (e.g. small cap = higher vol/drift
    than liquid funds), NOT copied from any real fund.
  - Top-10 holdings per equity fund, drawn from a fixed universe of real,
    large, liquid NSE-listed companies (this part IS realistic — big
    equity funds in a given category genuinely do cluster around the same
    ~30-40 large-cap names, which is exactly what makes "overlap" a real
    phenomenon worth detecting).

Fund names are intentionally fictional ("Horizon Bluechip Fund" etc.)
rather than real AMC scheme names, because attaching synthetic NAV/return
numbers to a real fund's real name would misrepresent that fund's actual
performance. The category structure, expense ratios, and risk metrics are
all within realistic real-world ranges for their category.

Swapping this for live data means: implement the `# LIVE` functions in
data_sources.py (skeletons already provided) and set
MF_INTELLIGENCE_DATA_MODE=live. Nothing else in the analytics or insight
layers needs to change, because they only depend on the schemas in
data_sources.py, not on how the data was produced.
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

OUT_DIR = Path(__file__).parent

# --------------------------------------------------------------------------
# 1. Fund catalog
# --------------------------------------------------------------------------

# (category, sub_category, annualised_drift, annualised_vol, expense_ratio, risk_level)
CATEGORY_PROFILES = {
    "large_cap":        ("Equity", "Large Cap",        0.12, 0.15, 0.9,  4),
    "flexi_cap":        ("Equity", "Flexi Cap",         0.13, 0.17, 1.0,  4),
    "mid_cap":          ("Equity", "Mid Cap",           0.15, 0.22, 1.1,  5),
    "small_cap":        ("Equity", "Small Cap",         0.16, 0.27, 1.3,  6),
    "elss":             ("Equity", "ELSS (Tax Saving)", 0.13, 0.18, 1.0,  5),
    "hybrid_aggressive":("Hybrid", "Aggressive Hybrid",  0.10, 0.12, 0.9,  4),
    "debt_short":       ("Debt",   "Short Duration",     0.065, 0.02, 0.5, 2),
    "liquid":           ("Debt",   "Liquid",             0.06,  0.005,0.25,1),
    "gold_fof":         ("Other",  "Gold FoF",            0.09, 0.13, 0.6,  4),
}

FUND_NAME_POOL = [
    "Horizon", "Zenith", "Northstar", "Bluepeak", "Ridgeview", "Meridian",
    "Silverline", "Anchorage", "Highbridge", "Crestwood", "Bayline", "Foxglove",
    "Summit", "Lakeshore", "Cobalt", "Windermere", "Fernhill", "Ashgrove",
    "Redcliff", "Pinehurst", "Kingsford", "Oakvale", "Stonebridge", "Millrace",
    "Copperfield", "Wrenfield",
]

SUFFIX_BY_CATEGORY = {
    "large_cap": "Bluechip Fund",
    "flexi_cap": "Flexi Cap Fund",
    "mid_cap": "Mid Cap Growth Fund",
    "small_cap": "Small Cap Fund",
    "elss": "Tax Saver Fund",
    "hybrid_aggressive": "Balanced Advantage Fund",
    "debt_short": "Short Term Debt Fund",
    "liquid": "Liquid Fund",
    "gold_fof": "Gold Fund of Fund",
}

AMCS = ["Northbridge MF", "Cardinal MF", "Alpine Asset Mgmt", "Solstice MF", "Vantage MF"]

funds = []
scheme_code_counter = 100001

for cat_key, (category, sub_category, drift, vol, exp_ratio, risk_level) in CATEGORY_PROFILES.items():
    # 2-3 funds per category, from different AMCs, so overlap has something to detect
    n_funds = 3 if category == "Equity" else 2
    for i in range(n_funds):
        name_prefix = random.choice(FUND_NAME_POOL)
        FUND_NAME_POOL.remove(name_prefix)  # unique names
        fund_name = f"{name_prefix} {SUFFIX_BY_CATEGORY[cat_key]}"
        amc = random.choice(AMCS)
        launch_year = random.randint(2008, 2019)
        funds.append({
            "scheme_code": str(scheme_code_counter),
            "scheme_name": fund_name,
            "amc": amc,
            "category": category,
            "sub_category": sub_category,
            "expense_ratio_pct": round(exp_ratio + random.uniform(-0.15, 0.15), 2),
            "risk_level": risk_level,  # 1 (low) - 6 (very high), SEBI riskometer style
            "launch_date": f"{launch_year}-04-01",
            "_drift": drift,
            "_vol": vol,
        })
        scheme_code_counter += 1

# --------------------------------------------------------------------------
# 2. NAV history (5 years, daily, business days only)
# --------------------------------------------------------------------------

def business_days(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)

start_date = date(2020, 8, 17)
end_date = date(2026, 8, 14)  # last trading day before "today" in this project's timeline
all_days = list(business_days(start_date, end_date))
n_days = len(all_days)
dt = 1 / 252  # trading-day fraction of a year

nav_history = {}
for f in funds:
    drift, vol = f["_drift"], f["_vol"]
    nav = 20.0 if f["category"] != "Debt" else 1000.0  # plausible starting NAV levels
    series = []
    for d in all_days:
        shock = random.gauss(0, 1)
        # simple GBM-style daily step calibrated to category drift/vol
        daily_return = (drift - 0.5 * vol ** 2) * dt + vol * (dt ** 0.5) * shock
        nav = max(nav * (1 + daily_return), 0.01)
        series.append({"date": d.isoformat(), "nav": round(nav, 4)})
    nav_history[f["scheme_code"]] = series

# --------------------------------------------------------------------------
# 3. Category benchmark returns (for suitability / relative performance)
# --------------------------------------------------------------------------

category_benchmarks = {}
for cat_key, (category, sub_category, drift, vol, exp_ratio, risk_level) in CATEGORY_PROFILES.items():
    category_benchmarks[sub_category] = {
        "category": category,
        "sub_category": sub_category,
        "typical_1yr_return_pct": round(drift * 100 + random.uniform(-2, 2), 2),
        "typical_3yr_cagr_pct": round(drift * 100 + random.uniform(-1, 1), 2),
        "typical_annualised_volatility_pct": round(vol * 100, 2),
    }

# --------------------------------------------------------------------------
# 4. Holdings (equity funds only) — drawn from a fixed universe of large,
#    real, liquid NSE-listed companies so that overlap is realistic.
# --------------------------------------------------------------------------

STOCK_UNIVERSE_LARGE = [
    "HDFC Bank", "ICICI Bank", "Reliance Industries", "Infosys", "TCS",
    "Larsen & Toubro", "Axis Bank", "Kotak Mahindra Bank", "Bharti Airtel",
    "ITC", "State Bank of India", "Hindustan Unilever",
]
STOCK_UNIVERSE_MID = [
    "Persistent Systems", "Cummins India", "Coforge", "Astral Ltd",
    "Page Industries", "Trent Ltd", "Federal Bank", "Voltas",
    "AU Small Finance Bank", "Indian Hotels",
]
STOCK_UNIVERSE_SMALL = [
    "Blue Star", "KEI Industries", "Cera Sanitaryware", "Gravita India",
    "Sonata Software", "Latent View Analytics", "Route Mobile",
    "Anupam Rasayan", "Rainbow Children's Medicare", "Suven Pharma",
]

holdings = {}
for f in funds:
    if f["category"] != "Equity":
        continue
    if f["sub_category"] == "Small Cap":
        universe = STOCK_UNIVERSE_SMALL + random.sample(STOCK_UNIVERSE_MID, 3)
    elif f["sub_category"] == "Mid Cap":
        universe = STOCK_UNIVERSE_MID + random.sample(STOCK_UNIVERSE_LARGE, 2)
    else:  # Large cap, flexi cap, ELSS lean large-cap heavy
        universe = STOCK_UNIVERSE_LARGE + random.sample(STOCK_UNIVERSE_MID, 4)

    chosen = random.sample(universe, min(10, len(universe)))
    weights = sorted([random.uniform(2, 9) for _ in chosen], reverse=True)
    total = sum(weights)
    weights = [round(w / total * random.uniform(55, 75), 2) for w in weights]  # top10 typically ~55-75% of portfolio
    holdings[f["scheme_code"]] = [
        {"stock": s, "weight_pct": w} for s, w in zip(chosen, weights)
    ]

# --------------------------------------------------------------------------
# Write outputs
# --------------------------------------------------------------------------

for f in funds:
    del f["_drift"], f["_vol"]

(OUT_DIR / "fund_catalog.json").write_text(json.dumps(funds, indent=2))
(OUT_DIR / "nav_history.json").write_text(json.dumps(nav_history))
(OUT_DIR / "category_benchmarks.json").write_text(json.dumps(category_benchmarks, indent=2))
(OUT_DIR / "holdings.json").write_text(json.dumps(holdings, indent=2))

print(f"Generated {len(funds)} funds, {n_days} trading days of NAV history each.")
print(f"Holdings generated for {len(holdings)} equity funds.")
