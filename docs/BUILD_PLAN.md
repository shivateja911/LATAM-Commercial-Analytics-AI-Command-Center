# CABI: LATAM Commercial Command Center. Build plan

**Status:** built · see [README](../README.md) to run · mock UI at [mockups/cabi_mock_ui.html](../mockups/cabi_mock_ui.html) · "As built" notes in section 13

---

## 1. What we are building

A locally-run demo app for an audience that knows commercial excellence, revenue growth management (RGM) and SAP supply chain well. It has two halves.

1. **Commercial command center.** AI reads LATAM consumer trends, point-of-sale (POS) sell-out and local market dynamics. It then recommends prices and promotions in near real time, with the numbers, the drivers and the guardrails visible.
2. **SAP AI overlay.** Generative AI and predictive models read SAP S/4HANA data. They forecast demand, manage stock at each DC, and re-optimize distribution routes around LATAM infrastructure problems: landslides, river levels, cargo-theft corridors, heat and altitude.

**Hard constraints:** runs 100% on one laptop. No Docker, no cloud services. Uses an LLM from Hugging Face running on-device, with a local response-cache fallback, so the demo never fails on stage.

### Reference company (fictional)

**Northstar Confections** is modeled on a large US chocolate manufacturer that has operated in LATAM for decades with local plants:

| | |
|---|---|
| HQ | United States · LATAM operations since 1968 |
| Plants | MX01 Monterrey (chocolate, wafer) · MX02 Guadalajara (confectionery) · BR01 Jundiaí, SP (tablets, Páscoa eggs) |
| DCs / hubs | 18: CDMX, GDL, MTY, Mérida, Tijuana, Guatemala City, Colón FTZ, Bogotá, Medellín, Barranquilla, Lima (Lurín), Arequipa, Santiago, Buenos Aires, Cajamar, Recife, Manaus, Porto Alegre |
| Markets | Mexico, Brazil, Colombia, Peru, Chile, Argentina, Central America |
| Brands (fictional) | Dulcera (milk tablets), Dulcera Zero (no added sugar), Rayo (kids single-serve), Crunchita (wafer), Cacao Alto (premium dark), Almendra Real (nut bar), Fiesta Bites (seasonal / share) |
| Competitors (fictional) | Helvetia (global major), Andina Dulces (regional), private label |

The name, logo, colors and brands come from one config file. They can be swapped for a specific customer's branding in a private session. Real retailer and competitor names stay out of the defaults.

---

## 2. Scope: screens and features

The mock UI shows all eight screens. In the built app every number on them comes from models running on the synthetic data, not from hard-coded values.

| # | Screen | Key features | AI / ML behind it |
|---|---|---|---|
| 1 | **Command Center** | KPI tiles, AI morning briefing (EN/ES/PT), LATAM network map, market table, live POS pulse, recommendation queue with approve/simulate/dismiss | Anomaly detection on POS, ranking by value at stake, LLM narrative |
| 2 | **Pricing & Promotions** | Competitor-move alert, three response options compared, driver attribution, guardrails, what-if simulator, price-pack architecture, promo calendar with ROI, cocoa cost pass-through | Hierarchical price elasticity (own + cross), promo uplift with carry-over and pantry-loading dip, guardrailed optimizer |
| 3 | **Market Pulse** | Consumer trend signals, share by market, POS heatmap by region, local dynamics (macro, regulation, weather, calendar), channel-mix shift, competitor feed | Trend momentum scoring, signal → implication via LLM |
| 4 | **Demand Forecast** (SAP) | AI forecast against the SAP IBP statistical baseline, P10–P90 bands, event annotations, forecast bridge, accuracy by market, "why it changed", PIR write-back preview | Gradient-boosted global model with quantile loss, demand sensing from POS, backtest WAPE/bias |
| 5 | **Inventory** (SAP) | Days-of-supply matrix by DC × SKU, AI stock transfer (STO) and markdown actions, projected stock (as-is against the AI plan), shelf-life exposure | Monte-Carlo stock-out probability, safety-stock optimization, transfer optimization |
| 6 | **Route Optimizer** (SAP) | Disruption scenarios, zoomed network map, plan comparison, route cards, risk layers, lane risk scoring | OR-Tools vehicle routing with time windows (VRP-TW) on risk-weighted cost |
| 7 | **SAP Data Hub** | Connection card, data lineage (SAP object → model), **AI overlay on MD04** (Stock/Requirements List), governed write-back queue | Annotation engine over MRP elements |
| 8 | **Demo Control & AI** | LLM mode (Auto / Local / Cache), model picker, runtime status, scenario injector, stream speed, presenter script | n/a |
| ★ | **Copilot** (side panel, every screen) | Ask in EN/ES/PT, agent trace, source chips, actions drafted for approval | Intent router → analytics tools → grounded LLM narrative |

