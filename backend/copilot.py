"""CABI Copilot: multilingual intent routing → analytics tool → grounded narrative.

The language model only writes the answer; every number comes from a tool. Answers never reveal how the model is served.
"""
from __future__ import annotations

import re
import time
import unicodedata

import numpy as np

from . import catalog as C
from .engine.inventory import HERO as INV_HERO
from .hub import hub, lc, num, pct, sto_payload, usd
from .llm import GATEWAY

MARKET_NAMES = {"MX": ["mexico", "mexic", "cdmx", "mx"], "BR": ["brazil", "brasil", "br"], "CO": ["colombia", "co"], "PE": ["peru", "pe"],
                "CL": ["chile", "cl"], "AR": ["argentina", "ar"], "CA": ["central america", "centroamerica", "guatemala", "panama"]}
INTENTS = [
    ("pascoa", 3, ["pascoa", "pascua", "easter", "ovo", "huevo"]),
    ("create_sto", 3, ["sto", "stock transport", "draft an", "crea un", "crear un", "criar", "traslado", "transferencia", "transferencia"]),
    ("share_loss", 2, ["participacion", "participacao", "share", "perdiendo", "perdendo", "losing", "competidor", "concorrente", "competitor", "helvetia", "price cut", "recorte"]),
    ("stockout_scan", 2, ["stock out", "stockout", "stock-out", "quiebre", "agotad", "ruptura", "falta", "desabasto", "run out", "dcs will", "inventario", "inventory"]),
    ("cost_shock", 2, ["cocoa", "cacao", "cacau", "commodity", "cost rise", "costs rise", "costo", "custo"]),
    ("route_risk", 2, ["route", "ruta", "rota", "huaico", "logistic", "transport", "entrega", "delivery", "carretera", "road", "camion"]),
    ("forecast_explain", 2, ["forecast", "pronostico", "previsao", "ibp", "baseline", "accuracy", "precision", "acuracia", "demand"]),
    ("trends", 2, ["trend", "tendencia", "consumer", "consumidor", "sin azucar", "zero sugar", "premium"]),
    ("ar_price", 2, ["inflation", "inflacion", "inflacao", "cpi", "indexation", "indexacion"]),
    ("kpi_summary", 1, ["how is", "how are", "como va", "como esta", "performance", "desempeno", "desempenho", "summary", "resumen", "resumo", "revenue",
                        "ventas", "vendas", "kpi", "results", "resultados", "briefing", "today"]),
]
ES_WORDS = ["que", "por", "estamos", "cual", "los", "las", "esta", "semana", "explica", "como", "riesgo", "ventas", "el", "la", "en", "de", "del"]
PT_WORDS = ["voce", "nao", "quais", "resumo", "em", "da", "do", "das", "dos", "estamos", "perdendo", "portugues", "semana", "risco", "vendas"]


def norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def detect_lang(q: str) -> str:
    n = norm(q)
    if "portugues" in n or "em portugues" in n:
        return "pt"
    if "espanol" in n or "en espanol" in n:
        return "es"
    words = re.findall(r"[a-z]+", n)
    es = sum(w in ES_WORDS for w in words) + (2 if "¿" in q else 0) + (1 if "ñ" in q else 0)
    pt = sum(w in PT_WORDS for w in words) + (2 if any(x in q for x in ("ção", "ões", "ã", "õ")) else 0)
    if max(es, pt) < 2:
        return "en"
    return "pt" if pt > es else "es"


def route(q: str) -> tuple[str, dict]:
    n = norm(q)
    best, score = "kpi_summary", 0
    for name, weight, kws in INTENTS:
        s = sum(weight for k in kws if re.search(r"(?<![a-z])" + re.escape(k), n))
        if s > score:
            best, score = name, s
    params = {}
    for code, names in MARKET_NAMES.items():
        if any(re.search(rf"(?<![a-z]){re.escape(x)}(?![a-z])", n) for x in names if len(x) > 2):
            params["market"] = code
            break
    m = re.search(r"(\d+(?:\.\d+)?)\s?%", q)
    if m:
        params["pct"] = float(m.group(1))
    if score == 0:
        best = "kpi_summary" if params.get("market") else "help"
    return best, params


