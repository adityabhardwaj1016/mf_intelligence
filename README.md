# Mutual Fund Portfolio Intelligence System — Prototype

Built for the RupeeStop AI Engineer assignment. Answers, for a given
investor + mutual fund portfolio:

> **"What are the most important things this investor should know about
> their mutual fund portfolio, and why?"**

Run it in 30 seconds:

```bash
pip install -r requirements.txt
python data/generate_sample_data.py     # already run; regenerate anytime
uvicorn api.main:app --reload --app-dir .
```

Then open **http://localhost:8000/** in a browser — that's the full website
(build a portfolio on the left, click "Analyze portfolio", see live results
on the right). It's the same FastAPI app serving both the UI and the API,
so there's nothing else to start.

Prefer the terminal? `python cli.py --demo concentrated` shows a full
analysis without a browser.

Optional: set `ANTHROPIC_API_KEY` to enable LLM-generated explanations.
Without it, the system runs in a deterministic templated-explanation
fallback mode — see [Technical Decisions](#technical-decisions--trade-offs).

---

## 1. Architecture

```
                    ┌─────────────────────┐
 AnalysisRequest →  │  insights/pipeline.py │  → AnalysisResponse
 (investor +        └──────────┬───────────┘   (structured JSON)
  portfolio)                   │
                                ▼
                 ┌──────────────────────────────┐
                 │ 1. insights/engine.py          │  DETERMINISTIC
                 │    orchestrates analytics/*:    │
                 │    allocation, concentration,   │
                 │    overlap, risk, performance,  │
                 │    suitability                  │
                 │    → AnalysisBundle (facts)     │
                 └──────────────┬───────────────┘
                                ▼
                 ┌──────────────────────────────┐
                 │ 2. insights/prioritizer.py     │  DETERMINISTIC
                 │    rule-based scoring/ranking   │
                 │    → CandidateInsight[]         │
                 │    (category, severity, evidence)│
                 └──────────────┬───────────────┘
                                ▼
                 ┌──────────────────────────────┐
                 │ 3. insights/llm_reasoner.py    │  LLM (or fallback)
                 │    explains + personalizes +    │
                 │    selects top candidates       │
                 │    → Insight[] (title, prose)   │
                 └──────────────┬───────────────┘
                                ▼
                 ┌──────────────────────────────┐
                 │ 4. insights/validator.py       │  DETERMINISTIC
                 │    hallucination guard: every   │
                 │    number in LLM prose must      │
                 │    trace back to evidence        │
                 └──────────────────────────────┘
```

**Why this shape, specifically:** each stage has exactly one kind of
decision to make, and only one. Stage 1 computes facts. Stage 2 decides
what's *important* (a fixed rule, so it's reproducible). Stage 3
decides how to *say* it. Stage 4 checks stage 3 didn't lie. No stage can
silently do another stage's job — e.g. the LLM in stage 3 physically
cannot introduce a new financial figure, because stage 4 checks for
exactly that and flags it if it happens (this actually caught a real bug
during development — see §5).

A rendered version of this diagram is at `architecture.svg`.

Interfaces: `api/main.py` (FastAPI, `POST /analyze`) and `cli.py` both
call the same `insights.pipeline.analyze_portfolio()` — there's one
pipeline, two thin entry points, per the assignment's "no requirement to
build a polished frontend."

### File map

```
schemas.py              Pydantic contracts for input/output (single source of truth)
data_sources.py          Data access abstraction (sample mode / live mode)
data/generate_sample_data.py   Generates local sample dataset (see §2)
analytics/
  allocation.py           Portfolio value resolution, category/AMC weights
  concentration.py         HHI, top-N weight concentration
  overlap.py                Weighted holdings overlap between fund pairs
  risk.py                    Volatility, max drawdown, Sharpe (from NAV history)
  performance.py             CAGR, returns vs category benchmark
  suitability.py              Rule-based investor-profile-vs-portfolio checks
insights/
  engine.py                Orchestrates analytics/* into one AnalysisBundle
  prioritizer.py             Scores/ranks candidate insights (deterministic)
  llm_reasoner.py             LLM explanation layer + deterministic fallback
  validator.py                 Hallucination guard
  pipeline.py                    Wires the above into analyze_portfolio()
api/main.py               FastAPI app (also serves frontend/ as static files at "/")
frontend/index.html       Single-file website: form → POST /analyze → rendered insights
cli.py                     CLI entry point
tests/
  test_cases.py            5 demo portfolios + expected-outcome assertions
  run_eval.py                Evaluation harness (§5)
sample_output/            Saved outputs from the 5 demo portfolios
```