### Demo storyline (≈18 min, built in as presenter script)

1. **Command Center.** The briefing surfaces five signals for 27 Oct 2026, week 44.
2. **Pricing.** Helvetia cuts its 90g tablet by 12% in CDMX. The AI rejects both "hold" and "full match" and recommends a −5% TPR. The presenter plays with the what-if sliders.
3. **Market Pulse.** Why LATAM is different: coin price points, traditional trade, octagon warning labels, the Colombian health tax, heat.
4. **Forecast.** The AI beats the SAP IBP baseline by about 13 pp. The bridge shows that the Buen Fin promo is missing from the PIRs. The PIR update goes to write-back.
5. **Inventory + MD04 overlay.** Día de Muertos stock-out on 2 Nov. The fix is an STO from GDL plus a pulled-in planned order.
6. **Routes.** The presenter injects the huaico live and the network re-routes in about 3 s.
7. **Copilot.** Questions in Spanish and Portuguese, then a switch to cache mode to show offline resilience.

---

## 3. Architecture

```
Browser (localhost:8000)
  Single-page app · ECharts · offline LATAM map · Server-Sent Events
        │  REST + SSE
FastAPI (Python, one process)
  ├─ api/            routes per screen, /stream (SSE), /copilot, /demo
  ├─ analytics/      DuckDB SQL over Parquet: KPIs, share, price gaps
  ├─ models/         forecast · elasticity · promo uplift · stock-out risk
  ├─ optimize/       price/promo grid + guardrails · transfers · VRP-TW
  ├─ llm/            gateway: HF model (MLX / llama.cpp) → cache → template
  ├─ sap/            adapter interface: MockSAP (Parquet) | OData (stub)
  ├─ scenarios/      event engine: inject, recompute affected outputs
  └─ realtime/       POS tick simulator
        │
data/  Parquet (synthetic, seeded) · DuckDB file · llm_cache/*.json · audit.log
```

**One command to run:** `./run.sh` creates a virtualenv, installs dependencies, generates data (first run only, under 60 s), warms the models and opens `http://localhost:8000`. It runs without Docker, Node, or a database server.

### Tech choices

| Layer | Choice | Why |
|---|---|---|
| Backend | Python + FastAPI + Uvicorn | One runtime; strong ML ecosystem |
| Analytics store | DuckDB over Parquet | In-process SQL, fast on millions of POS rows, zero setup |
| ML | scikit-learn (HistGradientBoosting with quantile loss), NumPy | Ships wheels with OpenMP bundled, unlike LightGBM, which needs `libomp` on Mac |
| Routing | Google OR-Tools (VRP-TW) | Industry-standard solver; a nearest-neighbor + 2-opt heuristic covers the case where it fails to install |
| LLM runtime | **MLX** (`mlx-lm`) on Apple Silicon; **llama.cpp** (`llama-cpp-python`, GGUF) elsewhere | Fastest on-device path on Mac; portable fallback for Windows and Intel |
| Frontend | **No-build** single-page app: Preact + htm + ECharts, vendored locally | Needs no Node.js (not installed on this machine). Works fully offline, looks custom rather than "dashboard-tool" |
| Map | Natural Earth country shapes (public domain) bundled as GeoJSON | Offline; no map-tile server |
| Live updates | Server-Sent Events | Simpler than WebSockets, enough for one-way streams |

