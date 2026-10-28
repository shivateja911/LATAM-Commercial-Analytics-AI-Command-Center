"""Facade over all engines: caches results per demo-state version, builds briefing signals, recommendations,
and the facts + templates behind every AI narrative."""
from __future__ import annotations

import threading
import time

import numpy as np
import pandas as pd

from . import catalog as C
from .config import settings, today
from .datagen import HIST
from .engine.commercial import Commercial
from .engine.forecast import Forecaster
from .engine.inventory import HERO as INV_HERO
from .engine.inventory import Inventory
from .engine.pricing import Pricing
from .engine.routing import Router
from .state import SCENARIOS, STATE
from .store import store

SEV_ORDER = dict(neg=0, warn=1, info=2, pos=3)


# ------------------------------------------------------------------ formatting helpers (facts are pre-formatted strings)
def usd(v: float) -> str:
    a = abs(v)
    s = f"${a / 1e6:.1f}M" if a >= 1e6 else (f"${a / 1e3:.0f}k" if a >= 1e3 else f"${a:.0f}")
    return ("−" if v < 0 else "") + s


def lc(v: float, ccy: str) -> str:
    a = abs(v)
    s = f"{ccy} {a / 1e6:.2f}M" if a >= 1e6 else (f"{ccy} {a / 1e3:.0f}k" if a >= 1e3 else f"{ccy} {a:,.2f}")
    return ("−" if v < 0 else "") + s


def pct(v: float, d: int = 0, sign: bool = True) -> str:
    s = f"{abs(v) * 100:.{d}f}%"
    return (("+" if v > 0 else "−" if v < 0 else "") + s) if sign else s


def num(v: float) -> str:
    return f"{v:,.0f}"


