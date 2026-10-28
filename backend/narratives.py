"""Screen narratives: facts → LLM (via gateway) with a deterministic template fallback."""
from __future__ import annotations

from . import catalog as C
from .hub import Hub, hub, lc, num, pct, usd
from .llm import GATEWAY


def _briefing(h: Hub, **_):
    sig = h.signals()[:5]
    facts = dict(total_value_at_stake_across_all_signals=usd(sum(s["value"] for s in sig)),
                 signals=[dict(title=s["title"], recommended_action=s["action"], **s["facts"]) for s in sig])
    instr = ("Write a 3-sentence executive summary of today's briefing for the LATAM commercial director. Lead with the most urgent "
             "signal, then cover the others briefly, each with its recommended action. Do not use bullet points.")

    def tmpl(f, lang):
        s = f["signals"]
        parts = [f"{x['title']}: {x['recommended_action']}" for x in s[:4]]
        return (f"Five signals need a decision today, with {f['total_value_at_stake_across_all_signals']} at stake across them. Most urgent: {parts[0]}. "
                + " ".join(p + "." for p in parts[1:]))
    return facts, instr, tmpl


def _pricing(h: Hub, **_):
    pp = h.pricing_payload()
    o = pp["options"]
    fmt = lambda r: dict(price=f"MXN {r['price']:.2f}", price_index=f"{r['index']:.0f}", volume_8w=pct(r["vol"], 1), gross_profit_vs_pre_cut_baseline=lc(r["dgp"], "MXN"),
                         promo_roi="n/a" if r["roi"] is None else f"{r['roi']:.1f}x", guardrails_failed=[g["name"] for g in r["guardrails"] if g["ok"] == "x"] or "none")
    ai = o["ai"]
    facts = dict(product=pp["hero"]["sku_name"], customer="Hiper Nacional", competitor_cut=pct(-pp["alert"]["cut"]), price_index_band="95–105",
                 own_price_elasticity=f"{pp['elasticity']['own']:.1f}", cross_elasticity=f"{pp['elasticity']['cross']:.1f}",
                 option_a_hold=fmt(o["hold"]), option_b_full_match=fmt(o["match"]), option_c_recommended=dict(fmt(ai), price_cut_depth=pct(-ai["depth"]), promo_weeks=ai["weeks"],
                 display="yes" if ai["display"] else "no"),
                 option_c_gross_profit_better_than_a_by=lc(ai["dgp"] - o["hold"]["dgp"], "MXN"), option_c_gross_profit_better_than_b_by=lc(ai["dgp"] - o["match"]["dgp"], "MXN"),
                 context="The competitor cut lowers gross profit versus the pre-cut baseline under every option; option C loses the least.")
    instr = ("In 3 sentences, explain why option C is recommended over holding price (A) and a full match (B). Mention the price-index band, "
             "by how much option C's gross profit beats A and B, and whether a secondary display is used.")

    def tmpl(f, lang):
        c = f["option_c_recommended"]
        return (f"A shallow {c['price_cut_depth']} TPR to {c['price']} brings the price index to {c['price_index']}, inside the {f['price_index_band']} band, "
                f"while holding price leaves it at {f['option_a_hold']['price_index']}. Over 8 weeks its gross profit is {f['option_c_gross_profit_better_than_a_by']} better than holding "
                f"and {f['option_c_gross_profit_better_than_b_by']} better than a full match, because promo elasticity ({f['own_price_elasticity']}) recovers volume without the margin hit. "
                f"A secondary display is {'included' if c['display'] == 'yes' else 'not ROI-positive at this depth'}.")
    return facts, instr, tmpl


def _forecast(h: Hub, dc: str = "MX1D", sku: str = "100045", **_):
    br = h.fc.bridge(dc, sku)
    acc = h.fc.accuracy()[C.DCS[dc]["country"]]
    sap, ai = br[0]["value"], br[-1]["value"]
    comps = sorted(br[1:-1], key=lambda b: -abs(b["value"]))
    facts = dict(product=C.SKUS[sku]["name"], dc=C.DCS[dc]["name"], horizon="next 8 weeks", sap_baseline_cases=num(sap), ai_forecast_cases=num(ai),
                 difference=pct(ai / sap - 1, 1), drivers=[dict(driver=b["label"], cases=("+" if b["value"] > 0 else "−" if b["value"] < 0 else "") + num(abs(b["value"]))) for b in comps],
                 market_accuracy_ai=pct(acc["ai"], 1, sign=False), market_accuracy_sap=pct(acc["sap"], 1, sign=False))
    instr = ("In 3–4 sentences, explain why the AI forecast differs from the SAP IBP statistical baseline for this product and DC. "
             "Use the two or three drivers with the largest absolute values and say what the SAP baseline cannot see. End with the accuracy comparison.")

    def tmpl(f, lang):
        d = f["drivers"]
        return (f"For {f['product']} at {f['dc']}, the AI forecast for the {f['horizon']} is {f['ai_forecast_cases']} cases, {f['difference']} versus the "
                f"SAP IBP baseline of {f['sap_baseline_cases']}. The largest drivers are {d[0]['driver'].lower()} ({d[0]['cases']} cases), "
                f"{d[1]['driver'].lower()} ({d[1]['cases']}) and {d[2]['driver'].lower()} ({d[2]['cases']}). The SAP baseline projects last year's shape "
                f"and cannot see the promo plan, competitor prices, weather or POS momentum. Backtest accuracy in this market: AI {f['market_accuracy_ai']} vs SAP {f['market_accuracy_sap']}.")
    return facts, instr, tmpl