---

## 2. Data Research

### What I looked at and chose

| Source | What it gives you | Verdict |
|---|---|---|
| **AMFI** (amfiindia.com) | Official daily NAV feed, all schemes | Ground truth for prices. No holdings, no category metadata. |
| **mfapi.in** | Free unofficial JSON wrapper around AMFI NAV history | Easiest way to get historical NAV for return/volatility calculations. Unofficial → no SLA, worth cross-checking against AMFI directly in production. |
| **AMC fact sheets** (PDFs) | Holdings, category, expense ratio, risk metrics | The *only* real source for stock-level holdings, which overlap/concentration analysis needs. Unstructured, monthly, inconsistent format across ~40 AMCs — this is the single biggest practical bottleneck in a real system. |
| **Kaggle** ("India's Ultimate Mutual Fund Dataset", "Mutual Funds India - Detailed") | Pre-aggregated NAV + category + Sharpe/Sortino/Beta/expense ratio | Good for fast prototyping; some are static scrapes (stale), none include stock-level holdings. |
| Value Research / Morningstar-style aggregators | Richer category averages, ratings | Scraping raises ToS concerns — noted, not used. |

**Decision:** use AMFI/mfapi.in-shaped NAV data as the performance/risk
backbone, and a small hand-curated top-10-holdings dataset (in the shape
fact sheets provide) as the overlap/concentration backbone.

### Why this submission ships with generated sample data, not live data

**The sandboxed build environment this project was developed in has no
network access to `amfiindia.com`, `api.mfapi.in`, or `kaggle.com`.**
Rather than submit a system that only works in principle, I built
`data_sources.py` as a real abstraction boundary:

- `data/generate_sample_data.py` produces a **structurally realistic**
  local dataset: 23 funds across 9 real fund categories, 5+ years of
  daily NAV generated via a random walk calibrated to
  category-appropriate drift/volatility (small-cap ≠ liquid fund
  volatility, etc.), and top-10 holdings for equity funds drawn from a
  fixed universe of real, large, liquid NSE-listed stocks — so overlap
  between funds is a genuine, detectable phenomenon, not noise.
- Fund and stock *names* are fictional. Attaching synthetic performance
  numbers to a real fund's real name would misrepresent that fund —
  so `Kingsford Bluechip Fund` is fictional, `HDFC Bank` (a holding)
  is real, and no synthetic return number is ever attached to a real
  company.
- `data_sources.py` has working, unexercised `# LIVE` implementations of
  `_live_fetch_nav_history()` (hits `api.mfapi.in`) and
  `_live_fetch_amfi_nav_snapshot()` (hits AMFI directly, intended as a
  cross-check). Setting `MF_INTELLIGENCE_DATA_MODE=live` routes through
  these instead. Nothing in `analytics/`, `insights/`, `api/`, or `cli.py`
  needs to change — they only depend on `data_sources.py`'s functions,
  not on where the data actually came from.
- The one gap live mode does **not** solve here: fund category/holdings
  metadata still needs a fact-sheet ingestion pipeline, which is a real
  sub-project (PDF parsing per-AMC format) intentionally out of scope for
  a prototype. This is flagged as an explicit limitation, not glossed over.

This is the single most important assumption in the whole submission —
stated here as clearly as I can state it.

---

## 3. Technical Decisions & Trade-offs

**Deterministic vs. LLM — the line I drew, and why:**

Everything with one mathematically correct answer is code:
allocation %, HHI, weighted overlap, volatility, max drawdown, Sharpe,
CAGR, and the suitability rules (e.g. "short horizon + high equity" is a
fixed threshold check). An LLM asked to compute these would (a) be less
accurate than a formula, (b) be non-reproducible run-to-run, and (c)
actively invites the exact hallucination risk the assignment calls out.