---

## 4. LLM design: Hugging Face model with cache fallback

**Default model:** `Qwen3-4B-Instruct-2507`, 4-bit, about 2.3 GB, Apache-2.0, strong in Spanish and Portuguese. Options in the picker: Qwen3-8B (quality), Llama-3.2-3B-Instruct, Phi-4-mini-instruct. Exact Hugging Face repo IDs are confirmed in phase 0. If a better small multilingual model is current at build time, it gets proposed then.

It downloads once with `huggingface_hub` into the standard HF cache. After that, everything runs offline.

**The core rule: the LLM never computes numbers.** Models and optimizers compute facts, and the LLM only turns facts into narrative.

```
question / screen event
   → intent router (TF-IDF over EN/ES/PT example phrases; optional JSON tool-choice from the LLM)
   → analytics tool (e.g. share_loss_diagnosis, stockout_scan, route_risk)
   → facts JSON (numbers, sources)
   → LLM gateway
        Auto:  local model (8 s budget, streamed) ─fail/timeout/ungrounded→ cache ─miss→ template narrator
        Local: local model only (shows real latency)
        Cache: cache → template (instant, no model needed)
   → grounding guard: every number in the text must exist in facts (±rounding), else retry once, then fall back
   → UI: text + model badge + latency + source chips + agent trace
```

- **Response cache.** `data/llm_cache/` holds JSON keyed by intent, parameters and language. It is pre-built by `scripts/build_llm_cache.py`, which runs the local model over every demo-script prompt and keeps only grounded outputs. A curated set ships in the repo, so cache mode works even on a machine that never downloaded the model. Free-text questions match the nearest cached entry by cosine similarity, with a threshold.
- **Template narrator.** Deterministic EN/ES/PT text built from the same facts. This is the last-resort path; it can't fail.
- **Language.** The narrative follows the question's language, with a UI override (Auto/EN/ES/PT).

---

## 5. Data: synthetic, SAP-shaped, seeded

`scripts/generate_data.py --seed 42` is reproducible. It covers Nov 2023 to Oct 2026, with demo "today" = **27 Oct 2026**.

| Dataset | Shaped like | Grain · approximate size |
|---|---|---|
| Sales orders / items | VBAK / VBAP (VBELN, POSNR, MATNR, WERKS, KUNNR, KWMENG, ERDAT…) | daily · SKU × ship-to · ~4M rows |
| Deliveries | LIKP / LIPS | daily · ~3.9M |
| Billing + pricing conditions | VBRP · PRCD_ELEMENTS (PR00, K007…) | ~4M |
| Stock | MATDOC / I_MaterialStock (LABST by WERKS/LGORT) | daily snapshot · SKU × DC · 90 days |
| Material / MRP | MARA · MARC (safety stock, lot size, MRP type) · MVKE | 40 SKUs × 21 plants/DCs |
| PIRs · planned orders | PBIM / PBED · PLAF | weekly / per order |
| Shipments | VTTK / VTTP + lanes | per load |
| POS sell-out | retailer scan + traditional-trade panel | daily · store × SKU · last 13 weeks (~8M), weekly before |
| Prices | own + competitor shelf prices | SKU × banner × week |
| Signals | trends index, weather (38 stations), road alerts, river levels, FX/CPI, calendar events | daily / monthly |

**Planted stories.** The generator embeds the events the demo tells: Día de Muertos and Buen Fin uplift, the Helvetia price cut, heat in the north of Mexico, Rio Negro low water, the huaico on the Carretera Central, Páscoa pre-orders and Argentina CPI. The models then *discover* them. Each one has a pytest that checks the story still holds.

### SAP integration story

- `sap/adapter.py` defines one interface (`sales_orders()`, `stock()`, `pirs()`, `post_sto()`…). **MockSAPAdapter** serves the Parquet extracts using real SAP field names.
- **ODataAdapter** is a documented stub (`API_SALES_ORDER_SRV`, `API_MATERIAL_STOCK_SRV`, `API_PURCHASEORDER_PROCESS_SRV`…). It shows the audience the path to a live system. It is **not** connected in the demo.
- **Write-back** (STO, PIR change, price condition, planned-order pull-in) only goes to an approval queue. On approval it updates the mock replica and appends a payload line to `audit.log`. No real SAP system is touched.