class Hub:
    def __init__(self):
        t0 = time.time()
        self.fc = Forecaster()
        self.pricing = Pricing()
        self.inv = Inventory(self.fc)
        self.router = Router()
        self.com = Commercial()
        self._cache: dict = {}
        self._lock = threading.RLock()
        self.boot_seconds = round(time.time() - t0, 1)

    # ------------------------------------------------------------ cached engine outputs
    def scen(self) -> tuple:
        return tuple(sorted(STATE.active))

    def _memo(self, name: str, key, fn):
        with self._lock:
            k = (name, key)
            if k not in self._cache:
                self._cache[k] = fn()
            return self._cache[k]

    def inventory(self):
        s = self.scen()
        with self._lock:
            self.fc.refresh(s)
            return self._memo("inv", s, lambda: self.inv.compute(s))

    def pricing_payload(self):
        s = self.scen()
        return self._memo("pricing", s, lambda: self.pricing.payload(s))

    def routes_payload(self):
        s = self.scen()
        return self._memo("routes", ("huaico_pe" in s, "heat_mx" in s, "strike_br" in s, "rionegro_br" in s), lambda: self.router.payload(s))

    def overview_core(self):
        s = self.scen()
        return self._memo("ov", s, lambda: self.com.overview(s, self.fc.accuracy()))

    def market_payload(self):
        s = self.scen()
        return self._memo("market", ("heat_mx" in s,), lambda: self.com.market(s))

    # ------------------------------------------------------------ signals (briefing)
    def signals(self) -> list[dict]:
        s = self.scen()
        return self._memo("signals", s, lambda: self._signals(s))

    def _signals(self, scen: tuple) -> list[dict]:
        out = []
        fx_mx = C.MARKETS["MX"]["fx"]
        # 1. competitor price move → pricing response
        pp = self.pricing_payload()
        a, o = pp["alert"], pp["options"]
        ai, hold, match = o["ai"], o["hold"], o["match"]
        out.append(dict(
            id="pricing", sev="neg", market="MX", value=(ai["dgp"] - hold["dgp"]) / fx_mx, goto="pricing",
            title="Competitor price cut in CDMX modern trade",
            facts=dict(competitor_product=pp["hero"]["comp_product"], customer="Hiper Nacional (CDMX & Edomex, modern trade)",
                       competitor_cut=pct(-a["cut"]), competitor_price=f"MXN {a['comp_regular']:.2f} → {a['comp_now']:.2f}",
                       our_product=pp["hero"]["sku_name"], our_price=f"MXN {a['our_price']:.2f}", price_index=f"{a['index_before']:.0f} → {a['index_now']:.0f}",
                       sellout_impact=f"{pct(a['impact'])} vs expected (model-implied)", recommendation=f"TPR {pct(-ai['depth'])} to MXN {ai['price']:.2f} for {ai['weeks']} weeks",
                       gp_saved_vs_hold=lc(ai["dgp"] - hold["dgp"], "MXN"), gp_saved_vs_match=lc(ai["dgp"] - match["dgp"], "MXN")),
            action=f"TPR {pct(-ai['depth'])} · saves {lc(ai['dgp'] - hold['dgp'], 'MXN')} GP vs holding"))
        # 2. stock-outs
        inv = self.inventory()
        hero = next((x for x in inv["actions"] if x["kind"] == "rebalance" and (x["dc"], x["sku"]) == INV_HERO), None)
        if hero:
            sh = inv["series"][INV_HERO]
            days = sh["stockout_day"]
            date_s = (pd.Timestamp(today()) + pd.Timedelta(days=days)).strftime("%-d %b") if days else "within 14 days"
            out.append(dict(
                id="stockout", sev="neg", market="MX", value=hero["value"], goto="sap",
                title=f"Día de Muertos stock-out risk · DC {C.DCS[INV_HERO[0]]['code']}",
                facts=dict(product=C.SKUS[INV_HERO[1]]["name"], dc=C.DCS[INV_HERO[0]]["name"], stockout_probability=pct(sh["p14"], sign=False),
                           projected_stockout=date_s, fix=hero["detail"].split(" · ", 1)[1], donor_cover=f"{inv['series'][(hero['sto']['donor'], INV_HERO[1])]['dos']:.0f} days at DC {C.DCS[hero['sto']['donor']]['code']}" if hero.get("sto") else "n/a",
                           revenue_protected=usd(hero["value"])),
                action=hero["detail"].split(" · ", 1)[1]))
        # 3. route disruption
        if "huaico_pe" in scen:
            rp = self.routes_payload()
            out.append(dict(
                id="route", sev="neg", market="PE", value=(rp["ev_legacy"]["sales_at_risk"] - rp["ev_ai"]["sales_at_risk"]) / C.MARKETS["PE"]["fx"], goto="routes",
                title="Huaico closes Carretera Central (Peru)",
                facts=dict(location="km 98, San Mateo", reopening="36–48 h", on_time_original=pct(rp["ev_legacy"]["on_time"], sign=False),
                           on_time_ai=pct(rp["ev_ai"]["on_time"], sign=False), sales_at_risk_original=lc(rp["ev_legacy"]["sales_at_risk"], "S/"),
                           reroute="Junín loads via Canta–Huayllay–Cerro de Pasco (daylight only, escort)", freight_change=rp["kpis"][1][2].split("(")[-1].rstrip(")")),
                action="Re-route Junín loads via Canta · protect Todos los Santos orders"))
        # 4. Páscoa
        pre = store().table("PREORDERS_PASCOA")
        p26 = pre[(pre.SEASON == 2026) & (pre.WEEKS_BEFORE_EASTER == 22)].CUM_CASES.iloc[0]
        p27 = pre[(pre.SEASON == 2027) & (pre.WEEKS_BEFORE_EASTER == 22)].CUM_CASES.iloc[0]
        eggs = [self.fc.idx[k] for k in self.fc.idx if k[1] in ("100081", "100082")]
        wk = pd.to_datetime(self.fc.weeks.week_start.values[:HIST])
        last_mask = (wk > pd.Timestamp(C.EASTER[2026]) - pd.Timedelta(weeks=14)) & (wk <= pd.Timestamp(C.EASTER[2026]))
        last_season = float(sum(self.fc.Y[i, :HIST][last_mask].sum() for i in eggs))
        # seasonal model: last season's volume, lifted by the pre-order signal (partially passed through) and market volume growth
        pre_lift = (p27 / p26 - 1) * 0.6
        fc_eggs = last_season * (1 + pre_lift) * (1 + C.MARKETS["BR"]["growth"] - 0.035)
        out.append(dict(
            id="pascoa", sev="pos", market="BR", value=max(fc_eggs - last_season, 0) * 12 * 5.5, goto="forecast",
            title="Brazil Páscoa 2027 starts early",
            facts=dict(easter_date="28 Mar 2027", preorders_vs_last_year=pct(p27 / p26 - 1), ai_egg_forecast=f"{num(fc_eggs)} cases", preorder_adjustment=pct(pre_lift, 1),
                       vs_last_season=pct(fc_eggs / last_season - 1) if last_season else "n/a", plant="BR01 Jundiaí", line_utilization_feb="94% (line L3)"),
            action=f"Raise Páscoa PIRs {pct(fc_eggs / last_season - 1) if last_season else ''} · book climate-controlled pallets"))
        # 5. Argentina indexation
        macro = store().table("MACRO")
        ar_cpi = float(macro[macro.COUNTRY == "AR"].sort_values("MONTH").CPI_MOM.iloc[-1])
        pos = self.com.pos
        arp = pos[(pos.COUNTRY == "AR") & (pos.WEEK_START == pos.WEEK_START.max())]
        idx = float((arp.LIST_PRICE_LC / arp.CAT_INDEX).mean() / (pos[pos.COUNTRY == "AR"].LIST_PRICE_LC / pos[pos.COUNTRY == "AR"].CAT_INDEX).mean())
        inc = max(0.0, (1 / idx - 1) + ar_cpi)
        ar_rev = [r for r in self.overview_core()["markets"] if r["code"] == "AR"][0]["rev"]
        out.append(dict(
            id="ar_price", sev="info", market="AR", value=ar_rev * inc * 0.6, goto="pricing",
            title=f"Argentina CPI print {ar_cpi * 100:.1f}% m/m",
            facts=dict(cpi_mom=f"{ar_cpi * 100:.1f}%", our_price_index_vs_category=f"{idx * 100:.0f}", recommended_increase=pct(inc, 1), effective="9 Nov",
                       gp_per_month=usd(ar_rev * inc * 0.6)),
            action=f"List {pct(inc, 1)} from 9 Nov · hold 12g coin price point"))
        # scenario-driven signals
        if "heat_mx" in scen:
            delta = self._heat_delta()
            out.append(dict(id="heat", sev="warn", market="MX", value=abs(delta["usd"]) + 150_000, goto="routes", title="Heat wave in northern Mexico",
                            facts=dict(temperatures="Monterrey 41°C, Mérida 39°C", demand_impact_2_weeks=pct(delta["pct"], 1), lanes_needing_reefer="Monterrey → Mérida, Monterrey → Tijuana",
                                       dispatch_window="04:00 dispatch, reefer above 28°C"),
                            action="Reefer + 04:00 dispatch on northern lanes · trim northern replenishment"))
        if "rionegro_br" in scen:
            pre_acts = [x for x in inv["actions"] if x["kind"] == "prebuild"]
            q = sum(x["qty"] for x in pre_acts)
            out.append(dict(id="river", sev="warn", market="BR", value=sum(x["value"] for x in pre_acts), goto="inventory", title="Rio Negro low water · Manaus",
                            facts=dict(barge_capacity="−35%", inbound_delay="+7 days", prebuild=f"{num(q)} cases from DC Cajamar", route="road to Porto Velho, then Madeira barge (11 days)"),
                            action=f"Pre-build {num(q)} cs at DC Manaus"))
        if "cocoa_up" in scen:
            rows = pp["cocoa"]["rows"]
            out.append(dict(id="cocoa", sev="warn", market="LATAM", value=self.overview_core()["totals"]["rev"] * 0.012, goto="pricing", title="Cocoa futures +8%",
                            facts=dict(cocoa_move="+8%", cogs_impact_mx=pct(rows[0]["cogs"], 1), price_needed_mx=pct(rows[0]["price"], 1), approach="PPA first in Mexico; list increases in Q1 elsewhere"),
                            action="Pass-through plan by market"))
        if "strike_br" in scen:
            out.append(dict(id="strike", sev="warn", market="BR", value=420_000, goto="routes", title="Trucker strike on BR-116",
                            facts=dict(duration="48 h", dcs_affected="Recife, Porto Alegre", inbound_delay="+2 days", otif_impact="−4.2 pp Brazil"),
                            action="Re-sequence via BR-101 · protect key accounts"))
        md = next((x for x in inv["actions"] if x["kind"] == "markdown"), None)
        if md:
            out.append(dict(id="markdown", sev="info", market="MX", value=md["value"], goto="inventory", title=f"Short shelf-life stock · {C.SKUS[md['sku']]['name']}",
                            facts=dict(quantity=f"{num(md['qty'])} cases", days_to_expiry=f"{md['days_left']} days", dcs=md["dc"].replace(",", ", "), recovery="71% via hard-discount bundles vs 18% write-off"),
                            action="Hard-discount bundles before Buen Fin"))
        for x in out:
            x["text"] = signal_text(x)
        out.sort(key=lambda x: (SEV_ORDER[x["sev"]], -x["value"]))
        return out

    def _heat_delta(self) -> dict:
        rows = [i for i, (dc, _) in enumerate(self.fc.keys) if dc in ("MX3D", "MX5D", "MX4D")]
        ts = np.tile(np.arange(HIST, HIST + 2), len(rows))
        r = np.repeat(rows, 2)
        clim = self.fc.temp_clim[r, self.fc.weeks.iso_week.values[ts]]
        hot = self.fc.overrides["temp"][r, (ts - HIST)]
        base = self.fc._predict(self.fc.models, r, ts, temp=clim)[0.5]
        heat = self.fc._predict(self.fc.models, r, ts, temp=hot)[0.5]
        price = np.array([C.SKUS[self.fc.keys[i][1]]["upc"] * C.SKUS[self.fc.keys[i][1]]["price"] for i in r])
        return dict(pct=float(heat.sum() / base.sum() - 1), usd=float(((heat - base) * price).sum()))

    # ------------------------------------------------------------ recommendations → SAP write-back
    def recommendations(self) -> list[dict]:
        sig = {s_["id"]: s_ for s_ in self.signals()}
        pp = self.pricing_payload()
        inv = self.inventory()
        recs = []
        if "pricing" in sig:
            ai = pp["options"]["ai"]
            recs.append(dict(key="rec-pricing", type="Pricing", tone="gold", market="MX", title=f"TPR {pct(-ai['depth'])} on {pp['hero']['sku_name']} at Hiper Nacional, {ai['weeks']} weeks",
                             metric="GP saved", metric_value=sig["pricing"]["facts"]["gp_saved_vs_hold"] + " vs hold", confidence=0.86, owner="RGM Mexico",
                             writeback=dict(title=f"Price condition K007 · {pct(ai['depth'], sign=False)} · {ai['weeks']} weeks", tcode="VK11", api="API_SLSPRCGCONDITIONRECORD_SRV",
                                            approver="RGM manager MX", doc_prefix="CR",
                                            preview={"ConditionType": "K007", "SalesOrganization": "MX10", "Customer": "0000412233", "Material": pp["hero"]["sku"],
                                                     "ConditionRateValue": round(ai["depth"] * 100, 1), "ConditionValidityStartDate": "2026-10-28",
                                                     "ConditionValidityEndDate": (pd.Timestamp(today()) + pd.Timedelta(weeks=ai["weeks"])).strftime("%Y-%m-%d")})))
        hero = next((x for x in inv["actions"] if x["kind"] == "rebalance" and (x["dc"], x["sku"]) == INV_HERO), None)
        if hero and hero.get("sto"):
            stoq = hero["sto"]
            recs.append(dict(key="rec-sto", type="Supply", tone="info", market="MX", title=f"STO {num(stoq['qty'])} cs {C.SKUS[INV_HERO[1]]['name']} · DC {C.DCS[stoq['donor']]['code']} → DC {C.DCS[INV_HERO[0]]['code']}" + (" + pull-in" if hero.get("pull") else ""),
                             metric="Revenue protected", metric_value=usd(hero["value"]), confidence=round(0.75 + 0.2 * hero["risk_before"], 2), owner="Supply planner MX",
                             writeback=dict(title=f"STO (UB) · {C.DCS[stoq['donor']]['code']} → {C.DCS[INV_HERO[0]]['code']} · {num(stoq['qty'])} cs", tcode="ME21N", api="API_PURCHASEORDER_PROCESS_SRV",
                                            approver="Supply planner MX", doc_prefix="45", preview=sto_payload(stoq["donor"], INV_HERO[0], INV_HERO[1], stoq["qty"], stoq["day"]))))
        if "route" in sig:
            recs.append(dict(key="rec-route", type="Logistics", tone="warn", market="PE", title="Re-route Junín loads via Canta–Cerro de Pasco after the Carretera Central closure",
                             metric="On-time", metric_value=f"{sig['route']['facts']['on_time_original']} → {sig['route']['facts']['on_time_ai']}", confidence=0.82, owner="Transport PE",
                             writeback=dict(title="Shipment update · Junín loads re-routed", tcode="VT02N", api="Shipment IDoc SHPMNT06", approver="Transport planner PE", doc_prefix="77",
                                            preview={"ShipmentType": "0001", "TransportationPlanningPoint": "PE10", "Route": "PE-CNT-HYO", "Remark": "Carretera Central closed km 98"})))
        if "ar_price" in sig:
            f = sig["ar_price"]["facts"]
            recs.append(dict(key="rec-ar", type="Pricing", tone="gold", market="AR", title=f"List price {f['recommended_increase']} from {f['effective']} (CPI indexation), hold 12g coin price point",
                             metric="GP", metric_value=f"+{f['gp_per_month']} / month", confidence=0.77, owner="RGM Southern Cone",
                             writeback=dict(title=f"Price list PR00 · AR · {f['recommended_increase']}", tcode="VK11", api="API_SLSPRCGCONDITIONRECORD_SRV", approver="RGM manager AR", doc_prefix="CR",
                                            preview={"ConditionType": "PR00", "SalesOrganization": "AR10", "ConditionRateValueChange": f["recommended_increase"], "ValidFrom": "2026-11-09"})))
        cal = pp["calendar"]
        bf = next((c for c in cal if "Buen Fin 3x2" in c["name"]), None)
        if bf:
            recs.append(dict(key="rec-buenfin", type="Promo", tone="ai", market="MX", title="Replace Buen Fin 3x2 on Dulcera Milk 40g with a “2 × MXN 40” bundle",
                             metric="Promo ROI", metric_value=f"{bf['roi']:.1f}x → 1.4x", confidence=0.80, owner="Trade marketing MX",
                             writeback=dict(title="Trade promotion change · Buen Fin bundle", tcode="TPM (S/4 Trade Promotion)", api="Trade promotion API", approver="Trade marketing MX", doc_prefix="TP",
                                            preview={"Promotion": "BF26-MX-0412", "Mechanic": "2 x MXN 40", "Material": "100041"})))
        if "pascoa" in sig:
            f = sig["pascoa"]["facts"]
            recs.append(dict(key="rec-pascoa", type="Supply", tone="info", market="BR", title="Raise Páscoa 2027 PIRs at BR01 and book climate-controlled pallets",
                             metric="Pre-orders", metric_value=f["preorders_vs_last_year"] + " vs LY", confidence=0.74, owner="Demand planner BR",
                             writeback=dict(title="PIR change · Páscoa eggs · BR01", tcode="MD61", api="BAPI_REQUIREMENTS_CHANGE", approver="Demand planner BR", doc_prefix="PB",
                                            preview={"Material": "100081", "Plant": "BR01", "Version": "00", "AIForecastCases": f["ai_egg_forecast"]})))
        for a in inv["actions"]:
            if a["kind"] == "prebuild":
                recs.append(dict(key=f"rec-pre-{a['sku']}", type="Supply", tone="info", market="BR", title=f"Pre-build {C.SKUS[a['sku']]['name']} at DC Manaus ({num(a['qty'])} cs)",
                                 metric="Lost sales avoided", metric_value=usd(a["value"]), confidence=0.74, owner="Supply planner BR",
                                 writeback=dict(title=f"STO (UB) · CAJ → MAO · {num(a['qty'])} cs", tcode="ME21N", api="API_PURCHASEORDER_PROCESS_SRV", approver="Supply planner BR", doc_prefix="45",
                                                preview=sto_payload("BR1D", "BR3D", a["sku"], a["qty"], 11))))
        done = {q.get("key") for q in STATE.queue + STATE.done}
        for r in recs:
            r["status"] = "approved" if r["key"] in done else "pending"
        return recs

    def approve_rec(self, key: str) -> dict | None:
        rec = next((r for r in self.recommendations() if r["key"] == key), None)
        if not rec:
            return None
        wb = rec["writeback"]
        return STATE.enqueue(dict(key=key, title=wb["title"], tcode=wb["tcode"], api=wb["api"], approver=wb["approver"], doc_prefix=wb["doc_prefix"],
                                  preview=wb["preview"], market=rec["market"], type=rec["type"]))

    def total_value(self) -> float:
        return sum(s_["value"] for s_ in self.signals())


