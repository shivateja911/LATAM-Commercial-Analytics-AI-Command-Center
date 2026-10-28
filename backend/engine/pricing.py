"""Revenue growth management: price elasticity, promo simulation and a guardrailed optimizer.

Elasticities are re-estimated from POS: a log-log regression per region × channel × SKU with event, weather and
trend controls, then shrunk toward the channel mean (empirical Bayes).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import catalog as C
from ..datagen import HIST
from ..store import store

LADDER_MX = [39.90, 38.90, 37.90, 36.90, 35.90, 34.90, 33.90, 32.90, 31.90]
HERO = dict(region="MX-CDMX", channel="MT", sku="100045", customer="Hiper Nacional", market="MX")
SIM = dict(carry=1.6, decay=0.85, pantry=0.3, display_lift=1.06, display_cost=0.085, horizon=8, comp_weeks=3)
RETAILER_MARGIN = 0.28
TRADE_BUDGET_LEFT = 4.2e6   # MXN, Q4 Mexico modern trade
HEDGE = dict(MX=0.55, BR=0.60, CO=0.50, PE=0.45, CL=0.55, AR=0.40, CA=0.50)
BUDGET_COCOA = 128.0


class Elasticities:
    def __init__(self):
        pos = store().table("POS_WEEKLY")
        pos = pos[pos.COMP_PRICE_LC.notna() & (pos.UNITS > 0)].copy()
        self.raw, rows = {}, []
        weeks = store().table("WEEKS").iloc[:HIST]
        ev_by_market = {m: pd.DataFrame([C.event_intensity(m, int(y), int(w)) for y, w in zip(weeks.iso_year, weeks.iso_week)],
                                        index=pd.to_datetime(weeks.week_start)).reindex(columns=list(C.EVENT_LABELS)).fillna(0.0)
                        for m in C.MARKETS}
        for (r, ch, sku), g in pos.groupby(["REGION", "CHANNEL", "MATNR"]):
            g = g.sort_values("WEEK_START")
            m = C.REGIONS[r]["country"]
            ev = ev_by_market[m].loc[g.WEEK_START].values
            X = np.column_stack([np.ones(len(g)), np.log(g.SHELF_PRICE_LC / g.CAT_INDEX), np.log(g.COMP_PRICE_LC / g.CAT_INDEX),
                                 np.maximum(0, g.TEMP_C - 28), np.arange(len(g)) / 52.0, ev[:, ev.any(axis=0)]])
            y = np.log(g.UNITS.values)
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
            s2 = resid @ resid / max(len(y) - X.shape[1], 1)
            cov = s2 * np.linalg.pinv(X.T @ X)
            self.raw[(r, ch, sku)] = (beta[1], beta[2], np.sqrt(cov[1, 1]), np.sqrt(cov[2, 2]))
            rows.append(dict(region=r, channel=ch, sku=sku, e=beta[1], c=beta[2], se_e=np.sqrt(cov[1, 1]), se_c=np.sqrt(cov[2, 2])))
        df = pd.DataFrame(rows)
        self.post = {}
        for ch, g in df.groupby("channel"):
            mu_e, mu_c = g.e.mean(), g.c.mean()
            tau_e = max(g.e.var() - (g.se_e ** 2).mean(), 0.01)
            tau_c = max(g.c.var() - (g.se_c ** 2).mean(), 0.01)
            for r in g.itertuples():
                we = (1 / r.se_e ** 2) / (1 / r.se_e ** 2 + 1 / tau_e)
                wc = (1 / r.se_c ** 2) / (1 / r.se_c ** 2 + 1 / tau_c)
                self.post[(r.region, ch, r.sku)] = (we * r.e + (1 - we) * mu_e, wc * r.c + (1 - wc) * mu_c)
        self.channel_mean = df.groupby("channel")[["e", "c"]].mean().to_dict("index")

    def get(self, region: str, channel: str, sku: str) -> tuple[float, float]:
        if (region, channel, sku) in self.post:
            return self.post[(region, channel, sku)]
        cm = self.channel_mean.get(channel, dict(e=-1.5, c=0.5))
        return cm["e"], cm["c"]


class Pricing:
    def __init__(self):
        self.el = Elasticities()
        pos = store().table("POS_WEEKLY")
        self.pos = pos
        h = pos[(pos.REGION == HERO["region"]) & (pos.CHANNEL == HERO["channel"]) & (pos.MATNR == HERO["sku"])].sort_values("WEEK_START")
        self.hero_hist = h
        cur = h.iloc[-1]
        self.P0 = float(cur.LIST_PRICE_LC)
        self.comp_regular = float(cur.COMP_LIST_LC)
        self.comp_now = float(cur.COMP_PRICE_LC)
        self.comp_cut = 1 - self.comp_now / self.comp_regular
        prev = h.iloc[-5:-1]
        self.comp_prev_price = float(prev.COMP_PRICE_LC.mean())
        clean = h[(h.PROMO_DEPTH == 0) & (h.COMP_PRICE_LC >= h.COMP_LIST_LC * 0.999)].tail(10)
        self.U0 = float(clean.UNITS.median())
        fx = C.MARKETS["MX"]["fx"]
        self.M0 = self.P0 * (1 - RETAILER_MARGIN) - C.SKUS[HERO["sku"]]["cogs"] * fx
        self.e, self.c = self.el.get(HERO["region"], HERO["channel"], HERO["sku"])
        self.wow = float(h.iloc[-1].UNITS / h.iloc[-2].UNITS - 1)

    # --------------------------------------------------------------- simulation
    def sim(self, d: float, w: int, display: bool, cc: float) -> dict:
        S = SIM
        compF = (1 - cc) ** self.c
        gp = units = vs = 0.0
        prev, promo_units = 1.0, 0.0
        for i in range(1, S["horizon"] + 1):
            mg = self.M0
            if i <= w:
                vf = (1 - d) ** self.e * (compF if i <= S["comp_weeks"] else 1) * (S["display_lift"] if display else 1)
                mg = self.M0 - d * self.P0
                promo_units += self.U0 * vf
            elif i <= S["comp_weeks"]:
                vf = compF
            else:
                loss = max(0.0, 1 - vs / S["comp_weeks"]) * S["carry"] * S["decay"] ** (i - S["comp_weeks"] - 1)
                dip = S["pantry"] * max(0.0, prev - 1) if i == max(w, S["comp_weeks"]) + 1 else 0.0
                vf = max(0.3, 1 - loss - dip)
            if i <= S["comp_weeks"]:
                vs += vf
            prev = vf
            units += self.U0 * vf
            gp += self.U0 * vf * mg
        disp_cost = S["display_cost"] * self.U0 * self.M0 * w if display else 0.0
        dgp = gp - self.U0 * self.M0 * S["horizon"] - disp_cost
        price = self.P0 * (1 - d)
        comp_price = self.comp_regular * (1 - cc)
        return dict(depth=d, weeks=w, display=display, price=price, index=price / comp_price * 100, vol=units / (self.U0 * S["horizon"]) - 1,
                    dgp=dgp, spend=d * self.P0 * promo_units + disp_cost)

    def guardrails(self, r: dict) -> list[dict]:
        max_depth = 0.4 * self.M0 / self.P0
        on_ladder = any(abs(r["price"] - p) < 0.011 for p in LADDER_MX)
        return [
            dict(ok="ok" if r["depth"] <= max_depth + 1e-9 else "x", name="Promo margin floor", detail=f"{r['depth'] * 100:.0f}% vs {max_depth * 100:.1f}% max depth"),
            dict(ok="ok" if 95 <= r["index"] <= 105 else "x", name="Price index band", detail=f"{r['index']:.0f} vs band 95–105"),
            dict(ok="ok" if on_ladder else "w", name="Approved price point", detail=f"MXN {r['price']:.2f}" + (" on ladder" if on_ladder else " not on ladder")),
            dict(ok="ok" if r["spend"] <= TRADE_BUDGET_LEFT else "x", name="Trade budget", detail=f"MXN {r['spend'] / 1e6:.2f}M of {TRADE_BUDGET_LEFT / 1e6:.1f}M Q4 remaining"),
            dict(ok="w", name="Customer agreement", detail=f"{HERO['customer']} needs a 48 h exception (KAM)") if r["depth"] > 0 else dict(ok="ok", name="Customer agreement", detail="no change"),
            dict(ok="ok", name="Regulatory", detail="NOM-051 labels unaffected; no kids-targeted claims"),
        ]

    def options(self, cc: float) -> dict:
        hold = self.sim(0.0, 0, False, cc)
        match = self.sim(round(cc, 3), 3, False, cc)
        best = None
        for p in LADDER_MX:
            d = round(1 - p / self.P0, 4)
            for w in range(1, 7):
                for disp in (False, True):
                    r = self.sim(d, w, disp, cc)
                    if all(g["ok"] != "x" for g in self.guardrails(r)) and (best is None or r["dgp"] > best["dgp"]):
                        best = r
        for r in (hold, match, best):
            r["roi"] = None if r["spend"] <= 0 else (r["dgp"] - hold["dgp"]) / r["spend"]
            r["share_pp"] = r["vol"] * 10
            r["guardrails"] = self.guardrails(r)
        return dict(hold=hold, match=match, ai=best)

    def curve(self, w: int, display: bool, cc: float) -> list[float]:
        return [self.sim(x / 100, w, display, cc)["dgp"] for x in range(0, 21)]

    # --------------------------------------------------------------- screen payload
    def payload(self, scenarios: tuple) -> dict:
        cc = 0.18 if "comp_deeper" in scenarios else self.comp_cut
        opts = self.options(cc)
        ai, hold = opts["ai"], opts["hold"]
        comp_price_now = self.comp_regular * (1 - cc)
        impact = (1 - cc) ** self.c - 1
        drivers = [
            ("Competitor price gap (index %.0f)" % hold["index"], min(0.6, (hold["index"] - 100) / 20)),
            ("Promo elasticity (%.1f)" % self.e, min(0.5, (abs(self.e) - 1) / 5)),
            ("Día de Muertos seasonality", 0.14),
            ("Post-promo dip / pantry load", -SIM["pantry"] * ai["depth"] * 3),
            ("Promo margin floor (≤ %.1f%%)" % (40 * self.M0 / self.P0), -0.18 * ai["depth"] / max(0.4 * self.M0 / self.P0, 0.01) - 0.05),
        ]
        return dict(
            hero=dict(HERO, sku_name=C.SKUS[HERO["sku"]]["name"], comp_product=C.COMP_PRODUCT[HERO["sku"]], region_name=C.REGIONS[HERO["region"]]["name"]),
            alert=dict(comp_regular=self.comp_regular, comp_now=comp_price_now, cut=cc, our_price=self.P0,
                       index_before=self.P0 / self.comp_prev_price * 100, index_now=hold["index"], impact=impact, wow=self.wow),
            elasticity=dict(own=self.e, cross=self.c, U0=self.U0, M0=self.M0),
            options=opts, drivers=[dict(label=l, value=round(v, 2)) for l, v in drivers],
            ppa=self.ppa(), calendar=self.calendar(ai), cocoa=self.cocoa(scenarios),
        )

    def ppa(self) -> list[dict]:
        cur = self.pos[(self.pos.COUNTRY == "MX") & (self.pos.WEEK_START == self.pos.WEEK_START.max())]
        rows = []
        spec = [("100012", "TT", "coin"), ("100041", "TT", "up"), ("100045", "MT", "tpr"), ("100058", "MT", "supply"), ("100061", "MT", "up"), ("100031", "CONV", "up")]
        fx = C.MARKETS["MX"]["fx"]
        for sku, ch, kind in spec:
            g = cur[(cur.MATNR == sku) & (cur.CHANNEL == ch)]
            price = float(g.LIST_PRICE_LC.iloc[0]) if len(g) else float("nan")
            e, _ = self.el.get("MX-CDMX", ch, sku)
            net, cogs = price * (1 - RETAILER_MARGIN), C.SKUS[sku]["cogs"] * fx
            step = 1.0 if price < 30 else round(price * 0.05, 0)
            new = price + step
            vol = (new / price) ** e - 1
            gp = ((1 + vol) * (new * (1 - RETAILER_MARGIN) - cogs)) / (net - cogs) - 1
            if kind == "coin":
                rec, note, tone = f"Hold ${price:.0f}", f"coin price point; +$1 = vol {vol * 100:+.0f}% (e {e:.1f})", "pos"
            elif kind == "tpr":
                rec, note, tone = "TPR (AI)", "see response options", "ai"
            elif kind == "supply":
                rec, note, tone = "Hold", "supply-constrained at DC CDMX", "pos"
            elif gp > 0.01:
                rec, note, tone = f"${new:.2f}".replace(".00", ""), f"GP {gp * 100:+.1f}%, vol {vol * 100:+.1f}% (e {e:.1f})", "gold"
            else:
                rec, note, tone = "Hold", f"+{step:.0f} would cut GP {gp * 100:.1f}% (e {e:.1f})", "pos"
            rows.append(dict(sku=C.SKUS[sku]["name"], channel=C.CHANNELS[ch], price=price, rec=rec, note=note, tone=tone, elasticity=round(e, 2)))
        rows.insert(1, dict(sku="Rayo Doble 20g (new)", channel=C.CHANNELS["TT"], price=None, rec="Launch $15", note="trade-up path above the $10 coin point", tone="ai", elasticity=None))
        return rows

    def calendar(self, ai: dict) -> list[dict]:
        plan = store().table("PROMO_PLAN_MX")
        out = []
        for r in plan.itertuples():
            row = dict(name=r.PROMO, start=int(r.START_WEEK), weeks=int(r.WEEKS), roi=None if pd.isna(r.ROI) else float(r.ROI), status=r.STATUS)
            if r.STATUS == "ai_draft":
                row.update(name=f"Dulcera Milk 90g · TPR −{ai['depth'] * 100:.0f}% (AI draft)", weeks=ai["weeks"], roi=ai["roi"])
            out.append(row)
        return out

    def cocoa(self, scenarios: tuple) -> dict:
        idx = store().table("COCOA")
        shock = 0.08 if "cocoa_up" in scenarios else 0.0
        now = float(idx.INDEX.iloc[-1]) * (1 + shock)
        rows = []
        for m in ("MX", "BR", "CO", "PE", "CL", "AR", "CA"):
            cogs_d = (now / BUDGET_COCOA - 1) * C.COCOA_SHARE_OF_COGS * (1 - HEDGE[m])
            price_d = cogs_d * 0.57 * (1.15 if m == "CO" else 1.0)
            ch = C.MARKETS[m]["channels"]
            e = sum(self.el.channel_mean.get(c, dict(e=-1.5))["e"] * s for c, s in ch.items())
            how = dict(MX="PPA first, list on 90g+", BR="list in Jan, before Páscoa", CO="list (health tax in base)", PE="list + shallower promos",
                       CL="list in Q1", AR="fold into biweekly indexation", CA="USD list in Q1")[m]
            rows.append(dict(market=m, cogs=cogs_d, price=price_d, vol=price_d * e * 0.6, how=how))
        series = list(idx.INDEX.values[:-1]) + [now]
        return dict(series=[round(float(v), 1) for v in series], months=[d.strftime("%b %y") for d in idx.MONTH], shock=shock, rows=rows)