---

## 6. Models and methods

| Capability | Method | Shown to audience as |
|---|---|---|
| Demand forecast | Global HistGradientBoosting (P10/P50/P90 quantiles). Features: lags, seasonality, ISO week, events by market, price index, promo flags, POS demand sensing, temperature | AI against the SAP IBP baseline, 13-week backtest 1−WAPE and bias, forecast bridge |
| SAP baseline (for contrast) | Holt-Winters / seasonal-naive with damping. Mimics a statistical baseline that has no promo or POS signal | Gray dashed line |
| Price elasticity | Log-log regression with empirical-Bayes shrinkage by market → channel → SKU; cross-elasticity against the main competitor | Elasticity values, what-if curve |
| Promo uplift / ROI | Baseline vs. actual decomposition; carry-over share loss; post-promo pantry dip | Options A/B/C, promo ROI, calendar flags |
| Price / promo optimizer | Grid over depth × duration × display, with guardrails: margin floor, price-index band, approved price points, trade budget, customer lead time, regulatory notes | Recommended option + guardrail checklist |
| Stock-out risk | Monte-Carlo over forecast quantiles × open orders × planned receipts | Risk %, projected-stock chart |
| Rebalancing | Greedy / LP transfer from excess to deficit DCs, minimizing lost sales + freight + shelf-life risk | STO and markdown cards |
| Routing | OR-Tools VRP-TW. Cost = freight + λ·risk (landslide, security, heat/melt, altitude, border/port, urban truck windows); daylight-only and reefer constraints | Re-optimized plan, lane risk table |

---

## 7. Real-time and scenario engine

- A POS tick simulator streams sell-out events over SSE at an adjustable rate. Anomaly rules raise alerts on the ticker and the briefing.
- The scenario injector takes seven presets: competitor cut, heat wave, huaico, Rio Negro, cocoa +8%, Argentina CPI, trucker strike. Each one changes in-memory state and recomputes only the affected models (target: under 3 s). The new recommendation is pushed to the UI.
- **Reset demo** restores the 27 Oct 07:40 state, so every run of the pitch is identical.

---

## 8. Project layout

```
Demo_AI_CABI/
  run.sh                     # one-command setup + launch (macOS / Linux)
  run.ps1                    # Windows equivalent
  config.yaml                # company name, branding, LLM mode/model, SAP mode, demo date
  requirements.txt
  backend/
    app.py                   # FastAPI app, serves frontend/ statically
    api/  analytics/  models/  optimize/  llm/  sap/  scenarios/  realtime/
  frontend/
    index.html  app.js  screens/*.js  components/*.js  styles.css
    vendor/                  # preact, htm, echarts, latam.geojson (offline)
  scripts/
    generate_data.py  build_llm_cache.py  download_model.py  check_env.py
  data/                      # generated Parquet, duckdb, llm_cache/, audit.log
  tests/                     # pytest: data stories, models, optimizer, LLM fallback
  docs/  BUILD_PLAN.md  DEMO_SCRIPT.md  ARCHITECTURE.md
  mockups/  cabi_mock_ui.html
```

---

## 9. Build phases and how each is verified

| Phase | Deliverable | Verified by |
|---|---|---|
| 0 · Environment | `check_env.py`, venv, requirements, model download script | All wheels install on this Mac; `./run.sh` serves a hello page; model loads and generates |
| 1 · Data | Generator, SAP-shaped Parquet, DuckDB views, planted stories | pytest on row counts, keys, and that each story is present |
| 2 · Models | Forecast, elasticity, uplift, optimizer, stock-out risk, rebalancing, VRP | pytest: backtest accuracy above the baseline; optimizer picks a shallow TPR; VRP avoids the closed lane |
| 3 · LLM gateway | MLX/llama.cpp loader, prompts, grounding guard, cache builder, template narrator | Tests with the model absent (cache path), the model present (live path), and a forced timeout (fallback) |
| 4 · API + realtime | REST endpoints, SSE stream, scenario engine, write-back queue + audit | API tests; inject → recompute in under 3 s |
| 5 · Frontend | 8 screens + Copilot matching the approved mock, dark/light theme | Click through every screen in the browser; no console errors; 1440 px and projector widths |
| 6 · Demo hardening | Presenter script, reset, offline test, cold-start timing, README, zip package | Full rehearsal with Wi-Fi **off**, in Auto and Cache modes |