# ------------------------------------------------------------------ tools: return (facts, extras, sources, trace_steps)
def t_share_loss(h, market="MX", **_):
    pp = h.pricing_payload()
    sh = h.com.share
    g = sh[(sh.REGION == "MX-CDMX") & (sh.CHANNEL == "MT")]
    wk = sorted(g.WEEK_START.unique())
    ours = lambda w: g[(g.WEEK_START.isin(w)) & (g.PLAYER == "Northstar")].VALUE_LC.sum() / g[g.WEEK_START.isin(w)].VALUE_LC.sum()
    now, before = ours(wk[-1:]), ours(wk[-5:-1])
    inv = h.inventory()
    s = inv["series"][INV_HERO]
    ai, hold = pp["options"]["ai"], pp["options"]["hold"]
    facts = dict(scope="CDMX & Edomex modern trade, week 44", value_share_now=pct(now, 1, sign=False), value_share_prior_4_weeks=pct(before, 1, sign=False),
                 change=f"{(now - before) * 100:+.1f} pp".replace("-", "−"),
                 causes=[dict(cause="Helvetia price cut", detail=f"{pp['hero']['comp_product']} {pct(-pp['alert']['cut'])} at Hiper Nacional; our price index {pp['alert']['index_before']:.0f} → {pp['alert']['index_now']:.0f}; estimated cross-elasticity {pp['elasticity']['cross']:.1f}"),
                         dict(cause="Fiesta Bites 150g supply", detail=f"DC CDMX stock-out probability {pct(s['p14'], sign=False)} in the Día de Muertos peak")],
                 recommendation=f"TPR {pct(-ai['depth'])} ({pp['alert']['our_price']:.2f} → {ai['price']:.2f}) for {ai['weeks']} weeks plus a stock transfer from DC GDL",
                 gp_cost_recommended=lc(ai["dgp"], "MXN"), gp_cost_if_hold=lc(hold["dgp"], "MXN"))
    return facts, {}, ["POS · CDMX MT · 5 wks", "SAP VBAP / MATDOC", "Elasticity model"], [
        "Intent → share_loss_diagnosis(MX, CDMX, modern trade, wk44)", "DuckDB: category share by player · 5 weeks", "Price-gap & elasticity model", "Stock-out risk (Monte Carlo)"]


def t_stockout(h, market=None, **_):
    inv = h.inventory()
    rows = []
    risky = sorted([s for s in inv["series"].values() if s["p14"] >= 0.25 and not s["seasonal"] and (not market or C.DCS[s["dc"]]["country"] == market)],
                   key=lambda s: -s["p14"])[:6]
    acts = {(a["dc"], a["sku"]): a for a in inv["actions"] if a["kind"] in ("rebalance", "prebuild")}
    import pandas as pd
    from .config import today
    for s in risky:
        a = acts.get((s["dc"], s["sku"]))
        d = (pd.Timestamp(today()) + pd.Timedelta(days=s["stockout_day"])).strftime("%-d %b") if s["stockout_day"] else "> 21 d"
        rows.append(dict(dc=C.DCS[s["dc"]]["code"], sku=C.SKUS[s["sku"]]["name"], date=d, risk=pct(s["p14"], sign=False),
                         fix=a["detail"].split(" · ", 1)[1] if a else "monitor; next MRP receipt covers"))
    facts = dict(horizon="14 days", count=len(rows), items=rows, note="P50 AI forecast, open sales orders and planned receipts from SAP")
    table = dict(cols=["DC", "SKU", "Stock-out", "Risk", "Fix"], rows=[[r["dc"], r["sku"], r["date"], r["risk"], r["fix"]] for r in rows])
    return facts, dict(table=table), ["SAP MATDOC stock", "SAP PLAF receipts", "AI forecast"], [
        "Intent → stockout_scan(horizon=14d)", f"Projected {len(inv['series'])} SKU × DC series", "Monte-Carlo stock-out probability (600 draws)", "Matched fixes from rebalancing engine"]


