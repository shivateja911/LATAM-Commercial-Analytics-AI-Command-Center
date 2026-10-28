"""CABI API server. Serves the single-page UI and all /api endpoints on one local port.

Run:  .venv/bin/python -m backend.app      (or ./run.sh)
"""
from __future__ import annotations

import asyncio
import json
import random
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
import pandas as pd
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import catalog as C
from .config import FRONTEND, settings, today
from .copilot import SUGGESTIONS, answer
from .hub import hub
from .llm import GATEWAY
from .narratives import BUILDERS, narrative
from .state import SCENARIOS, STATE
from .store import store

BOOT = dict(ready=False, error="", seconds=None)
STREAM = dict(rate=20)


def _boot():
    t0 = time.time()
    try:
        h = hub()
        h.signals()
        BOOT.update(ready=True, seconds=round(time.time() - t0, 1))
        if settings()["llm"].get("preload", True) and GATEWAY.mode != "cache":
            GATEWAY.load_async()
            time.sleep(0.5)
        prewarm_async()
    except Exception as e:  # pragma: no cover
        BOOT.update(error=f"{type(e).__name__}: {e}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_boot, daemon=True).start()
    yield


app = FastAPI(title="CABI · LATAM Commercial Command Center", lifespan=lifespan)


def ready():
    for _ in range(600):
        if BOOT["ready"]:
            return hub()
        if BOOT["error"]:
            raise HTTPException(500, BOOT["error"])
        time.sleep(0.05)
    raise HTTPException(503, "engines still loading")


# ------------------------------------------------------------------ narrative pre-warm (background)
_prewarm_lock = threading.Lock()


def prewarm_async(include_copilot: bool = True):
    def run():
        if not _prewarm_lock.acquire(blocking=False):
            return
        try:
            if GATEWAY.mode == "cache":
                return
            for _ in range(200):
                if GATEWAY.status in ("ready", "missing", "error"):
                    break
                time.sleep(0.25)
            if GATEWAY.status != "ready":
                return
            jobs = [("n", t) for t in ("briefing", "pricing", "forecast", "inventory", "routes")]
            if include_copilot:
                jobs += [("q", q) for q in SUGGESTIONS]
            GATEWAY.prewarm_state.update(running=True, done=0, total=len(jobs))
            for kind, x in jobs:
                try:
                    narrative(x) if kind == "n" else answer(x)
                except Exception:
                    pass
                GATEWAY.prewarm_state["done"] += 1
        finally:
            GATEWAY.prewarm_state["running"] = False
            _prewarm_lock.release()
    threading.Thread(target=run, daemon=True).start()


# ------------------------------------------------------------------ meta / overview
def nav_counts(h) -> dict:
    sig = h.signals()
    goto = {}
    for s in sig:
        goto[s["goto"]] = goto.get(s["goto"], 0) + 1
    inv = h.inventory()
    return dict(overview=len(sig[:5]), pricing=1 + (1 if "cocoa_up" in STATE.active else 0), inventory=len([a for a in inv["actions"]][:6]),
                routes=sum(1 for s in ("huaico_pe", "heat_mx", "strike_br") if s in STATE.active), sap=len(STATE.queue))


@app.get("/api/meta")
def meta():
    cfg = settings()
    out = dict(company=cfg["company"], today=cfg["demo"]["today"], clock=cfg["demo"]["clock"], ready=BOOT["ready"], boot_error=BOOT["error"],
               version=STATE.version, active=list(STATE.active), scenarios=SCENARIOS)
    if BOOT["ready"]:
        out["counts"] = nav_counts(hub())
    return out


@app.get("/api/overview")
def overview():
    h = ready()
    core = h.overview_core()
    sig = h.signals()
    alert_dcs = {"MX1D", "PE1D", "AR1D"} | ({"BR3D"} if "rionegro_br" in STATE.active else set()) | ({"MX3D", "MX4D"} if "heat_mx" in STATE.active else set())
    alert_plants = {"MX01"} if "heat_mx" in STATE.active else set()
    if "huaico_pe" not in STATE.active:
        alert_dcs.discard("PE1D")
    mkt_alerts = {}
    for s in sig:
        mkt_alerts[s["market"]] = mkt_alerts.get(s["market"], 0) + 1
    markets = []
    for m in core["markets"]:
        markets.append(dict(m, alerts=mkt_alerts.get(m["code"], 0)))
    nodes = [dict(t="plant", id=k, n=v["name"], lat=v["lat"], lon=v["lon"], alert=k in alert_plants) for k, v in C.PLANTS.items()]
    nodes += [dict(t="dc", id=k, n=v["name"], lat=v["lat"], lon=v["lon"], alert=k in alert_dcs) for k, v in C.DCS.items()]
    recs = h.recommendations()
    return dict(kpis=core["kpis"], markets=markets, channel_mix=core["channel_mix"], nodes=nodes,
                signals=[dict(id=s["id"], sev=s["sev"], title=s["title"], text=s["text"], action=s["action"], goto=s["goto"], value=s["value"]) for s in sig[:5]],
                recs=recs, recs_value=sum(s["value"] for s in sig), recs_pending=sum(1 for r in recs if r["status"] == "pending"))


@app.get("/api/narrative/{task}")
def get_narrative(task: str, lang: str = "en", dc: str | None = None, sku: str | None = None, fresh: int = 0):
    ready()
    if task not in BUILDERS:
        raise HTTPException(404)
    params = {k: v for k, v in dict(dc=dc, sku=sku).items() if v}
    return narrative(task, lang, fresh=bool(fresh), **params)


# ------------------------------------------------------------------ pricing
def _sim_view(r: dict, h) -> dict:
    return dict(price=r["price"], index=r["index"], vol=r["vol"], dgp=r["dgp"], depth=r["depth"], weeks=r["weeks"], display=r["display"],
                roi=r.get("roi"), share_pp=r.get("share_pp"), guardrails=r.get("guardrails") or h.pricing.guardrails(r), spend=r["spend"])


@app.get("/api/pricing")
def pricing():
    h = ready()
    p = h.pricing_payload()
    o = p["options"]
    return dict(p, options={k: _sim_view(v, h) for k, v in o.items()}, curve=h.pricing.curve(o["ai"]["weeks"], o["ai"]["display"], p["alert"]["cut"]))


@app.post("/api/pricing/simulate")
def simulate(body: dict = Body(...)):
    h = ready()
    d, w, cc, disp = float(body.get("depth", 5)) / 100, int(body.get("weeks", 3)), float(body.get("comp", 12)) / 100, bool(body.get("display", False))
    r = h.pricing.sim(d, w, disp, cc)
    curve = h.pricing.curve(w, disp, cc)
    feasible = [i for i in range(0, 21) if all(g["ok"] != "x" for g in h.pricing.guardrails(h.pricing.sim(i / 100, w, disp, cc)))]
    best = max(feasible, key=lambda i: curve[i]) if feasible else 0
    return dict(result=_sim_view(r, h), curve=curve, best=best)


# ------------------------------------------------------------------ market / forecast
@app.get("/api/market")
def market():
    return ready().market_payload()


@app.get("/api/forecast")
def forecast(dc: str = "MX1D", sku: str = "100045"):
    h = ready()
    fc = h.fc
    if (dc, sku) not in fc.idx:
        raise HTTPException(404, "series not found")
    h.inventory()
    acc = fc.accuracy()
    i = fc.idx[(dc, sku)]
    all_ = acc["ALL"]
    nxt8 = float(fc.fc[0.5][:, :8].sum())
    sap8 = float(sum(fc.sap_future(j)[:8].sum() for j in range(len(fc.keys))))
    band = float(((fc.fc[0.9][:, :8] - fc.fc[0.1][:, :8]).sum() / 2) / nxt8)
    kpis = [dict(label="Forecast accuracy · AI", value=all_["ai"], fmt="pct1", delta=all_["ai"] - all_["sap"], delta_fmt="pp", sub=f"vs SAP IBP {all_['sap'] * 100:.1f}%"),
            dict(label="Forecast bias · AI", value=all_["bias_ai"], fmt="pctS1", sub=f"SAP {all_['bias_sap'] * 100:+.1f}%"),
            dict(label="Next 8 weeks · LATAM", value=nxt8, fmt="kcs", delta=nxt8 / sap8 - 1, delta_fmt="pct", sub=f"vs SAP · P10–P90 ±{band * 100:.0f}%"),
            dict(label="Series forecast", value=len(fc.keys), fmt="int", sub="SKU × DC · 26-week horizon"),
            dict(label="Safety stock released", value=fc.safety_stock_release_usd(), fmt="usdM", sub="same 97% service level")]
    pir = store().table("PBED")
    pir = pir[(pir.WERKS == dc) & (pir.MATNR == sku)].sort_values("PDATU").iloc[1:5]
    wb = [dict(week=f"W{int(r.ISO_WEEK)}", pir=float(r.PLNMG), ai=float(round(fc.fc[0.5][i][k]))) for k, r in enumerate(pir.itertuples())]
    series_opts = dict(skus=[dict(id=k, name=v["name"]) for k, v in C.SKUS.items() if any((d, k) in fc.idx for d in C.DCS)],
                       dcs=[dict(id=k, name=v["name"]) for k, v in C.DCS.items()])
    return dict(kpis=kpis, series=fc.series(dc, sku), bridge=fc.bridge(dc, sku), dc=dc, sku=sku, sku_name=C.SKUS[sku]["name"], dc_name=C.DCS[dc]["name"],
                accuracy=[dict(market=m, name=C.MARKETS[m]["name"], **{k: float(v) for k, v in acc[m].items()}) for m in C.MARKETS],
                writeback=wb, options=series_opts, fit_seconds=fc.fit_seconds)


@app.post("/api/forecast/writeback")
def forecast_writeback(body: dict = Body(...)):
    h = ready()
    dc, sku = body.get("dc", "MX1D"), body.get("sku", "100045")
    i = h.fc.idx[(dc, sku)]
    delta = float(h.fc.fc[0.5][i][:4].sum())
    item = STATE.enqueue(dict(key=f"pir-{dc}-{sku}", title=f"PIR change · {C.SKUS[sku]['name']} · {C.DCS[dc]['code']} · 4 weeks", tcode="MD61",
                              api="BAPI_REQUIREMENTS_CHANGE", approver="Demand planner " + C.DCS[dc]["country"], doc_prefix="PB", market=C.DCS[dc]["country"], type="Forecast",
                              preview={"Material": sku, "Plant": dc, "Version": "00", "Weeks": 4, "AIForecastCases": round(delta)}))
    return item


# ------------------------------------------------------------------ inventory / routes / sap
@app.get("/api/inventory")
def inventory():
    h = ready()
    res = h.inventory()
    return h.inv.payload(res, h.scen())


@app.get("/api/routes")
def routes():
    return ready().routes_payload()


@app.get("/api/sap")
def sap():
    h = ready()
    cfg = settings()["sap"]
    counts = store().row_counts()
    lineage = [
        ("Sales orders / deliveries", "VBAK / VBAP · LIKP / LIPS", "API_SALES_ORDER_SRV · API_OUTBOUND_DELIVERY_SRV", "SELLIN_WEEKLY", "06:00", "Forecast · Pricing · KPIs"),
        ("Open sales orders", "VBAP (open items)", "API_SALES_ORDER_SRV", "VBAP_OPEN", "15 min", "Inventory · MD04"),
        ("Stock", "MATDOC · I_MaterialStock", "API_MATERIAL_STOCK_SRV", "MARD", "15 min", "Inventory"),
        ("Batches / shelf life", "MCHB · MCH1", "API_BATCH_SRV", "MCHB", "hourly", "Inventory · Markdown"),
        ("Material / MRP", "MARA · MARC", "API_PRODUCT_SRV", "MARC", "daily", "All modules"),
        ("PIRs", "PBIM / PBED", "BAPI_REQUIREMENTS_*", "PBED", "06:00", "Forecast ⇄ write-back"),
        ("Planned orders / receipts", "PLAF", "API_PLANNED_ORDERS", "PLAF", "hourly", "Inventory · MD04"),
        ("Shipments", "VTTK / VTTP", "Shipment IDoc · CDS", "VTTK", "hourly", "Routes"),
        ("Plants & DCs", "T001W", "table read", "T001W", "static", "Network"),
        ("Non-SAP signals", "POS · panel · weather · roads · FX", "File / API (mock)", "POS_WEEKLY", "live", "All modules"),
    ]
    res = h.inventory()
    return dict(connection=dict(system=f"{cfg['system']} · {cfg['release']}", client=cfg["client"], company_codes="MX10 BR10 CO10 PE10 CL10 AR10 GT10",
                                access="OData v2/v4 + CDS views, read-only user (target design)", mode=cfg["mode"], switch="Mock replica in demo · live OData connector is a next step",
                                last_sync=f"{settings()['demo']['today']} 06:00", delta="every 15 min (stock)", writeback="Simulated · data/audit.log"),
                lineage=[dict(domain=a, objects=b, api=c, records=counts.get(d, 0), fresh=e, feeds=f) for a, b, c, d, e, f in lineage],
                md04=h.inv.md04(res), queue=STATE.queue, done=STATE.done[-6:][::-1])


@app.post("/api/recs/{key}/approve")
def approve_rec(key: str):
    item = ready().approve_rec(key)
    if not item:
        raise HTTPException(404)
    return item


@app.post("/api/sap/queue/{item_id}/approve")
def approve_queue(item_id: str):
    item = STATE.approve(item_id)
    if not item:
        raise HTTPException(404)
    return item


# ------------------------------------------------------------------ copilot
@app.post("/api/copilot")
def copilot(body: dict = Body(...)):
    ready()
    q = (body.get("q") or "").strip()
    if not q:
        raise HTTPException(400, "empty question")
    return answer(q, body.get("lang"))


@app.get("/api/copilot/suggestions")
def suggestions():
    return SUGGESTIONS


# ------------------------------------------------------------------ demo control
SCRIPT = [("Command Center", "AI morning briefing: five signals, one decision each", "2 min", "overview"),
          ("Pricing & Promotions", "Competitor cut → three options → what-if → approve TPR", "4 min", "pricing"),
          ("Market Pulse", "Trends, regulation, weather: why LATAM is different", "2 min", "market"),
          ("Demand Forecast", "AI vs SAP IBP baseline, explain the gap, write PIRs back", "3 min", "forecast"),
          ("Inventory + SAP overlay", "MD04 with AI annotations → STO draft → approve in the queue", "2 min", "sap"),
          ("Route Optimizer", "Inject the huaico live and re-route in seconds", "3 min", "routes"),
          ("Copilot", "Ask in Spanish & Portuguese, then flip to Cache mode to show offline resilience", "2 min", "overview")]


@app.get("/api/demo")
def demo():
    return dict(llm=GATEWAY.info(), scenarios=[dict(id=k, **v, active=k in STATE.active) for k, v in SCENARIOS.items()],
                script=[dict(title=a, text=b, time=c, goto=d) for a, b, c, d in SCRIPT], stream=STREAM, boot=BOOT)


@app.post("/api/demo/inject/{name}")
def inject(name: str):
    if name not in SCENARIOS:
        raise HTTPException(404)
    STATE.inject(name)
    ready().signals()
    prewarm_async(include_copilot=False)
    return dict(active=STATE.active, version=STATE.version)


@app.post("/api/demo/clear/{name}")
def clear(name: str):
    STATE.clear(name)
    return dict(active=STATE.active, version=STATE.version)


@app.post("/api/demo/reset")
def reset():
    STATE.reset()
    return dict(active=STATE.active, version=STATE.version)


@app.post("/api/demo/llm")
def set_llm(body: dict = Body(...)):
    if body.get("mode") in ("auto", "live", "cache"):
        GATEWAY.mode = body["mode"]
        if GATEWAY.mode != "cache" and GATEWAY.status == "not_loaded":
            GATEWAY.load_async()
    if body.get("model") and body["model"] != GATEWAY.model_id:
        GATEWAY.load_async(body["model"], download=bool(body.get("download")))
    if body.get("load"):
        GATEWAY.load_async(download=bool(body.get("download")))
    if "rate" in body:
        STREAM["rate"] = int(body["rate"])
    return GATEWAY.info()


@app.post("/api/demo/llm/test")
def llm_test():
    ready()
    t0 = time.time()
    r = answer("How is Mexico doing this month?", force=True)
    return dict(text=r["text"], ms=int((time.time() - t0) * 1000), source=GATEWAY.log[0]["source"] if GATEWAY.log else "")


@app.post("/api/demo/prewarm")
def prewarm():
    prewarm_async()
    return GATEWAY.prewarm_state


# ------------------------------------------------------------------ live stream (SSE)
STORES = {"TT": ["Tienda de barrio", "Abarrotes", "Bodega", "Mercadinho", "Kiosco"], "MT": ["Hiper Nacional", "Super Andino", "MegaMart"],
          "CONV": ["Conveniencia 24h", "Express Market"], "DISC": ["Atacarejo", "Hard discount D-Max"], "ECOM": ["Marketplace", "Quick-commerce"]}
CITY = {"MX-NOR": "Monterrey", "MX-BAJ": "Guadalajara", "MX-CDMX": "CDMX", "MX-SUR": "Mérida", "BR-SP": "São Paulo", "BR-SUL": "Porto Alegre", "BR-NE": "Recife",
        "BR-NO": "Manaus", "CO-AND": "Bogotá", "CO-CAR": "Barranquilla", "PE-LIM": "Lima", "PE-CEN": "Huancayo", "PE-SUR": "Arequipa", "CL-RM": "Santiago",
        "AR-AMBA": "Buenos Aires", "CA-CAM": "Guatemala"}
_pos_sample = {}


def _pos_weights():
    if not _pos_sample:
        p = store().table("POS_WEEKLY")
        last = p[p.WEEK_START == p.WEEK_START.max()]
        _pos_sample["rows"] = last[["REGION", "CHANNEL", "MATNR", "SHELF_PRICE_LC", "COUNTRY"]].to_dict("records")
        w = last.UNITS.values.astype(float)
        _pos_sample["w"] = w / w.sum()
        _pos_sample["units_per_min"] = float(last.UNITS.sum()) / (7 * 16 * 60)
    return _pos_sample


@app.get("/api/stream")
async def stream():
    async def gen():
        pw = _pos_weights()
        rng = np.random.default_rng()
        version = -1
        t_clock = time.time()
        while True:
            rate = max(1, STREAM["rate"])
            idx = rng.choice(len(pw["rows"]), size=min(rate, 40), p=pw["w"])
            ev = []
            for i in idx:
                r = pw["rows"][i]
                q = int(rng.integers(1, 25))
                ev.append(dict(region=r["REGION"], city=CITY[r["REGION"]], store=random.choice(STORES[r["CHANNEL"]]), sku=C.SKUS[r["MATNR"]]["name"], qty=q,
                               value=round(q * r["SHELF_PRICE_LC"], 2), ccy=C.MARKETS[r["COUNTRY"]]["ccy"]))
            upm = pw["units_per_min"] * float(rng.normal(1, 0.05))
            yield f"event: tick\ndata: {json.dumps(dict(events=ev[:6], units_per_min=round(upm), tx_per_min=round(upm / 3.1)))}\n\n"
            if STATE.version != version:
                version = STATE.version
                yield f"event: state\ndata: {json.dumps(dict(version=version, active=STATE.active, events=STATE.events[-3:]))}\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="static")


def main():
    import uvicorn
    cfg = settings()["server"]
    print(f"\n  CABI is starting on http://{cfg['host']}:{cfg['port']}  (engines load in ~5 s)\n")
    uvicorn.run(app, host=cfg["host"], port=cfg["port"], log_level="warning")


if __name__ == "__main__":
    main()
