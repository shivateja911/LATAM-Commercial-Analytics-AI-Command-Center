# CABI · LATAM Commercial Command Center

An AI-powered commercial command center for a (fictional) US chocolate manufacturer with plants and DCs across Latin America.
It shows how AI turns **consumer trends, POS sell-out and local market dynamics** into real-time **pricing and promotion
recommendations**, and how an **AI overlay on SAP S/4HANA** forecasts demand, rebalances localized inventory and re-routes
distribution around LATAM infrastructure disruptions.

Everything runs **locally on one laptop**: no Docker, no cloud services. Narratives and Copilot answers come from a
**Hugging Face model running on-device**, with a **cache of grounded answers** as the fallback.

## Quick start

```bash
./run.sh
```

The first run creates `.venv`, installs packages, generates the synthetic data (< 1 s), downloads the model once from
Hugging Face (2.3 GB), and opens http://127.0.0.1:8000. Later runs start in about 10 seconds.

```bash
./run.sh --no-model
```

This skips the model download and runs in Cache mode.

Requirements: Python 3.11+ (tested on 3.14) and macOS on Apple Silicon for live generation (16 GB+ RAM recommended).
On other machines the app runs fully in Cache mode.

## What's in the demo

| Screen | What the audience sees | What actually runs |
|---|---|---|
| **Command Center** | AI briefing, KPIs, LATAM network map, market table, live POS pulse, approval queue | KPIs from SAP-shaped sell-in and POS; signals ranked by value at stake; LLM executive summary |
| **Pricing & Promotions** | Competitor-cut response options, why-C narrative, what-if simulator, PPA, promo calendar, cocoa pass-through | Elasticities re-estimated from POS (log-log + empirical-Bayes shrinkage); promo simulator with carry-over and pantry dip; guardrailed optimizer over the price-point ladder |
| **Market Pulse** | Trend signals, share by market, POS heatmap, local dynamics, channel mix, competitor feed | Computed from the POS panel; competitor price moves detected automatically |
| **Demand Forecast** | AI vs SAP IBP baseline with intervals, forecast bridge, accuracy by market, PIR write-back | Gradient-boosted global model (Poisson); 13-week backtest; counterfactual bridge; intervals calibrated on backtest errors |
| **Inventory** | Days-of-supply matrix, stock-out risk, STO / pull-in / markdown actions, projected stock | Monte-Carlo stock-out probability, rebalancing engine, shelf-life batches |
| **Route Optimizer** | Peru network, cost-only vs risk-aware plan, live landslide re-route, lane risk table | OR-Tools VRP with time windows, capacity, reefer rule, risk-weighted cost, deferrable stops |
| **SAP Data Hub** | Lineage of SAP objects, **AI overlay on MD04**, governed write-back queue | Mock S/4HANA replica (VBAK/VBAP, LIPS, MATDOC/MARD, MARC, PBED, PLAF, VTTK); simulated posting + `data/audit.log` |
| **Demo Control** | LLM gateway, scenario injector, presenter script | The only screen that shows which model is used and whether an answer came from the model, the cache or a template |
| **Copilot** | Ask in English, Spanish or Portuguese; agent trace; source chips; approve drafted actions | Intent router → analytics tool → grounded narrative |

A suggested 18-minute storyline is on the Demo Control screen.

## The LLM layer

- **Model:** `mlx-community/Qwen3-4B-Instruct-2507-4bit` (Apache-2.0, strong in ES/PT), run with MLX on Apple Silicon.
  Pick another model in Demo Control or in `config.toml`; it downloads once from Hugging Face.
- **Modes** (Demo Control):
  - **Auto:** the model generates; identical requests reuse the earlier answer. If the model is missing, slow or ungrounded, it falls back to the cache, then to a template.
  - **Live:** every narrative is generated on this laptop.
  - **Cache:** never calls the model. Instant and offline-safe.
- **The model never computes numbers.** Engines compute facts. The LLM only writes narrative, and a grounding guard rejects any figure that is not in the facts.
- **No source on screen.** Business screens never show which model or path produced a narrative; that information is only on Demo Control.
- **Pre-build the cache** for every demo state after changing data or the model:
  ```bash
  .venv/bin/python scripts/build_llm_cache.py
  ```

## Data

`backend/datagen.py` builds three years of seeded, synthetic data from a known demand model: price and promo
elasticities, events (Día de Muertos, Buen Fin, Páscoa…), weather, and competitor moves. It then writes SAP-shaped tables
and external signals to `data/cabi.duckdb`, with Parquet extracts in `data/sap_extracts/`. The engines then
*rediscover* the planted stories:

- the competitor price cut in CDMX;
- the Día de Muertos surge;
- the CDMX stock-out and the excess stock in Guadalajara;
- expiring seasonal stock;
- the Páscoa pre-orders.

Regenerate the data with `.venv/bin/python -m backend.datagen`. Company name, demo date, revenue scale and LLM settings
are in `config.toml`. The company, brands, competitors and retailers are all fictional.

## Project layout

```
backend/   app.py (FastAPI + SSE) · hub.py (signals, recommendations) · llm.py (HF gateway, cache, grounding)
           narratives.py · copilot.py · state.py (scenarios, write-back queue) · datagen.py · catalog.py
           engine/ forecast.py · pricing.py · inventory.py · routing.py · commercial.py · baseline.py
frontend/  index.html · styles.css · js/ui.js (SVG charts, offline map) · js/app.js (screens, Copilot, live stream)
scripts/   download_model.py · build_llm_cache.py
tests/     test_cabi.py  (.venv/bin/python -m pytest -q tests)
mockups/   cabi_mock_ui.html (approved mock)
docs/      BUILD_PLAN.md
```

## Limitations (by design for a demo)

- SAP is a **mock replica**: no live connector is included, and write-backs are simulated and audit-logged.
- Live generation needs Apple Silicon (MLX). Other machines run in Cache mode.
- Market and consumer signals are synthetic. Treat every number as illustrative.