def t_cost(h, pct_=None, **kw):
    shock = (kw.get("pct") or 10) / 100
    ov = h.overview_core()
    rev52 = float(h.com.si[h.com.si.WEEK_START > h.com.si.WEEK_START.max() - __import__("pandas").Timedelta(weeks=52)].NET_USD.sum())
    cogs_ratio = 1 - ov["totals"]["gm"]
    hedge = 0.52
    cogs_d = shock * C.COCOA_SHARE_OF_COGS * (1 - hedge)
    gm_new = ov["totals"]["gm"] - cogs_d * cogs_ratio
    by_m = []
    from .engine.pricing import HEDGE
    for m in ("MX", "BR", "CO", "AR"):
        cd = shock * C.COCOA_SHARE_OF_COGS * (1 - HEDGE[m])
        by_m.append(dict(market=C.MARKETS[m]["name"], cogs=pct(cd, 1), price_to_hold_margin=pct(cd * 0.57, 1)))
    facts = dict(cocoa_move=pct(shock), hedge_cover_h1="52%", cogs_impact=pct(cogs_d, 1), annualised_cost=usd(rev52 * cogs_ratio * cogs_d),
                 gross_margin_now=pct(ov["totals"]["gm"], 1, sign=False), gross_margin_unpriced=pct(gm_new, 1, sign=False), by_market=by_m,
                 playbook="Mexico: protect MXN 10 coin price points, use grammage / trade-up packs; Brazil: list in January before Páscoa; Argentina: fold into biweekly indexation")
    return facts, {}, ["Cocoa cost index", "Hedge book (mock)", "Elasticity model"], [
        f"Intent → cost_shock(cocoa={pct(shock)})", "COGS exposure: cocoa share of COGS × unhedged share", "Margin & pass-through by market"]


def t_route(h, market="PE", **_):
    rp = h.routes_payload()
    k = {x[0]: (x[1], x[2]) for x in rp["kpis"]}
    lanes = [dict(lane=l["lane"], risk=l["risk"], score=l["score"], action=l["action"]) for l in rp["lanes"][:4]]
    facts = dict(network="Peru · DC Lima (Lurín) and DC Arequipa", disruption="Huaico at km 98 of the Carretera Central (San Mateo), reopening in 36–48 h" if rp["disruption"] else "none active",
                 on_time_original=k["On-time delivery"][0], on_time_ai=k["On-time delivery"][1], freight_ai=k["Freight cost"][1],
                 sales_at_risk_original=k["Sales at risk"][0], melt_risk_loads=f"{k['Melt-risk loads (dry truck > 28°C)'][0]} → {k['Melt-risk loads (dry truck > 28°C)'][1]}",
                 key_routes=[c["title"] + " · " + c["detail"] for c in rp["cards"][:3]], top_lanes=lanes)
    return facts, {}, ["SAP VTTK shipments", "Road alerts (mock)", "Route solver"], [
        "Intent → route_risk(PE)", f"Road graph {len(C.PE_NODES)} nodes · closures applied", f"{rp['solver']} · {rp['stops']} stops · {rp['used']} trucks · {rp['solve_s']:.1f} s"]


def t_pascoa(h, **_):
    sig = next((s for s in h.signals() if s["id"] == "pascoa"), None)
    return dict(sig["facts"]), {}, ["SAP VBAP pre-orders", "PBED PIRs", "AI forecast"], [
        "Intent → seasonal_outlook(Páscoa 2027, BR)", "Pre-orders at 22 weeks before Easter vs last season", "Egg SKUs forecast + pre-order signal"]