def _inventory(h: Hub, **_):
    inv = h.inventory()
    acts = inv["actions"]
    reb = next((a for a in acts if a["kind"] == "rebalance"), None)
    md = next((a for a in acts if a["kind"] == "markdown"), None)
    facts = dict(horizon="next 14 days", stockout=dict(product=C.SKUS[reb["sku"]]["name"], dc=C.DCS[reb["dc"]]["name"], probability_14d=pct(reb["risk_before"], sign=False),
                               fix=reb["detail"].split(" · ", 1)[1], revenue_protected=usd(reb["value"])) if reb else "none",
                 markdown=dict(product=C.SKUS[md["sku"]]["name"], quantity=f"{num(md['qty'])} cases", days_to_expiry=md["days_left"], dcs=md["dc"],
                               value_recovery="71% vs 18% write-off") if md else "none")
    instr = "In 2–3 sentences, explain the most important stock-out risk and the recommended fix, then the shelf-life markdown opportunity."

    def tmpl(f, lang):
        s, m = f["stockout"], f["markdown"]
        t = ""
        if s != "none":
            t += f"{s['product']} at {s['dc']} has a {s['probability_14d']} stock-out probability within 14 days; the fix is to {s['fix']}, protecting {s['revenue_protected']} of revenue. "
        if m != "none":
            t += f"{m['quantity']} of {m['product']} expire in {m['days_to_expiry']} days at DC {m['dcs']}; hard-discount bundles recover {m['value_recovery']}."
        return t.strip()
    return facts, instr, tmpl


def _routes(h: Hub, **_):
    rp = h.routes_payload()
    k = {x[0]: (x[1], x[2]) for x in rp["kpis"]}
    facts = dict(disruption="Huaico closes Carretera Central at km 98 (San Mateo), reopening in 36–48 h" if rp["disruption"] else "none (network nominal)",
                 stops=rp["stops"], trucks_used=rp["used"], on_time=dict(original=k["On-time delivery"][0], ai=k["On-time delivery"][1]),
                 freight=dict(original=k["Freight cost"][0], ai=k["Freight cost"][1]), sales_at_risk=dict(original=k["Sales at risk"][0], ai=k["Sales at risk"][1]),
                 melt_risk_loads=dict(original=k["Melt-risk loads (dry truck > 28°C)"][0], ai=k["Melt-risk loads (dry truck > 28°C)"][1]),
                 key_routes=[c["title"] + " · " + c["detail"] for c in rp["cards"][:3]])
    instr = ("In 3 sentences, explain the disruption (if any) and how the re-optimized plan protects deliveries versus the original plan, "
             "citing on-time delivery, freight cost, sales at risk and melt-risk loads.")

    def tmpl(f, lang):
        if f["disruption"].startswith("none"):
            return (f"No active disruption. Against the cost-only plan, the risk-aware plan puts hot-town drops on reefer trucks "
                    f"(melt-risk loads {f['melt_risk_loads']['original']} → {f['melt_risk_loads']['ai']}) for freight of {f['freight']['ai']}.")
        return (f"{f['disruption']}. The original plan would deliver {f['on_time']['original']} on time with {f['sales_at_risk']['original']} of sales at risk; "
                f"the re-optimized plan reaches {f['on_time']['ai']} by re-routing Junín loads, at a freight cost of {f['freight']['ai']}. "
                f"Melt-risk loads drop from {f['melt_risk_loads']['original']} to {f['melt_risk_loads']['ai']}.")
    return facts, instr, tmpl


BUILDERS = dict(briefing=_briefing, pricing=_pricing, forecast=_forecast, inventory=_inventory, routes=_routes)


def narrative(task: str, lang: str = "en", fresh: bool = False, **params) -> dict:
    h = hub()
    facts, instr, tmpl = BUILDERS[task](h, **params)
    key_task = task + ("" if not params else ":" + ":".join(f"{k}={v}" for k, v in sorted(params.items())))
    res = GATEWAY.narrate(key_task, facts, lang, instr, tmpl, force=fresh)
    return dict(text=res["text"], ms=res["ms"])
