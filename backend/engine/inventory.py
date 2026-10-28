"""Localized inventory: projected stock, Monte-Carlo stock-out risk, AI rebalancing and the MD04 overlay."""
from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pandas as pd

from .. import catalog as C
from ..config import today
from ..store import store
from .forecast import Forecaster

DAYS = 21
HERO = ("MX1D", "100058")
MATRIX_SKUS = ["100045", "100041", "100012", "100031", "100061", "100071", "100058", "100051"]


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class Inventory:
    def __init__(self, fc: Forecaster):
        self.fc = fc
        s = store()
        self.mard = s.table("MARD").set_index(["WERKS", "MATNR"])
        self.marc = s.table("MARC").set_index(["WERKS", "MATNR"])
        self.plaf = s.table("PLAF")
        self.vbap = s.table("VBAP_OPEN")
        self.mchb = s.table("MCHB")
        self.pbed = s.table("PBED")
        self.t0 = pd.Timestamp(today())
        self.rng_seed = 11

    # ---------------------------------------------------------------- core projection
    def _receipts(self, dc, sku, scenarios) -> np.ndarray:
        r = np.zeros(DAYS + 1)
        rows = self.plaf[(self.plaf.WERKS == dc) & (self.plaf.MATNR == sku)]
        delay = 7 if ("rionegro_br" in scenarios and dc == "BR3D") else (2 if ("strike_br" in scenarios and dc in ("BR2D", "BR4D")) else 0)
        for x in rows.itertuples():
            d = (x.PSTTR - self.t0).days + delay
            if 1 <= d <= DAYS:
                r[d] += x.GSMNG
        return r

    def _project(self, stock, dem, rec) -> np.ndarray:
        out, s = np.zeros(DAYS + 1), stock
        out[0] = s
        for d in range(1, DAYS + 1):
            s = s + rec[d] - dem[d - 1]
            out[d] = s
        return out

    def _lost(self, stock, dem, rec) -> float:
        s, lost = stock, 0.0
        for d in range(1, DAYS + 1):
            s += rec[d]
            served = min(max(s, 0.0), dem[d - 1])
            lost += dem[d - 1] - served
            s -= served
        return lost

    def compute(self, scenarios: tuple) -> dict:
        rng = np.random.default_rng(self.rng_seed)
        series = {}
        for (dc, sku), row in self.mard.iterrows():
            if (dc, sku) not in self.fc.idx:
                continue
            i = self.fc.idx[(dc, sku)]
            dem, sig = self.fc.daily_demand(i, DAYS)
            rec = self._receipts(dc, sku, scenarios)
            stock = float(row.LABST)
            proj = self._project(stock, dem, rec)
            ss = float(self.marc.loc[(dc, sku)].EISBE)
            # Monte-Carlo: weekly demand shocks (lognormal), shared across the days of a week
            n = 600
            wk = np.minimum((np.arange(1, DAYS + 1) + 1) // 7, 3)
            shocks = np.exp(rng.normal(0, 1, (n, 4)) * sig[[min(7 * k, DAYS - 1) for k in range(4)]] - sig[[min(7 * k, DAYS - 1) for k in range(4)]] ** 2 / 2)
            sims = stock + np.cumsum(rec[1:] - dem[None, :] * shocks[:, wk], axis=1)
            p14 = min(float((sims[:, :14] < 0).any(axis=1).mean()), 0.99)
            mean14 = dem[:14].mean()
            sd = C.SKUS[sku]
            series[(dc, sku)] = dict(dc=dc, sku=sku, i=i, stock=stock, ss=ss, dem=dem, rec=rec, proj=proj, p14=p14,
                                     dos=stock / mean14 if mean14 > 0 else 999.0, case_usd=sd["upc"] * sd["price"], case_cost=sd["upc"] * sd["cogs"],
                                     stockout_day=next((d for d in range(1, DAYS + 1) if proj[d] < 0), None),
                                     lost=self._lost(stock, dem, rec), seasonal=sd.get("seasonal", ""))
        actions = self._actions(series, scenarios)
        return dict(series=series, actions=actions)

    # ---------------------------------------------------------------- actions
    def _actions(self, S: dict, scenarios: tuple) -> list[dict]:
        acts = []
        for key, s in sorted(S.items(), key=lambda kv: -kv[1]["p14"]):
            dc, sku = key
            if s["p14"] < 0.45 or s["seasonal"] or (dc == "BR3D" and "rionegro_br" in scenarios):
                continue
            plan = self._fix(S, s)
            if plan:
                acts.append(plan)
        if "rionegro_br" in scenarios:
            for sku in ("100045", "100012", "100041"):
                s = S.get(("BR3D", sku))
                if not s:
                    continue
                qty = int(math.ceil(s["dem"][:21].sum() / 10) * 10)
                acts.append(dict(kind="prebuild", dc="BR3D", sku=sku, donor="BR1D", qty=qty, lead=11,
                                 title=f"STO · CAJ → MAO", detail=f"{C.SKUS[sku]['name']} · {qty:,} cs · road to Porto Velho, then Madeira barge (11 d)",
                                 why="Rio Negro low water: barge capacity −35%, inbound +7 days", value=qty * s["case_usd"] * 0.5,
                                 risk_before=s["p14"], risk_after=0.08, owner="Supply planner BR"))
        for b in self._markdowns(S):
            acts.append(b)
        acts.sort(key=lambda a: -a["value"])
        return acts

    def _fix(self, S: dict, s: dict) -> dict | None:
        dc, sku = s["dc"], s["sku"]
        country = C.DCS[dc]["country"]
        need = float(np.max(s["ss"] - s["proj"][1:15]))
        if need <= 0:
            return None
        donors = []
        for (d2, k2), o in S.items():
            if k2 != sku or d2 == dc or C.DCS[d2]["country"] != country or o["dos"] < 40:
                continue
            spare = o["stock"] - (o["ss"] + o["dem"][:21].sum() * 0.8)
            if spare > 0:
                dist = km((C.DCS[dc]["lat"], C.DCS[dc]["lon"]), (C.DCS[d2]["lat"], C.DCS[d2]["lon"]))
                donors.append((o["dos"], d2, spare, 1 if dist < 700 else 2, dist))
        donors.sort(reverse=True)
        rec = s["rec"].copy()
        steps, sto = [], None
        if donors:
            _, d2, spare, lead, dist = donors[0]
            qty = int(min(math.ceil(need / 10) * 10, math.floor(spare / 10) * 10))
            if qty > 0:
                rec[lead + 1] += qty
                sto = dict(donor=d2, qty=qty, day=lead + 1, km=round(dist))
                steps.append(f"STO {qty:,} cs from DC {C.DCS[d2]['code']}")
        proj = self._project(s["stock"], s["dem"], rec)
        pull = None
        if (proj[1:15] < s["ss"]).any():
            rows = self.plaf[(self.plaf.WERKS == dc) & (self.plaf.MATNR == sku) & (self.plaf.TYPE == "PlOrd")]
            for x in rows.sort_values("PSTTR").itertuples():
                d = (x.PSTTR - self.t0).days
                if 3 <= d <= 10:
                    nd = max(2, d - 3)
                    rec[d] -= x.GSMNG
                    rec[nd] += x.GSMNG
                    pull = dict(plnum=x.PLNUM, qty=int(x.GSMNG), from_day=d, to_day=nd, plant=x.PLWRK)
                    steps.append(f"pull in planned order {x.PLNUM.lstrip('0')} by {d - nd} days")
                    break
        proj = self._project(s["stock"], s["dem"], rec)
        extra = None
        if (proj[1:DAYS + 1] < s["ss"]).any():
            short = float(np.max(s["ss"] - proj[1:]))
            d_first = int(np.argmax(proj[1:] < s["ss"])) + 1
            day = max(d_first - 1, (pull["to_day"] + 3) if pull else 6)
            qty = int(math.ceil(short / 10) * 10)
            if day <= DAYS:
                rec[day] += qty
                extra = dict(qty=qty, day=day)
                steps.append(f"add {qty:,} cs production / PIR")
        proj = self._project(s["stock"], s["dem"], rec)
        if not steps:
            return None
        lost_after = self._lost(s["stock"], s["dem"], rec)
        title = f"STO · {C.DCS[sto['donor']]['code']} → {C.DCS[dc]['code']}" if sto else f"Supply fix · DC {C.DCS[dc]['code']}"
        return dict(kind="rebalance", dc=dc, sku=sku, title=title, sto=sto, pull=pull, extra=extra, rec_plan=rec, proj_plan=proj,
                    detail=f"{C.SKUS[sku]['name']} · " + "; ".join(steps),
                    why=f"Stock-out risk {s['p14'] * 100:.0f}% within 14 days" + (f" (projected day {s['stockout_day']})" if s["stockout_day"] else ""),
                    value=max(s["lost"] - lost_after, 0) * s["case_usd"], risk_before=s["p14"], risk_after=0.06,
                    owner=f"Supply planner {C.DCS[dc]['country']}")

    def _markdowns(self, S: dict) -> list[dict]:
        """Short-life batches that will not sell through before expiry, grouped per SKU."""
        lim = self.t0 + timedelta(days=60)
        b = self.mchb[self.mchb.VFDAT <= lim]
        per_sku: dict[str, dict] = {}
        for (dc, sku), g in b.groupby(["WERKS", "MATNR"]):
            s = S.get((dc, sku))
            if not s:
                continue
            days_left = int((g.VFDAT.min() - self.t0).days)
            sellable = s["dem"][:min(days_left, DAYS)].sum() * (days_left / DAYS if days_left > DAYS else 1)
            leftover = max(0.0, float(g.CLABS.sum()) - sellable * (g.CLABS.sum() / max(s["stock"], 1)))
            if leftover < 300:
                continue
            agg = per_sku.setdefault(sku, dict(qty=0.0, dcs=[], days_left=days_left, cost=s["case_cost"]))
            agg["qty"] += leftover
            agg["dcs"].append(C.DCS[dc]["code"])
            agg["days_left"] = min(agg["days_left"], days_left)
        out = []
        for sku, a in per_sku.items():
            qty = int(round(a["qty"], -1))
            country = C.DCS[next(d for d in C.DCS if C.DCS[d]["code"] == a["dcs"][0])]["country"]
            out.append(dict(kind="markdown", dc=",".join(a["dcs"]), sku=sku, qty=qty, days_left=a["days_left"],
                            title=f"Markdown · {C.SKUS[sku]['name']}", detail=f"{qty:,} cs across DC {', '.join(a['dcs'])} · {a['days_left']} d to expiry",
                            why="Hard-discount bundles before Buen Fin · 71% value recovery vs 18% write-off", value=qty * a["cost"] * (0.71 - 0.18),
                            risk_before=None, risk_after=None, owner="RGM Mexico" if country == "MX" else "RGM"))
        return out

    # ---------------------------------------------------------------- payloads
    def payload(self, res: dict, scenarios: tuple) -> dict:
        S, A = res["series"], res["actions"]
        inv_value = sum(s["stock"] * s["case_cost"] for s in S.values())
        dem14 = sum(s["dem"][:14].sum() for s in S.values())
        stock_total = sum(s["stock"] for s in S.values())
        lost14 = sum(self._lost(s["stock"], s["dem"][:14].tolist() + [0] * (DAYS - 14), s["rec"]) for s in S.values())
        at_risk = [s for s in S.values() if s["p14"] >= 0.3 and not s["seasonal"]]
        crit = [s for s in at_risk if s["p14"] >= 0.6]
        short_life = self.mchb[self.mchb.VFDAT <= self.t0 + timedelta(days=60)]
        short_val = sum(r.CLABS * C.SKUS[r.MATNR]["upc"] * C.SKUS[r.MATNR]["cogs"] for r in short_life.itertuples())
        kpis = dict(dos=stock_total / (dem14 / 14), at_risk=len(at_risk), critical=len(crit), short_life_usd=short_val,
                    fill=1 - lost14 / dem14, inv_value=inv_value, ss_release=self.fc.safety_stock_release_usd())
        matrix = dict(dcs=list(C.DCS), codes=[C.DCS[d]["code"] for d in C.DCS], skus=[C.SKUS[k]["name"].replace("Dulcera Milk", "Dulcera").replace(" 70% 100g", " 70%") for k in MATRIX_SKUS],
                      values=[[round(S[(d, k)]["dos"]) if (d, k) in S else None for k in MATRIX_SKUS] for d in C.DCS],
                      risk=[[round(S[(d, k)]["p14"], 2) if (d, k) in S else None for k in MATRIX_SKUS] for d in C.DCS])
        hero = S[HERO]
        plan = next((a for a in A if a.get("dc") == HERO[0] and a.get("sku") == HERO[1] and a["kind"] == "rebalance"), None)
        dates = [(self.t0 + timedelta(days=d)).strftime("%-d %b") for d in range(DAYS + 1)]
        markers = []
        if plan:
            if plan["sto"]:
                markers.append(dict(i=plan["sto"]["day"], label=f"STO +{plan['sto']['qty']:,}"))
            if plan["pull"]:
                markers.append(dict(i=plan["pull"]["to_day"], label=f"Pull-in +{plan['pull']['qty']:,}"))
            if plan["extra"]:
                markers.append(dict(i=plan["extra"]["day"], label=f"+{plan['extra']['qty']:,} prod."))
        proj = dict(dates=dates, asis=[round(v) for v in hero["proj"]], plan=[round(v) for v in (plan["proj_plan"] if plan else hero["proj"])],
                    ss=hero["ss"], markers=markers, sku=C.SKUS[HERO[1]]["name"], dc=C.DCS[HERO[0]]["name"],
                    p14=hero["p14"], stockout_day=dates[hero["stockout_day"]] if hero["stockout_day"] else None)
        buckets = [("< 30 days", 0, 30), ("30–60 days", 30, 60), ("60–90 days", 60, 90), ("90–180 days", 90, 180), ("> 180 days", 180, 9999)]
        aging = []
        for label, lo, hi in buckets:
            g = self.mchb[(self.mchb.VFDAT > self.t0 + timedelta(days=lo)) & (self.mchb.VFDAT <= self.t0 + timedelta(days=hi))]
            aging.append(dict(label=label, usd=float(sum(r.CLABS * C.SKUS[r.MATNR]["upc"] * C.SKUS[r.MATNR]["cogs"] for r in g.itertuples()))))
        acts = [self.action_view(a) for a in A[:6]]
        return dict(kpis=kpis, matrix=matrix, actions=acts, projection=proj, aging=aging)

    @staticmethod
    def action_view(a: dict) -> dict:
        return {k: (float(v) if isinstance(v, (np.floating,)) else v) for k, v in a.items() if k not in ("rec_plan", "proj_plan")}

    def md04(self, res: dict, dc: str = HERO[0], sku: str = HERO[1]) -> dict:
        s = res["series"][(dc, sku)]
        plan = next((a for a in res["actions"] if a.get("dc") == dc and a.get("sku") == sku and a["kind"] == "rebalance"), None)
        rows = [dict(date=self.t0, el="Stock", data="", qty=s["stock"], ai_qty=s["stock"], kind="sap")]
        orders = self.vbap[(self.vbap.WERKS == dc) & (self.vbap.MATNR == sku)]
        ord_by_week = {}
        for o in orders.itertuples():
            rows.append(dict(date=o.EDATU, el="CusOrd", data=f"{o.VBELN}/{o.POSNR[-2:]}", qty=-o.KWMENG, ai_qty=-o.KWMENG, kind="sap"))
            wk = o.EDATU.isocalendar()[1]
            ord_by_week[wk] = ord_by_week.get(wk, 0) + o.KWMENG
        pir = self.pbed[(self.pbed.WERKS == dc) & (self.pbed.MATNR == sku)].sort_values("PDATU").head(3)
        dem = s["dem"]
        for k, p in enumerate(pir.itertuples()):
            wk = p.ISO_WEEK
            start = self.t0 + timedelta(days=1) if k == 0 else p.PDATU
            if start > self.t0 + timedelta(days=DAYS):
                break
            frac = 5 / 7 if k == 0 else 1.0
            pir_rem = max(p.PLNMG * frac - ord_by_week.get(wk, 0), 0)
            d0 = (start - self.t0).days
            ai_week = dem[d0 - 1:min(d0 - 1 + (5 if k == 0 else 7), DAYS)].sum()
            ai_rem = max(ai_week - ord_by_week.get(wk, 0), 0)
            note = f"AI demand {ai_week:,.0f} cs vs PIR {p.PLNMG * frac:,.0f} ({(ai_week / max(p.PLNMG * frac, 1) - 1) * 100:+.0f}%)"
            rows.append(dict(date=start, el="IndReq", data=f"VSF · PIR W{wk}", qty=-round(pir_rem), ai_qty=-round(ai_rem), kind="sap", note=note))
        rec_rows = self.plaf[(self.plaf.WERKS == dc) & (self.plaf.MATNR == sku)].sort_values("PSTTR")
        for r in rec_rows.itertuples():
            if (r.PSTTR - self.t0).days > DAYS:
                continue
            moved = plan and plan["pull"] and plan["pull"]["plnum"] == r.PLNUM
            rows.append(dict(date=r.PSTTR, el=r.TYPE, data=f"{r.PLNUM} · {r.PLWRK}", qty=r.GSMNG, ai_qty=0 if moved else r.GSMNG, kind="sap",
                             note="moved by AI pull-in" if moved else ""))
        if plan:
            if plan["sto"]:
                rows.append(dict(date=self.t0 + timedelta(days=plan["sto"]["day"]), el="POitem", data=f"STO from {plan['sto']['donor']} (draft)",
                                 qty=0, ai_qty=plan["sto"]["qty"], kind="ai", note=f"AI draft · uses excess at DC {C.DCS[plan['sto']['donor']]['code']}"))
            if plan["pull"]:
                rows.append(dict(date=self.t0 + timedelta(days=plan["pull"]["to_day"]), el="PlOrd", data=f"{plan['pull']['plnum']} · pulled in",
                                 qty=0, ai_qty=plan["pull"]["qty"], kind="ai", note=f"AI pull-in −{plan['pull']['from_day'] - plan['pull']['to_day']} d · line {plan['pull']['plant']}-L2 at 82%"))
            if plan["extra"]:
                rows.append(dict(date=self.t0 + timedelta(days=plan["extra"]["day"]), el="PlOrd", data="AI proposal · additional",
                                 qty=0, ai_qty=plan["extra"]["qty"], kind="ai", note="AI add · covers demand the PIRs miss"))
        rows.sort(key=lambda r: (r["date"], 0 if r["el"] == "Stock" else 1))
        a = b = 0.0
        out = []
        for r in rows:
            a += r["qty"]
            b += r["ai_qty"]
            flag = "stockout" if a < 0 else ("below_ss" if a < s["ss"] else "")
            out.append(dict(date=r["date"].strftime("%d.%m.%Y"), el=r["el"], data=r["data"], qty=r["qty"], ai_qty=r["ai_qty"],
                            avail=round(a), avail_ai=round(b), kind=r["kind"], note=r.get("note", ""), flag=flag))
        return dict(sku=sku, sku_name=C.SKUS[sku]["name"], dc=dc, dc_name=C.DCS[dc]["name"], ss=s["ss"], mrp_type="PD", rows=out)