def t_sto(h, **_):
    inv = h.inventory()
    a = next((x for x in inv["actions"] if x["kind"] == "rebalance" and x.get("sto")), None)
    if not a:
        return dict(status="no transfer needed right now"), {}, [], ["Intent → create_sto", "No deficit found"]
    s = a["sto"]
    payload = sto_payload(s["donor"], a["dc"], a["sku"], s["qty"], s["day"])
    facts = dict(order_type="stock transport order (UB)", from_dc=C.DCS[s["donor"]]["name"], to_dc=C.DCS[a["dc"]]["name"], product=C.SKUS[a["sku"]]["name"],
                 quantity=f"{num(s['qty'])} cases", delivery_date=payload["to_PurchaseOrderItem"][0]["ScheduleLineDeliveryDate"], reason=a["why"],
                 status="draft, waiting for supply-planner approval in the write-back queue")
    import json
    code = "POST …/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder\n" + json.dumps(payload, indent=2)
    return facts, dict(code=code, rec_key="rec-sto"), ["SAP MATDOC", "Write-back queue"], [
        "Intent → create_sto", f"Source: DC {C.DCS[s['donor']]['code']} excess", "Payload validated against schema", "Queued as draft (simulated)"]


def t_kpi(h, market=None, **_):
    ov = h.overview_core()
    if market:
        m = next(r for r in ov["markets"] if r["code"] == market)
        facts = dict(market=m["name"], net_revenue_mtd=usd(m["rev"]), vs_prior_year=pct(m["vs_py"], 1), vs_plan=pct(m["vs_plan"], 1, sign=False),
                     volume_tonnes=num(m["vol"]), value_share=pct(m["share"], 1, sign=False), share_change=f"{m['share_d'] * 100:+.1f} pp".replace("-", "−"),
                     gross_margin=pct(m["gm"], 1, sign=False), otif=pct(m["otif"], 1, sign=False),
                     signals=[s["title"] for s in h.signals() if s["market"] == market])
    else:
        t = ov["totals"]
        facts = dict(scope="LATAM, month to date", net_revenue_mtd=usd(t["rev"]), vs_prior_year=pct(t["rev"] / t["rev_py"] - 1, 1), vs_plan=pct(t["rev"] / t["plan"], 1, sign=False),
                     gross_margin=pct(t["gm"], 1, sign=False), value_share=pct(t["share"], 1, sign=False), otif=pct(t["otif"], 1, sign=False),
                     top_signals=[s["title"] + ": " + s["action"] for s in h.signals()[:3]])
    return facts, {}, ["SAP billing (VBRP)", "POS / panel"], [f"Intent → kpi_summary({market or 'LATAM'})", "DuckDB: MTD sell-in vs PY & plan", "Share MAT from POS panel"]


def t_forecast(h, **_):
    br = h.fc.bridge("MX1D", "100045")
    acc = h.fc.accuracy()
    facts = dict(example="Dulcera Milk 90g at DC CDMX, next 8 weeks", sap_baseline=num(br[0]["value"]) + " cases", ai_forecast=num(br[-1]["value"]) + " cases",
                 drivers=[dict(driver=b["label"], cases=f"{b['value']:+,}".replace("-", "−")) for b in sorted(br[1:-1], key=lambda b: -abs(b["value"]))[:4]],
                 accuracy_ai=pct(acc["ALL"]["ai"], 1, sign=False), accuracy_sap=pct(acc["ALL"]["sap"], 1, sign=False),
                 safety_stock_release=usd(h.fc.safety_stock_release_usd()))
    return facts, {}, ["SAP LIPS history", "TPM promo plan", "POS", "Weather"], ["Intent → forecast_explain", "Counterfactual bridge (feature groups on/off)", "13-week backtest vs SAP IBP"]


