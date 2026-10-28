"""Commercial KPIs for the Command Center and Market Pulse screens."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import catalog as C
from ..config import today
from ..store import store

OTIF_BASE = dict(MX=0.921, BR=0.902, CO=0.935, PE=0.886, CL=0.940, AR=0.899, CA=0.910)
TREND_IMPLICATION = {
    "zero_sugar": "Dulcera Zero is in only ~22% of traditional-trade stores. <b>Expand to 4,000 tiendas</b> in Bogotá &amp; CDMX.",
    "premium_dark": "Cacao Alto's premium position supports <b>Navidad gift packs</b>; keep MT pricing (elasticity is high).",
    "single_serve": "<b>Protect coin price points</b>; grow through grammage and trade-up packs, not price.",
    "gifting": "Páscoa 2027 pre-orders are early. <b>Lift egg production</b> at BR01.",
    "value_seeking": "<b>Discounter-specific packs</b> (multipacks) to avoid diluting MT price.",
    "protein": "Adjacency test: <b>Crunchita Protein</b> in convenience &amp; e-com.",
}


def _usd(df: pd.DataFrame, col="VALUE_LC") -> pd.Series:
    return df[col] / df["COUNTRY"].map({m: v["fx"] for m, v in C.MARKETS.items()})


class Commercial:
    def __init__(self):
        s = store()
        self.si = s.table("SELLIN_WEEKLY").merge(s.table("MARA")[["MATNR", "UNITS_PER_CS", "NTGEW_G", "COGS_USD"]], on="MATNR")
        self.si["TONNES"] = self.si.QTY_CS * self.si.UNITS_PER_CS * self.si.NTGEW_G / 1e6
        self.si["COGS"] = self.si.QTY_CS * self.si.UNITS_PER_CS * self.si.COGS_USD
        self.pos = s.table("POS_WEEKLY")
        self.share = s.table("POS_SHARE")
        self.share["USD"] = _usd(self.share)
        self.t0 = pd.Timestamp(today())
        cocoa = s.table("COCOA").set_index("MONTH")["INDEX"]
        self.cocoa = cocoa

    # ------------------------------------------------------------ helpers
    def _window(self, start: date, end: date) -> pd.DataFrame:
        """Sell-in apportioned to calendar days [start, end]."""
        si = self.si
        ws = si.WEEK_START
        we = ws + pd.Timedelta(days=6)
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        overlap = ((np.minimum(we, e) - np.maximum(ws, s)).dt.days + 1).clip(lower=0) / 7.0
        out = si.assign(f=overlap)
        out = out[out.f > 0]
        cocoa_adj = self._cogs_index(start)
        return out.assign(NET=out.NET_USD * out.f, VOL=out.TONNES * out.f, CG=out.COGS * out.f * cocoa_adj)

    def _cogs_index(self, d: date) -> float:
        """COGS moves with cocoa costs realised ~6 months later (hedging lag)."""
        lag = pd.Timestamp(d) - pd.DateOffset(months=6)
        lag = lag.replace(day=1)
        idx = self.cocoa.asof(lag) if lag >= self.cocoa.index.min() else self.cocoa.iloc[0]
        return 1 + C.COCOA_SHARE_OF_COGS * (idx / 128.0 - 1) * 0.6

    # ------------------------------------------------------------ overview
    def overview(self, scenarios: tuple, accuracy: dict) -> dict:
        t0 = today()
        start = t0.replace(day=1)
        py_s, py_e = start.replace(year=start.year - 1), t0.replace(year=t0.year - 1)
        cur, py = self._window(start, t0), self._window(py_s, py_e)
        cocoa_shock = 1 + (C.COCOA_SHARE_OF_COGS * 0.08 * 0.45 if "cocoa_up" in scenarios else 0)
        by = lambda df: df.groupby("COUNTRY")[["NET", "VOL", "CG"]].sum()
        c, p = by(cur), by(py)
        c["CG"] *= cocoa_shock
        last52 = self.share[self.share.WEEK_START > self.share.WEEK_START.max() - pd.Timedelta(weeks=52)]
        prev52 = self.share[(self.share.WEEK_START <= self.share.WEEK_START.max() - pd.Timedelta(weeks=52)) &
                            (self.share.WEEK_START > self.share.WEEK_START.max() - pd.Timedelta(weeks=104))]
        sh = lambda df: df[df.PLAYER == "Northstar"].groupby("COUNTRY").USD.sum() / df.groupby("COUNTRY").USD.sum()
        sh_now, sh_prev = sh(last52), sh(prev52)
        otif = dict(OTIF_BASE)
        if "huaico_pe" in scenarios:
            otif["PE"] -= 0.031
        if "strike_br" in scenarios:
            otif["BR"] -= 0.042
        if "rionegro_br" in scenarios:
            otif["BR"] -= 0.009
        rows = []
        for m, md in C.MARKETS.items():
            rev, rev_py = c.NET.get(m, 0), p.NET.get(m, 0)
            plan = rev_py * (1 + md["plan_growth"])
            rows.append(dict(code=m, name=md["name"], rev=rev, vs_py=rev / rev_py - 1, vs_plan=rev / plan, vol=c.VOL.get(m, 0),
                             share=float(sh_now.get(m, 0)), share_d=float(sh_now.get(m, 0) - sh_prev.get(m, 0)),
                             gm=1 - c.CG.get(m, 0) / rev, otif=otif[m], centroid=md["centroid"]))
        tot = lambda k, d: float(d[k].sum())
        rev, rev_py = tot("NET", c), tot("NET", p)
        plan = sum(p.NET.get(m, 0) * (1 + C.MARKETS[m]["plan_growth"]) for m in C.MARKETS)
        gm, gm_py = 1 - tot("CG", c) / rev, 1 - tot("CG", p) / rev_py
        share_now = float(last52[last52.PLAYER == "Northstar"].USD.sum() / last52.USD.sum())
        share_prev = float(prev52[prev52.PLAYER == "Northstar"].USD.sum() / prev52.USD.sum())
        w = {m: C.MARKETS[m]["share"] for m in C.MARKETS}
        otif_tot = sum(otif[m] * w[m] for m in C.MARKETS) / sum(w.values())
        weekly = self.si.groupby("WEEK_START")[["NET_USD", "TONNES", "COGS"]].sum().tail(20)
        sw = self.share.groupby(["WEEK_START", "PLAYER"]).USD.sum().unstack()
        share_spark = (sw["Northstar"] / sw.sum(axis=1)).rolling(4).mean().tail(20)
        acc = accuracy["ALL"]
        kpis = [
            dict(id="rev", label="Net revenue · MTD", value=rev, fmt="usdM", delta=rev / rev_py - 1, delta_fmt="pct", sub=f"{rev / plan * 100:.1f}% of plan", good=rev >= rev_py, spark=list(weekly.NET_USD.round(0))),
            dict(id="vol", label="Volume · MTD", value=tot("VOL", c), fmt="t", delta=tot("VOL", c) / tot("VOL", p) - 1, delta_fmt="pct", sub="vs prior year", good=True, spark=list(weekly.TONNES.round(1))),
            dict(id="gm", label="Gross margin", value=gm, fmt="pct1", delta=gm - gm_py, delta_fmt="pp", sub="cocoa shock" if "cocoa_up" in scenarios else ("cocoa costs easing" if gm >= gm_py else "cocoa cost pressure"), good=gm >= gm_py, spark=list((1 - weekly.COGS / weekly.NET_USD).round(4))),
            dict(id="share", label="Value share · chocolate", value=share_now, fmt="pct1", delta=share_now - share_prev, delta_fmt="pp", sub="MAT, 7 markets", good=share_now >= share_prev, spark=list(share_spark.round(4))),
            dict(id="otif", label="OTIF", value=otif_tot, fmt="pct1", delta=otif_tot - sum(OTIF_BASE[m] * w[m] for m in C.MARKETS) / sum(w.values()) - 0.006, delta_fmt="pp", sub="vs last month", good=otif_tot > 0.91, spark=[0.92, 0.918, 0.921, 0.917, 0.92, 0.922, 0.919, 0.916, 0.918, 0.92, 0.917, 0.915, 0.916, 0.918, 0.917, 0.915, 0.914, 0.916, 0.915, otif_tot]),
            dict(id="acc", label="Forecast accuracy · AI", value=acc["ai"], fmt="pct1", delta=acc["ai"] - acc["sap"], delta_fmt="pp", sub=f"vs SAP baseline {acc['sap'] * 100:.1f}%", good=True, spark=[]),
        ]
        ch = self.pos[self.pos.WEEK_START > self.pos.WEEK_START.max() - pd.Timedelta(weeks=52)].copy()
        ch["USD"] = _usd(ch)
        mix = (ch.groupby("CHANNEL").USD.sum() / ch.USD.sum()).reindex(list(C.CHANNELS)).fillna(0)
        return dict(kpis=kpis, markets=rows, channel_mix=[dict(code=k, name=C.CHANNELS[k], share=float(v)) for k, v in mix.items()],
                    totals=dict(rev=rev, rev_py=rev_py, plan=plan, gm=gm, share=share_now, otif=otif_tot))

    # ------------------------------------------------------------ market pulse
    def market(self, scenarios: tuple) -> dict:
        s = store()
        sh = self.share
        last = sh.WEEK_START.max()
        r13 = sh[sh.WEEK_START > last - pd.Timedelta(weeks=13)]
        r13_ly = sh[(sh.WEEK_START > last - pd.Timedelta(weeks=65)) & (sh.WEEK_START <= last - pd.Timedelta(weeks=52))]
        cat_growth = r13.USD.sum() / r13_ly.USD.sum() - 1
        last52 = sh[sh.WEEK_START > last - pd.Timedelta(weeks=52)]
        prev52 = sh[(sh.WEEK_START <= last - pd.Timedelta(weeks=52)) & (sh.WEEK_START > last - pd.Timedelta(weeks=104))]
        our = lambda d: d[d.PLAYER == "Northstar"].USD.sum() / d.USD.sum()
        pos = self.pos
        p13 = pos[pos.WEEK_START > last - pd.Timedelta(weeks=13)]
        p13_ly = pos[(pos.WEEK_START > last - pd.Timedelta(weeks=65)) & (pos.WEEK_START <= last - pd.Timedelta(weeks=52))]
        promo_share = lambda d: d[d.PROMO_DEPTH > 0].UNITS.sum() / d.UNITS.sum()
        hh = p13[p13.COMP_PRICE_LC.notna()]
        price_idx = float((hh.SHELF_PRICE_LC * hh.UNITS).sum() / (hh.COMP_PRICE_LC * hh.UNITS).sum() * 100)
        hh_ly = p13_ly[p13_ly.COMP_PRICE_LC.notna()]
        price_idx_ly = float((hh_ly.SHELF_PRICE_LC * hh_ly.UNITS).sum() / (hh_ly.COMP_PRICE_LC * hh_ly.UNITS).sum() * 100)
        pv = pos[pos.WEEK_START > last - pd.Timedelta(weeks=52)].assign(USD=lambda d: _usd(d))
        tt = pv[pv.CHANNEL == "TT"].USD.sum() / pv.USD.sum()
        pv_ly = pos[(pos.WEEK_START <= last - pd.Timedelta(weeks=52)) & (pos.WEEK_START > last - pd.Timedelta(weeks=104))].assign(USD=lambda d: _usd(d))
        tt_ly = pv_ly[pv_ly.CHANNEL == "TT"].USD.sum() / pv_ly.USD.sum()
        kpis = [
            dict(label="Category value growth · LATAM", value=cat_growth, fmt="pctS", sub="last 13 wks vs PY (USD)"),
            dict(label="Our value share", value=our(last52), fmt="pct1", delta=our(last52) - our(prev52), delta_fmt="pp", sub="MAT"),
            dict(label="Price index vs head-to-head", value=price_idx, fmt="int", delta=price_idx - price_idx_ly, delta_fmt="pts", sub="vs head-to-head competitor SKUs"),
            dict(label="Volume sold on promotion", value=promo_share(p13), fmt="pct0", delta=promo_share(p13) - promo_share(p13_ly), delta_fmt="pp", sub="last 13 weeks"),
            dict(label="Traditional trade share", value=tt, fmt="pct0", delta=tt - tt_ly, delta_fmt="pp", sub="of our sell-out value"),
        ]
        # trends
        tr = s.table("TRENDS")
        trends = []
        for code, g in tr.groupby("TREND", sort=False):
            g = g.sort_values("WEEK_START")
            v = g.INDEX.values
            yoy = v[-13:].mean() / v[-65:-52].mean() - 1
            trends.append(dict(code=code, label=g.LABEL.iloc[0], markets=g.MARKETS.iloc[0].replace(",", " · "), yoy=float(yoy),
                               spark=[float(x) for x in v[-26:]], implication=TREND_IMPLICATION.get(code, "")))
        # share by market
        sm = last52.groupby(["COUNTRY", "PLAYER"]).USD.sum().unstack().fillna(0)
        sm = sm.div(sm.sum(axis=1), axis=0)
        players = ["Northstar", "Helvetia", "Andina Dulces", "Private label", "Others"]
        share = [dict(market=m, values=[float(sm.loc[m, p_]) for p_ in players]) for m in C.MARKETS if m in sm.index]
        # POS heatmap: regions × last 12 weeks, % vs prior year
        wk = sorted(pos.WEEK_START.unique())[-12:]
        heat = []
        reg_units = pos.groupby(["REGION", "WEEK_START"]).UNITS.sum()
        for r in C.REGIONS:
            vals = []
            for w_ in wk:
                ly = pd.Timestamp(w_) - pd.Timedelta(weeks=52)
                a, b = reg_units.get((r, pd.Timestamp(w_)), np.nan), reg_units.get((r, ly), np.nan)
                vals.append(None if not b else round((a / b - 1) * 100))
            heat.append(dict(region=C.REGIONS[r]["name"], values=vals))
        weeks_lbl = [f"W{pd.Timestamp(w_).isocalendar()[1]:02d}" for w_ in wk]
        # channel mix by half-year
        pv_all = pos.assign(USD=lambda d: _usd(d), H=lambda d: d.WEEK_START.dt.year.astype(str).str[2:] + np.where(d.WEEK_START.dt.month <= 6, "H1", "H2"))
        mix = pv_all.groupby(["H", "CHANNEL"]).USD.sum().unstack().fillna(0)
        mix = mix.div(mix.sum(axis=1), axis=0)
        mix = mix.loc[[h for h in mix.index if h not in ("23H2",)]]
        channel_mix = dict(periods=[f"{h[2:]} {h[:2]}" for h in mix.index], series=[dict(code=c_, name=C.CHANNELS[c_], values=[float(x) for x in mix[c_].values]) for c_ in C.CHANNELS])
        # local dynamics
        macro = s.table("MACRO")
        ar = macro[macro.COUNTRY == "AR"].sort_values("MONTH").iloc[-1]
        temps = pos[pos.WEEK_START == last].groupby("REGION").TEMP_C.mean()
        hot = temps.sort_values(ascending=False).head(3)
        heat_txt = ", ".join(f"{C.REGIONS[r]['name'].split(' · ')[-1]} {t:.0f}°C" for r, t in hot.items())
        if "heat_mx" in scenarios:
            heat_txt = "Monterrey 41°C, Mérida 39°C (heat wave) · " + heat_txt
        local = [
            dict(color="info", title="Macro (mock)", text=f"AR CPI {ar.CPI_MOM * 100:.1f}% m/m · ARS {ar.FX_PER_USD:,.0f}/USD (crawling band) · MXN, BRL, COP broadly stable"),
            dict(color="warn", title="Weather", text=f"Hottest regions this week: {heat_txt} → melt risk above 28°C; Andean rainy season starting"),
            dict(color="ai", title="Regulation", text="MX NOM-051 warning octagons · CO health tax on ultra-processed foods (20%) · CL Ley 20.606 ad limits · BR RDC 429 front-label magnifier"),
            dict(color="gold", title="Calendar", text="Día de Muertos 1–2 Nov · Buen Fin 13–16 Nov · BR Black Friday 27 Nov · Navidad · Páscoa 28 Mar 2027"),
            dict(color="teal", title="Route-to-market", text="~1.2M traditional points of sale · pre-venta + distributor model · cash-heavy tiendas"),
        ]
        # competitor activity: detected price moves + field feed
        comp = []
        mt = pos[pos.COMP_PRICE_LC.notna()]
        recent = mt[mt.WEEK_START == last]
        prior = mt[(mt.WEEK_START < last) & (mt.WEEK_START >= last - pd.Timedelta(weeks=4))].groupby(["REGION", "CHANNEL", "MATNR"]).COMP_PRICE_LC.mean()
        for r_ in recent.itertuples():
            pr = prior.get((r_.REGION, r_.CHANNEL, r_.MATNR))
            if pr and r_.COMP_PRICE_LC < pr * 0.9 and r_.CHANNEL == "MT" and r_.REGION == "MX-CDMX":
                comp.append(dict(when="06:40", text=f"{C.COMP_PRODUCT[r_.MATNR]} {(r_.COMP_PRICE_LC / pr - 1) * 100:.0f}% at Hiper Nacional ({C.REGIONS[r_.REGION]['name']}, modern trade): MXN {pr:.2f} → {r_.COMP_PRICE_LC:.2f}",
                                 source="Retailer POS scan feed", type="Price", tone="neg"))
        for r_ in s.table("COMP_FEED").itertuples():
            comp.append(dict(when=r_.WHEN, text=r_.TEXT, source=r_.SOURCE, type=r_.TYPE, tone=dict(Launch="warn", Entry="warn", Seasonal="info", Price="pos").get(r_.TYPE, "info")))
        return dict(kpis=kpis, trends=trends, share=dict(players=players, rows=share), heat=dict(weeks=weeks_lbl, rows=heat), local=local,
                    channel_mix=channel_mix, competitor=comp)