def sto_payload(src: str, dst: str, sku: str, qty: int, day: int) -> dict:
    return {"PurchaseOrderType": "UB", "CompanyCode": C.DCS[dst]["country"] + "10", "PurchasingOrganization": C.DCS[dst]["country"] + "10",
            "SupplyingPlant": src, "to_PurchaseOrderItem": [{"Material": sku, "Plant": dst, "OrderQuantity": str(qty), "PurchaseOrderQuantityUnit": "CS",
                                                            "ScheduleLineDeliveryDate": (pd.Timestamp(today()) + pd.Timedelta(days=day)).strftime("%Y-%m-%d")}]}


def signal_text(s: dict) -> str:
    f = s["facts"]
    i = s["id"]
    if i == "pricing":
        return (f"{f['competitor_product']} is down {f['competitor_cut'].lstrip('−')} ({f['competitor_price']}) at {f['customer']}. "
                f"Our price index moved {f['price_index']} and {f['our_product']} sell-out is {f['sellout_impact']}.")
    if i == "stockout":
        return (f"{f['product']} at {f['dc']} is projected to stock out on {f['projected_stockout']} ({f['stockout_probability']} probability). "
                f"Fix: {f['fix']}; {f['donor_cover']} of cover available.")
    if i == "route":
        return (f"Landslide at {f['location']}; reopening in {f['reopening']}. The original plan delivers {f['on_time_original']} on time "
                f"({f['sales_at_risk_original']} at risk); the re-optimized plan reaches {f['on_time_ai']}.")
    if i == "pascoa":
        return (f"Key-account pre-orders are {f['preorders_vs_last_year']} vs last year. The AI forecast for Easter eggs is {f['ai_egg_forecast']} "
                f"({f['vs_last_season']} vs last season) at plant {f['plant']}, where line utilisation reaches {f['line_utilization_feb']} in February.")
    if i == "ar_price":
        return (f"Our price index vs the category has drifted to {f['our_price_index_vs_category']}. The indexation model recommends "
                f"{f['recommended_increase']} list from {f['effective']}, worth {f['gp_per_month']} gross profit per month.")
    if i == "heat":
        return f"{f['temperatures']}. Northern demand {f['demand_impact_2_weeks']} for 2 weeks; {f['lanes_needing_reefer']} need {f['dispatch_window']}."
    if i == "river":
        return f"Barge capacity {f['barge_capacity']} and inbound {f['inbound_delay']}. Pre-build {f['prebuild']} via {f['route']}."
    if i == "cocoa":
        return f"Cocoa {f['cocoa_move']} lifts Mexico COGS {f['cogs_impact_mx']}; holding margin needs about {f['price_needed_mx']} price. {f['approach']}."
    if i == "strike":
        return f"Blockades for {f['duration']} around {f['dcs_affected']}: inbound {f['inbound_delay']}, OTIF {f['otif_impact']}."
    if i == "markdown":
        return f"{f['quantity']} expire in {f['days_to_expiry']} at DC {f['dcs']}. Recovery: {f['recovery']}."
    return ""


HUB: Hub | None = None
_hub_lock = threading.Lock()


def hub() -> Hub:
    global HUB
    with _hub_lock:
        if HUB is None:
            HUB = Hub()
    return HUB