def t_trends(h, **_):
    mk = h.market_payload()
    facts = dict(trends=[dict(trend=t["label"], markets=t["markets"], momentum_yoy=pct(t["yoy"])) for t in mk["trends"]],
                 category_growth=pct(mk["kpis"][0]["value"], 1))
    return facts, {}, ["Search & social index (mock)", "POS panel"], ["Intent → consumer_trends", "Momentum: last 13 weeks vs last year"]


def t_ar(h, **_):
    sig = next((s for s in h.signals() if s["id"] == "ar_price"), None)
    return dict(sig["facts"]), {}, ["Macro feed (mock)", "POS price tracker"], ["Intent → price_indexation(AR)", "Price index vs category", "CPI pass-through"]


def t_help(h, **_):
    return dict(capabilities=["diagnose share loss and competitor moves", "scan stock-out risk by DC", "simulate cocoa cost shocks", "explain route risks and re-routing",
                              "Páscoa and seasonal outlooks", "draft SAP stock transport orders", "market KPI summaries", "explain forecasts vs the SAP baseline"]), {}, [], ["Intent → help"]


TOOLS = dict(share_loss=t_share_loss, stockout_scan=t_stockout, cost_shock=t_cost, route_risk=t_route, pascoa=t_pascoa, create_sto=t_sto,
             kpi_summary=t_kpi, forecast_explain=t_forecast, trends=t_trends, ar_price=t_ar, help=t_help)


def template(intent: str):
    def f(facts, lang):
        if intent == "share_loss":
            c = facts["causes"]
            if lang == "es":
                return (f"En {facts['scope']} nuestra participación pasó de {facts['value_share_prior_4_weeks']} a {facts['value_share_now']} ({facts['change']}). "
                        f"Causas: {c[0]['cause']} ({c[0]['detail']}) y {c[1]['cause']} ({c[1]['detail']}). "
                        f"Recomendación: {facts['recommendation']}; impacto en utilidad bruta {facts['gp_cost_recommended']} frente a {facts['gp_cost_if_hold']} si mantenemos precio.")
            return (f"In {facts['scope']} our value share moved from {facts['value_share_prior_4_weeks']} to {facts['value_share_now']} ({facts['change']}). "
                    f"Drivers: {c[0]['cause']} ({c[0]['detail']}) and {c[1]['cause']} ({c[1]['detail']}). "
                    f"Recommendation: {facts['recommendation']}; gross-profit impact {facts['gp_cost_recommended']} versus {facts['gp_cost_if_hold']} if we hold price.")
        if intent == "stockout_scan":
            return f"{facts['count']} SKU × DC combinations show stock-out risk within {facts['horizon']} ({facts['note']}). Fixes are drafted in the SAP write-back queue for approval."
        if intent == "cost_shock":
            return (f"A {facts['cocoa_move']} cocoa move ({facts['hedge_cover_h1']} hedged for H1) adds {facts['cogs_impact']} to COGS, about {facts['annualised_cost']} annualised. "
                    f"Unpriced, gross margin goes from {facts['gross_margin_now']} to {facts['gross_margin_unpriced']}. Playbook: {facts['playbook']}.")
        if intent == "route_risk":
            if lang == "es":
                return (f"Red: {facts['network']}. Disrupción: {facts['disruption']}. Puntualidad del plan original {facts['on_time_original']}, plan reoptimizado {facts['on_time_ai']} "
                        f"(flete {facts['freight_ai']}); cargas con riesgo de derretimiento {facts['melt_risk_loads']}.")
            return (f"Network: {facts['network']}. Disruption: {facts['disruption']}. On-time: original plan {facts['on_time_original']}, re-optimized {facts['on_time_ai']} "
                    f"(freight {facts['freight_ai']}); melt-risk loads {facts['melt_risk_loads']}.")
        if intent == "pascoa":
            if lang == "pt":
                return (f"A Páscoa 2027 cai em {facts['easter_date']}. Os pré-pedidos estão {facts['preorders_vs_last_year']} vs. o ano passado e a previsão de IA para ovos é de "
                        f"{facts['ai_egg_forecast']} ({facts['vs_last_season']} vs. a última temporada) na planta {facts['plant']}, com a linha a {facts['line_utilization_feb']} em fevereiro.")
            return (f"Páscoa 2027 falls on {facts['easter_date']}. Pre-orders are {facts['preorders_vs_last_year']} vs last year; the AI egg forecast is {facts['ai_egg_forecast']} "
                    f"({facts['vs_last_season']} vs last season) at plant {facts['plant']}, with the line at {facts['line_utilization_feb']} in February.")
        if intent == "create_sto":
            if "from_dc" not in facts:
                return "No stock transport order is needed right now."
            return f"Drafted a {facts['order_type']} for {facts['quantity']} of {facts['product']} from {facts['from_dc']} to {facts['to_dc']}, delivery {facts['delivery_date']}. Status: {facts['status']}."
        if intent == "kpi_summary":
            head = facts.get("market") or facts.get("scope")
            return (f"{head}: net revenue {facts['net_revenue_mtd']} ({facts['vs_prior_year']} vs prior year, {facts['vs_plan']} of plan), gross margin {facts['gross_margin']}, "
                    f"value share {facts['value_share']}, OTIF {facts['otif']}.")
        if intent == "forecast_explain":
            d = facts["drivers"]
            return (f"{facts['example']}: AI {facts['ai_forecast']} vs SAP baseline {facts['sap_baseline']}. Main drivers: " + ", ".join(f"{x['driver']} {x['cases']}" for x in d[:3])
                    + f". Backtest accuracy AI {facts['accuracy_ai']} vs SAP {facts['accuracy_sap']}; this releases about {facts['safety_stock_release']} of safety stock.")
        if intent == "trends":
            return "Consumer momentum (last 13 weeks vs last year): " + "; ".join(f"{t['trend']} {t['momentum_yoy']}" for t in facts["trends"]) + "."
        if intent == "ar_price":
            return f"Argentina CPI {facts['cpi_mom']} m/m; our price index vs category {facts['our_price_index_vs_category']}. Recommendation: {facts['recommended_increase']} list from {facts['effective']}, about {facts['gp_per_month']} GP per month."
        return "I can " + ", ".join(facts["capabilities"]) + "."
    return f