The LLM's job is narrowly: turn a list of already-decided, already-scored
facts into readable, personalized prose, and make one judgment call —
which of the top-ranked candidates are redundant/not worth surfacing
together. That's a genuinely LLM-shaped task (language + relevance
judgment) that a rule engine does badly, and it's the *only* thing I let
it do.

**Trade-off — rule-based prioritizer vs. LLM-based prioritizer:**
I chose fixed scoring rules (`SEVERITY_BASE_SCORE + magnitude`) over
asking the LLM to rank insights. Trade-off: less nuance (a rule can't
capture "this matters more because of something subtle in the
combination of two facts"), but full reproducibility and auditability —
the same input always produces the same severity/ranking, which matters
a lot more for a financial system than for, say, a content
recommendation.

**Trade-off — structured tool-calling vs. "ask for JSON":**
`llm_reasoner.py` forces the LLM to call a tool (`emit_insights`) with a
JSON-schema-constrained input, rather than prompting "please respond in
JSON." Tool-calling is enforced by the API; free-text JSON is not.

**Trade-off — deterministic fallback when no LLM is available:**
If `ANTHROPIC_API_KEY` isn't set, or the API call fails for any reason,
`llm_reasoner.py` falls back to templated explanations built directly
from the same `raw_facts` the LLM would have used. The system stays
100% functional and evidence-backed with zero LLM involvement — which is
also a working demonstration of the assignment's "using more AI does not
make the solution better" principle: the LLM adds fluency and
personalization on top of an already-complete analysis, it doesn't
create the analysis.

**Trade-off — RAG/vector store: not used.**
There's no unstructured document corpus in this system that benefits
from retrieval (fact sheets, if ingested, would be parsed into
structured holdings data, not embedded for semantic search). Adding a
vector store here would be exactly the kind of AI-for-its-own-sake the
brief warns against.

**Trade-off — overlap metric: weighted top-10 overlap vs. full portfolio /
return-correlation overlap.**
I used `sum(min(weight_A, weight_B))` over shared top-10 holdings — simple,
explainable, and defensible, but it (a) only sees the top 10 disclosed
holdings, not the full portfolio, and (b) is not the same concept as
return correlation between funds. Both are legitimate metrics; I picked
the one that's directly interpretable as "% of your money invested in the
literal same companies," and said explicitly that correlation-based
overlap is a different, unaddressed concept — see `analytics/overlap.py` docstring.

---

## 4. Reliability & Edge Cases

Concrete handling for each scenario the assignment calls out:

| Scenario | Handling |
|---|---|
| Missing/incomplete portfolio data | Unresolvable holdings are excluded from weighted calcs and logged as `DataQualityNote`, never silently zeroed or guessed (`analytics/allocation.py`) |
| Conflicting sources | In live mode, AMFI is documented as source-of-truth for NAV; a discrepancy vs mfapi.in would be surfaced as a data-quality note (not implemented in sample mode, since sample mode has one source) |
| Calculation can't be performed reliably | `analytics/risk.py` and `performance.py` require a minimum data-point threshold (e.g. 60 trading days for volatility) and return `None` + a stated reason otherwise, rather than computing on too little data |
| Scheme/fund info unavailable | Unknown scheme codes are excluded from every calculation and reported by scheme code in `data_quality_notes` |
| LLM lacks evidence to answer | Prompt explicitly instructs "if raw_facts don't give you enough, keep it general and lower confidence rather than fabricate" |
| External tool/API fails | `llm_reasoner._call_claude()` catches all exceptions and falls back to the deterministic template path; the pipeline never crashes because the LLM call failed |
| Retrieved info misleading/malicious | No live retrieval/RAG in this build (see §3); if fact-sheet ingestion were added, it would need source-trust scoring — noted as future work |
| LLM produces unsupported claim | `insights/validator.py` extracts every number from the LLM's explanation text and confirms it traces back to that insight's own evidence; unsupported numbers cap confidence at 0.35 and get flagged in `data_quality_notes` rather than silently trusted |

---

## 5. Evaluation

Two automated test files, run together for **102 total checks**:

```bash
python -m tests.test_analytics_correctness   # 12 checks
python -m tests.run_eval                       # 90 checks
```

### `tests/test_analytics_correctness.py` — formula correctness (12 checks)

The other test file checks end-to-end *behavior* (does a concentrated
portfolio raise a concentration flag). It never checked whether the
underlying formulas were numerically *correct* — a sign error in the
HHI or CAGR formula could still make every behavioral check pass, as
long as it fired a flag in roughly the right direction. This file closes
that gap: every formula is checked against a value calculated by hand
*before* the test was written (shown in each test's comment), including:

- HHI for weights `[50, 30, 20]` = 3800 (2500+900+400)
- HHI for 10 equal 10% holdings = 1000 (perfectly diversified reference point)
- HHI for a single 100% holding = 10000 (theoretical maximum)
- Weighted overlap for two funds with partial share = 10.0 (`min(10,4)+min(6,9)`)
- CAGR from NAV 100→133.1 over 3 years = exactly 10.00% (133.1 = 100×1.1³)
- Annualised volatility from 1% daily std = 15.87% (`0.01 × √252`)
- Conflicting-source detection: 5% NAV discrepancy flagged, 0.1% not flagged

### `tests/run_eval.py` — end-to-end behavior (90 checks)

Five demo portfolios (`tests/test_cases.py`), each engineered to exercise
a specific behavior, with explicit pass/fail expectations (not eyeballed):

1. **`well_diversified`** — 5 funds, different categories/AMCs. Asserts
   NO high-severity concentration flag is raised (a naive
   "flag everything" system would fail this).
2. **`concentrated`** — 80% in one fund, 3 overlapping large-cap-style
   funds. Asserts concentration AND overlap insights ARE raised, with
   HHI above a stated floor.
3. **`missing_data`** — one unknown scheme code, one fund with no
   invested amount. Asserts the system doesn't crash, produces at least
   2 data-quality notes, and still analyzes what it can (see
   `sample_output/missing_data.json`).
4. **`suitability_mismatch`** — short horizon + short-term goal + high
   equity exposure. Asserts suitability flags fire.
5. **`single_holding`** — edge case where overlap analysis is
   structurally impossible (needs ≥2 equity funds). Asserts graceful
   handling, not a crash.

Per-case, per-insight checks (not just per-portfolio):
- Output round-trips through the `AnalysisResponse` Pydantic schema
  (structural validation)
- Every insight has non-empty evidence
- Confidence is in `[0, 1]`
- **Every number in every insight's explanation text is traceable back
  to that insight's own evidence** — this directly evaluates the
  hallucination guard, not just trusts it exists.

Plus two engineered failure-case tests: an empty portfolio and an
implausible investor age are confirmed to be **rejected at the schema
validation layer**, before ever reaching the analysis pipeline.

**A bug this actually caught during development:** the first version of
the "performance vs category" insight template mentioned a computed
"gap" percentage in its explanation text, but the evidence list only
included the two raw return numbers — not the gap itself. The grounding
check in `run_eval.py` failed with `unsupported numbers: [-16.74]`,
correctly flagging that the explanation stated a number not present in
its own evidence. Fixed by adding the gap to the evidence list
(`insights/prioritizer.py`). This is included here deliberately — it's
the exact class of error the validator exists to catch, and it caught a
real one, not a contrived one.

**Not implemented, and why:** tool-use evaluation in the RAG sense (no
retrieval tools are used — see §3). The live-mode data fetch functions
(`_live_fetch_nav_history`, `_live_fetch_amfi_nav_snapshot`) are
functional but unexercised by any automated test, since this sandbox has
no network access to verify them against — flagged here rather than
implicitly claimed as tested.

**Latency, measured, not just discussed:** every response's
`data_quality_notes` includes a per-stage timing breakdown
(`insights/pipeline.py`), e.g. `analytics=54.8ms, prioritization=0.1ms,
reasoning[fallback_template]=0.3ms, validation=0.1ms, total=55.4ms` —
observed on every real request, not a one-line estimate in this
document.

---

## 5a. Known limitations (stated directly, not buried)

- **Conflicting-source handling** (`cross_check_latest_nav` in
  `data_sources.py`) is real, working code with unit-tested comparison
  logic (`tests/test_analytics_correctness.py`), but it only activates in
  live mode — sample mode has one underlying data source, so there is
  nothing to cross-check by construction, not because the feature is
  missing.
- **Misleading/malicious retrieved data**: not applicable to this build —
  there is no retrieval/RAG component, so there's nothing to sanitize.
  If fact-sheet ingestion were added (see §2), this would need real
  source-trust scoring, which is future work, not a gap in the current
  scope.
- **The actual Claude LLM call path** in `llm_reasoner.py` is functional
  and used in `sample_output/` generation when an API key is present, but
  is not covered by the automated test suite in this sandbox (no
  `ANTHROPIC_API_KEY` available here) — only the deterministic fallback
  path is exercised by `tests/run_eval.py`.
- No true multi-step agentic loop (an LLM iteratively choosing which
  tools to call). The one "agentic-flavored" decision in the system —
  skipping overlap analysis when fewer than 2 equity funds are held — is
  a fixed conditional in `engine.py`, not an LLM making a tool-choice
  decision. This was a deliberate choice (see §3 on reproducibility), not
  an oversight, but it's worth being precise about rather than
  overclaiming "agentic workflow."

---

## 6. Sample Output

Full JSON for all 5 demo portfolios is in `sample_output/`. Highlighting
one: **`concentrated`** (₹4L in one large-cap fund + two flexi-cap funds,
aggressive investor):

```json
{
  "headline": "Portfolio concentration is highly concentrated in a small number of holdings",
  "insights": [
    {
      "category": "concentration", "severity": "action",
      "title": "Portfolio concentration is highly concentrated in a small number of holdings",
      "explanation": "Your top holding is 80.0% of the portfolio and your top 3 holdings together make up 100.0% across 3 funds (HHI: 6608.0).",
      "evidence": [ ... HHI, top1 weight, top3 weight, each computed ... ],
      "confidence": 0.75
    },
    {
      "category": "overlap", "severity": "watch",
      "title": "Zenith Flexi Cap Fund and Redcliff Flexi Cap Fund overlap significantly",
      "explanation": "These two funds share 28.55% weighted exposure to the same holdings (Bharti Airtel, HDFC Bank, Infosys, Larsen & Toubro, TCS)...",
      "evidence": [ ... weighted overlap %, shared holdings list ... ],
      "confidence": 0.75
    }
    // + a category-relative performance insight
  ]
}
```

**Why these are useful:** the concentration insight tells the investor
something a plain summary wouldn't surface on its own — that "3 funds"
is misleading diversification, because HHI (6608, well above the ~2500
"highly concentrated" threshold used in `analytics/concentration.py`)
quantifies that it behaves like one bet. The overlap insight goes
further and names *which* funds are redundant with each other and *why*
(shared top holdings), which is directly actionable: the investor now
knows holding both flexi-cap funds isn't buying them extra
diversification, specifically because of Bharti Airtel/HDFC
Bank/Infosys/L&T/TCS overlap — not a vague "your portfolio is risky."

See `sample_output/missing_data.json` for the missing-data handling
example referenced in §4 — it shows the system explaining exactly what
was excluded and why, rather than either crashing or quietly proceeding
as if the missing holding didn't exist.

---

## 7. Assumptions (consolidated)

- NAV/holdings/category data in this submission is generated sample data
  in the exact shape live sources would provide (§2) — not real fund
  performance.
- Risk-free rate for Sharpe ratio: 6.5% annualized (illustrative, India
  short-term rate ballpark) — `analytics/risk.py`.
- Suitability risk-appetite bands and the age-based equity heuristic
  (`110 - age`) are illustrative rules of thumb, not regulatory guidance
  — explicitly labeled as such in both code and output text.
- Overlap is computed only on each fund's top-10 disclosed holdings
  (standard fact-sheet disclosure level), not full portfolio holdings.
- Minimum 60 trading days of NAV history required before volatility/
  Sharpe/drawdown are computed at all.