---

## 10. Machine requirements (checked on this Mac)

- **This laptop:** Apple Silicon, 24 GB RAM, Python 3.14, no Node.js. Good fit: the 4B model uses about 3 GB, and 8B is also feasible.
- **Minimum for customers' machines:** any Mac/Windows/Linux with Python 3.11+ and 8 GB RAM in cache mode. Live LLM mode wants 16 GB+, with Apple Silicon preferred.
- **Internet:** needed once for `pip install` and the model download, about 2.3 GB. After that the demo is fully offline.

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Python 3.14 is very new; some wheels (mlx, ortools, llama-cpp) may be missing | Phase 0 checks first. If needed, use a Python 3.12 virtualenv (installer from python.org, or `uv`), with your OK |
| Small LLMs can invent numbers | Facts-only prompting, grounding guard, cache and template fallbacks |
| Model slow on stage | Auto mode has an 8 s budget with streamed tokens. Cache mode is instant and toggled live |
| Demo drifts between rehearsals | Seeded data, demo clock and a one-click reset |
| Brand sensitivity | Fictional company by default; branding only via config |

---

## 12. Decisions needed from you

1. **Company identity:** keep fictional **Northstar Confections** (recommended for anything shared), or plan a config-only rebrand for a private session?
2. **Frontend approach:** no-build Preact + ECharts with a Python-only runtime (recommended), or React + Vite (requires installing Node.js)?
3. **Default model:** Qwen3-4B (fast, recommended) or Qwen3-8B (better prose, ~2× slower)?
4. **UI language:** English UI with EN/ES/PT AI narratives (planned), or full ES/PT UI translation as well?
5. **Python:** OK to install Python 3.12 alongside 3.14 if phase 0 finds missing wheels?

---

## 13. As built: changes from this plan

| Topic | Plan | As built | Why |
|---|---|---|---|
| LLM source visibility | Model badge on AI panels | Business screens and Copilot show only "AI"; model, runtime and per-request source (live / cache / template) appear **only on Demo Control** | Customer request |
| Frontend | Preact + htm + ECharts, vendored | Vanilla JS with the mock's own SVG chart and offline-map helpers | No downloads or vendoring needed; matches the approved mock pixel for pixel; fully offline |
| Forecast intervals | Separate P10/P90 quantile models | Intervals calibrated per series on 13-week backtest errors | Pooled quantile models over-stated spread (±49%); calibrated bands are about ±27%; training is 2.5× faster |
| Point forecast | Quantile P50 | Poisson-loss mean with an explicit series-growth detrend | Removed a −4.7% under-forecast bias (now −0.8%) |
| LLM runtime off Mac | llama.cpp fallback | Cache mode (pre-built grounded answers + templates) | MLX covers the demo laptop; a llama.cpp backend is a possible follow-up |
| SAP live connector | OData adapter stub | Mock replica only; connection card says the live connector is a next step | Avoids implying a live integration that doesn't exist |

Measured on this Mac (Apple Silicon, 24 GB):
- Engines boot in about 5 s; the model loads in about 1 s.
- The model writes about 57 tokens/s, so a narrative takes 2–5 s.
- Scenario injection recomputes everything in under 1 s.
- Backtest accuracy is 81.1% for the AI vs 76.0% for the SAP-style baseline.
- The pricing engine re-estimates elasticity −3.1 (true −2.9) and cross +1.1 (true +1.1).
- The router solves 162 stops and 18 trucks in under 1 s.