INSTRUCTION = ("Answer the user's question: \"{q}\". Use 3–6 short sentences or '- ' bullets. Lead with the direct answer, then the evidence, "
               "then the recommended action if the facts contain one.")


def answer(q: str, lang: str | None = None, force: bool = False) -> dict:
    t0 = time.time()
    lang = lang or detect_lang(q)
    intent, params = route(q)
    h = hub()
    t_tool = time.time()
    facts, extras, sources, steps = TOOLS[intent](h, **params)
    tool_ms = int((time.time() - t_tool) * 1000)
    res = GATEWAY.narrate(f"copilot:{intent}:{params.get('market', '')}", facts, lang, INSTRUCTION.format(q=q), template(intent), force=force)
    steps = steps + [f"Analytics computed · {tool_ms} ms", f"Narrative written · figures verified against facts · {res['ms'] / 1000:.1f} s"]
    return dict(text=res["text"], intent=intent, lang=lang, sources=sources, trace=steps, ms=int((time.time() - t0) * 1000), **extras)


SUGGESTIONS = [
    "¿Por qué estamos perdiendo participación en CDMX canal moderno esta semana?",
    "Which DCs will stock out in the next 14 days?",
    "What if cocoa costs rise another 10%?",
    "Explica el riesgo de rutas en Perú",
    "Resumo da Páscoa 2027 em português",
    "Draft an STO in SAP for CDMX",
    "How is Brazil doing this month?",
]
