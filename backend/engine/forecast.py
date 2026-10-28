"""Demand forecasting over SAP shipment history.

A global gradient-boosted model with quantile loss (P10/P50/P90). Features cover events, the promo plan, the
competitor price gap, weather and product/site categoricals. A demand-sensing step then nudges the first weeks
toward recent POS momentum. The SAP IBP-style statistical baseline is the comparison.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .. import catalog as C
from ..datagen import HIST, PROMO_CH, seasonal_curve
from ..store import store
from .baseline import sap_baseline

EVENTS = list(C.EVENT_LABELS)
CATS = ["mkt", "brand", "sku", "dc"]
FEATS = CATS + ["iso_week", "wsin", "wcos", "promo", "comp_depth", "temp", "cur_muertos", "cur_navidad", "cur_pascoa",
                "log_level"] + [f"ev_{e}" for e in EVENTS]
H = 26
BACKTEST = 13
DAY_SHAPE = np.array([0.16, 0.15, 0.15, 0.15, 0.16, 0.14, 0.09])
HEAT_DCS = {"MX3D": 5.0, "MX5D": 4.0, "MX4D": 4.5}


class Forecaster:
    def __init__(self):
        t0 = time.time()
        s = store()
        self.weeks = s.table("WEEKS")
        self.n = len(self.weeks)
        si = s.table("SELLIN_WEEKLY")
        si = si.sort_values("WEEK_START")
        self.keys = sorted({(w, m) for w, m in zip(si.WERKS, si.MATNR)})
        piv = lambda col: si.pivot_table(index=["WERKS", "MATNR"], columns="WEEK_START", values=col, aggfunc="sum").reindex(self.keys).fillna(0.0).values
        self.Y = piv("QTY_CS")
        self.promo_hist = piv("PROMO_DEPTH")
        self.temp_hist = si.pivot_table(index=["WERKS", "MATNR"], columns="WEEK_START", values="TEMP_C").reindex(self.keys).ffill(axis=1).fillna(25).values
        self.idx = {k: i for i, k in enumerate(self.keys)}
        self._build_static()
        self.models_bt = self._fit(origin=HIST - BACKTEST)
        self.models = self._fit(origin=HIST)
        self._backtest()
        # prediction intervals calibrated on each series' own backtest errors (log scale)
        a, ai = self.bt["actual"], self.bt["ai"]
        self.sigma = np.clip(np.std(np.log((a + 1) / (ai + 1)), axis=1), 0.06, 0.6)
        self.fit_seconds = round(time.time() - t0, 1)
        self.scenario_key = None
        self.refresh(())

    # ------------------------------------------------------------------ features
    def _build_static(self):
        w = self.weeks
        n = self.n
        self.ev = {m: np.zeros((len(EVENTS), n)) for m in C.MARKETS}
        for i, (y, wk) in enumerate(zip(w.iso_year, w.iso_week)):
            for m in C.MARKETS:
                for e, v in C.event_intensity(m, int(y), int(wk)).items():
                    self.ev[m][EVENTS.index(e), i] = v
        shift = lambda a: np.concatenate([a[2:], np.zeros(2)])
        self.curves = {k: shift(seasonal_curve(k, w)) for k in ("muertos", "navidad", "pascoa")}
        iso = w.iso_week.values.astype(float)
        self.wsin, self.wcos = np.sin(2 * np.pi * iso / 52), np.cos(2 * np.pi * iso / 52)
        # future promo plan (market level, weighted by promo-eligible channel share)
        pf = store().table("PROMO_FUTURE")
        self.promo_future = np.zeros((len(self.keys), n))
        t_of = {ws: t for t, ws in zip(w.t, pd.to_datetime(w.week_start))}
        for r in pf.itertuples():
            share = sum(v for c, v in C.MARKETS[r.COUNTRY]["channels"].items() if c in PROMO_CH)
            for dc, d in C.DCS.items():
                if d["country"] == r.COUNTRY and (dc, r.MATNR) in self.idx:
                    self.promo_future[self.idx[(dc, r.MATNR)], t_of[pd.Timestamp(r.WEEK_START)]] = r.DEPTH * share
        # competitor promo depth in the DC's regions (modern trade), from POS
        pos = store().table("POS_WEEKLY")
        mt = pos[(pos.CHANNEL == "MT") & pos.COMP_PRICE_LC.notna()].copy()
        mt["cdepth"] = 1 - mt.COMP_PRICE_LC / mt.COMP_LIST_LC
        cd = mt.pivot_table(index=["REGION", "MATNR"], columns="WEEK_START", values="cdepth").fillna(0.0)
        self.comp_hist = np.zeros((len(self.keys), HIST))
        for (dc, sku), i in self.idx.items():
            for r, splits in C.REGION_DCS.items():
                if dc in splits and (r, sku) in cd.index:
                    self.comp_hist[i] += cd.loc[(r, sku)].values[:HIST] * splits[dc] / sum(1 for rr, ss in C.REGION_DCS.items() if dc in ss)
        # temperature climatology per series by iso week
        iso_hist = w.iso_week.values[:HIST]
        self.temp_clim = np.zeros((len(self.keys), 54))
        for wk in range(1, 54):
            mask = iso_hist == wk
            self.temp_clim[:, wk] = self.temp_hist[:, mask].mean(axis=1) if mask.any() else self.temp_hist.mean(axis=1)

    def _growth(self, origin: int) -> np.ndarray:
        """Year-on-year growth of the last 26 weeks per series (1.0 for seasonal SKUs)."""
        g = np.ones(len(self.keys))
        for i, (dc, sku) in enumerate(self.keys):
            y = self.Y[i, :origin]
            ly = y[origin - 78:origin - 52].sum()
            if ly > 0 and not C.SKUS[sku].get("seasonal"):
                g[i] = np.clip(y[origin - 26:].sum() / ly, 0.9, 1.2)
        return g

    def _trend(self, fit: dict, rows, ts) -> np.ndarray:
        # the 52-week level is centred ~26 weeks before origin
        return fit["growth"][rows] ** ((ts - fit["origin"] + 26) / 52.0)

    def _levels(self, origin: int) -> np.ndarray:
        lv = np.zeros(len(self.keys))
        for i, (dc, sku) in enumerate(self.keys):
            y = self.Y[i, :origin]
            if C.SKUS[sku].get("seasonal"):
                top = np.sort(y[max(0, origin - 104):])[-8:]
                lv[i] = max(top.mean(), 1.0)
            else:
                lv[i] = max(y[origin - 52:].mean(), 1.0)
        return lv

    def _frame(self, rows: np.ndarray, ts: np.ndarray, origin: int, levels: np.ndarray, promo=None, comp=None, temp=None,
               events_on=True) -> pd.DataFrame:
        """Feature rows for series `rows` at absolute week indices `ts` (both 1-D, same length)."""
        w = self.weeks
        keys = [self.keys[r] for r in rows]
        mk = np.array([C.DCS[dc]["country"] for dc, _ in keys])
        df = pd.DataFrame({
            "mkt": pd.Categorical(mk, categories=list(C.MARKETS)).codes,
            "brand": pd.Categorical([C.SKUS[s]["brand"] for _, s in keys], categories=sorted({v["brand"] for v in C.SKUS.values()})).codes,
            "sku": pd.Categorical([s for _, s in keys], categories=list(C.SKUS)).codes,
            "dc": pd.Categorical([d for d, _ in keys], categories=list(C.DCS)).codes,
            "iso_week": w.iso_week.values[ts], "wsin": self.wsin[ts], "wcos": self.wcos[ts],
            "promo": promo if promo is not None else np.where(ts < HIST, self.promo_hist[rows, np.minimum(ts, HIST - 1)], self.promo_future[rows, ts]),
            "comp_depth": comp if comp is not None else np.where(ts < HIST, self.comp_hist[rows, np.minimum(ts, HIST - 1)], 0.0),
            "temp": temp if temp is not None else np.where(ts < HIST, self.temp_hist[rows, np.minimum(ts, HIST - 1)], self.temp_clim[rows, w.iso_week.values[ts]]),
            "log_level": np.log(levels[rows]),
        })
        seasonal = np.array([C.SKUS[s].get("seasonal", "") for _, s in keys])
        for k in ("muertos", "navidad", "pascoa"):
            df[f"cur_{k}"] = np.where(seasonal == k, self.curves[k][ts], 0.0) if events_on else 0.0
        evm = np.stack([self.ev[m][:, t] for m, t in zip(mk, ts)]) if events_on else np.zeros((len(ts), len(EVENTS)))
        for j, e in enumerate(EVENTS):
            df[f"ev_{e}"] = evm[:, j]
        return df[FEATS]

    def _fit(self, origin: int) -> dict:
        levels = self._levels(origin)
        nser = len(self.keys)
        ts = np.tile(np.arange(0, origin), nser)
        rows = np.repeat(np.arange(nser), origin)
        X = self._frame(rows, ts, origin, levels)
        fit = dict(levels=levels, origin=origin, growth=self._growth(origin))
        y = self.Y[rows, ts] / (levels[rows] * self._trend(fit, rows, ts))
        models = {}
        # point forecast = mean (Poisson loss, unbiased); intervals come from backtest residuals, not separate quantile models
        m = HistGradientBoostingRegressor(loss="poisson", max_iter=260, learning_rate=0.07, max_leaf_nodes=31,
                                          min_samples_leaf=30, categorical_features=[FEATS.index(c) for c in CATS], random_state=7)
        m.fit(X, y)
        models[0.5] = m
        return dict(fit, models=models)

    # ------------------------------------------------------------------ prediction
    def _sensing(self, origin: int) -> np.ndarray:
        """POS momentum: last 2 weeks vs last year, relative to the 13-week YoY trend."""
        pos = store().table("POS_WEEKLY")
        pv = pos.pivot_table(index=["REGION", "MATNR"], columns="WEEK_START", values="UNITS", aggfunc="sum").fillna(0.0)
        out = np.ones(len(self.keys))
        for i, (dc, sku) in enumerate(self.keys):
            regions = [r for r, sp in C.REGION_DCS.items() if dc in sp and (r, sku) in pv.index]
            if not regions or C.SKUS[sku].get("seasonal"):
                continue
            a = pv.loc[[(r, sku) for r in regions]].values.sum(axis=0)
            rec, rec_ly = a[origin - 2:origin].sum(), a[origin - 54:origin - 52].sum()
            tr, tr_ly = a[origin - 15:origin - 2].sum(), a[origin - 67:origin - 54].sum()
            if rec_ly > 0 and tr_ly > 0 and tr > 0:
                out[i] = float(np.clip((rec / rec_ly) / (tr / tr_ly), 0.88, 1.15))
        return out

    def _predict(self, fit: dict, rows, ts, sensing=None, **over) -> dict[float, np.ndarray]:
        X = self._frame(rows, ts, fit["origin"], fit["levels"], **over)
        lv = fit["levels"][rows]
        out = {}
        h = ts - fit["origin"] + 1
        g = self._trend(fit, rows, ts)
        sens = 1.0 if sensing is None else 1 + (sensing[rows] - 1) * np.where(h == 1, 0.7, np.where(h == 2, 0.4, np.where(h == 3, 0.15, 0.0)))
        for q, m in fit["models"].items():
            p = np.maximum(m.predict(X), 0.0) * lv * g * sens
            seas = np.array([C.SKUS[self.keys[r][1]].get("seasonal", "") for r in rows])
            inseason = np.ones(len(rows), dtype=bool)
            for k in ("muertos", "navidad", "pascoa"):
                inseason &= ~((seas == k) & (self.curves[k][ts] == 0))
            out[q] = np.where(inseason, p, 0.0)
        return out

    def _future_overrides(self, scenarios: tuple) -> dict:
        nser = len(self.keys)
        ts = np.arange(HIST, HIST + H)
        comp = np.zeros((nser, H))
        last = self.comp_hist[:, HIST - 1]
        deeper = "comp_deeper" in scenarios
        for i, (dc, sku) in enumerate(self.keys):
            if last[i] > 0.01:
                comp[i, :2] = last[i] * (1.5 if deeper and (dc, sku) == ("MX1D", "100045") else 1.0)
        temp = self.temp_clim[:, self.weeks.iso_week.values[ts]].copy()
        if "heat_mx" in scenarios:
            for dc, add in HEAT_DCS.items():
                for i, (d, _) in enumerate(self.keys):
                    if d == dc:
                        temp[i, :2] += add
        return dict(comp=comp, temp=temp)

    def refresh(self, scenarios: tuple):
        """Recompute future forecasts for the active scenarios (no retraining)."""
        key = tuple(sorted(s for s in scenarios if s in ("heat_mx", "comp_deeper")))
        if key == self.scenario_key:
            return
        nser = len(self.keys)
        rows = np.repeat(np.arange(nser), H)
        ts = np.tile(np.arange(HIST, HIST + H), nser)
        ov = self._future_overrides(key)
        self.sensing = self._sensing(HIST)
        p50 = self._predict(self.models, rows, ts, sensing=self.sensing, comp=ov["comp"].ravel(), temp=ov["temp"].ravel())[0.5].reshape(nser, H)
        widen = np.sqrt(1 + 0.03 * np.arange(H))[None, :]
        z = 1.2816 * self.sigma[:, None] * widen
        self.fc = {0.5: p50, 0.1: p50 * np.exp(-z), 0.9: p50 * np.exp(z)}
        self.overrides = ov
        self.scenario_key = key

    def _backtest(self):
        o = HIST - BACKTEST
        nser = len(self.keys)
        rows = np.repeat(np.arange(nser), BACKTEST)
        ts = np.tile(np.arange(o, HIST), nser)
        p = self._predict(self.models_bt, rows, ts, sensing=self._sensing(o))[0.5].reshape(nser, BACKTEST)
        sap = np.stack([sap_baseline(self.Y[i], BACKTEST, origin=o) for i in range(nser)])
        self.bt = dict(ai=p, sap=sap, actual=self.Y[:, o:HIST])

    # ------------------------------------------------------------------ public API
    def sap_future(self, i: int) -> np.ndarray:
        return sap_baseline(self.Y[i], H, origin=HIST)

    def accuracy(self) -> dict:
        res = {}
        mk = np.array([C.DCS[dc]["country"] for dc, _ in self.keys])
        a, ai, sap = self.bt["actual"], self.bt["ai"], self.bt["sap"]
        for m in list(C.MARKETS) + ["ALL"]:
            sel = mk == m if m != "ALL" else np.ones(len(mk), dtype=bool)
            tot = a[sel].sum()
            res[m] = dict(ai=1 - np.abs(ai[sel] - a[sel]).sum() / tot, sap=1 - np.abs(sap[sel] - a[sel]).sum() / tot,
                          bias_ai=(ai[sel] - a[sel]).sum() / tot, bias_sap=(sap[sel] - a[sel]).sum() / tot)
        return res

    def safety_stock_release_usd(self) -> float:
        a, ai, sap = self.bt["actual"], self.bt["ai"], self.bt["sap"]
        z, total = 1.88, 0.0
        for i, (dc, sku) in enumerate(self.keys):
            sd = C.SKUS[sku]
            lt = np.sqrt(2.0 if C.DCS[dc]["country"] in ("MX", "BR") else 3.0)
            case_cost = sd["upc"] * sd["cogs"]
            total += z * lt * (np.std(sap[i] - a[i]) - np.std(ai[i] - a[i])) * case_cost
        return float(max(total, 0.0))

    def series(self, dc: str, sku: str) -> dict:
        i = self.idx[(dc, sku)]
        hist_start = HIST - 57
        bt_o = HIST - BACKTEST
        w = self.weeks
        labels = [f"W{int(wk):02d}'{str(int(y))[2:]}" for y, wk in zip(w.iso_year.values[hist_start:HIST + H], w.iso_week.values[hist_start:HIST + H])]
        n_hist = HIST - hist_start
        actual = list(self.Y[i, hist_start:HIST]) + [None] * H
        sap = [None] * (bt_o - hist_start) + list(self.bt["sap"][i]) + list(self.sap_future(i))
        ai = [None] * (bt_o - hist_start) + list(self.bt["ai"][i]) + list(self.fc[0.5][i])
        lo = [None] * (n_hist - 1) + [self.Y[i, HIST - 1]] + list(self.fc[0.1][i])
        hi = [None] * (n_hist - 1) + [self.Y[i, HIST - 1]] + list(self.fc[0.9][i])
        m = C.DCS[dc]["country"]
        ann = []
        for j, t in enumerate(range(hist_start, HIST + H)):
            ev = C.event_intensity(m, int(w.iso_year[t]), int(w.iso_week[t]))
            for e, v in ev.items():
                if v >= 1.0 and e in ("muertos", "navidad", "buen_fin", "valentine", "kids", "pascoa", "black_friday", "halloween"):
                    if e == "navidad" and int(w.iso_week[t]) != 51:
                        continue
                    ann.append(dict(i=j, label=C.EVENT_LABELS[e].split(" / ")[0].replace("Día de ", "").replace("Día del ", "D. ")))
        return dict(labels=labels, split=n_hist - 1, actual=actual, sap=sap, ai=ai, lo=lo, hi=hi, ann=ann)

    def bridge(self, dc: str, sku: str, weeks: int = 8) -> list[dict]:
        """SAP baseline → AI forecast, decomposed by switching feature groups on one at a time."""
        i = self.idx[(dc, sku)]
        rows = np.full(weeks, i)
        ts = np.arange(HIST, HIST + weeks)
        clim = self.temp_clim[i, self.weeks.iso_week.values[ts]]
        actual_temp = self.overrides["temp"][i, :weeks]
        actual_comp = self.overrides["comp"][i, :weeks]
        zeros = np.zeros(weeks)
        p = lambda **kw: self._predict(self.models, rows, ts, **kw)[0.5].sum()
        x0 = p(promo=zeros, comp=zeros, temp=clim, events_on=False)
        x1 = p(promo=zeros, comp=zeros, temp=clim)
        x2 = p(comp=zeros, temp=clim)
        x3 = p(comp=actual_comp, temp=clim)
        x4 = p(comp=actual_comp, temp=actual_temp)
        x5 = float(self.fc[0.5][i, :weeks].sum())
        sap = float(self.sap_future(i)[:weeks].sum())
        steps = [("SAP IBP baseline", sap, "total"), ("Level & trend", x0 - sap, "delta"), ("Seasonality & events", x1 - x0, "delta"),
                 ("Promotions (TPM plan)", x2 - x1, "delta"), ("Competitor price gap", x3 - x2, "delta"), ("Weather", x4 - x3, "delta"),
                 ("POS demand sensing", x5 - x4, "delta"), ("AI forecast", x5, "total")]
        return [dict(label=l, value=round(v), kind=k) for l, v, k in steps]

    def daily_demand(self, i: int, days: int, today_dow: int = 1) -> tuple[np.ndarray, np.ndarray]:
        """Daily P50 demand and relative sigma for the next `days` days (rest of current week, then forecast)."""
        cur = self.Y[i, HIST - 1]
        weekly = np.concatenate([[cur], self.fc[0.5][i]])
        spread = np.concatenate([[0.08], (self.fc[0.9][i] - self.fc[0.1][i]) / 2.56 / np.maximum(self.fc[0.5][i], 1)])
        dem, sig = [], []
        for d in range(1, days + 1):
            dow = (today_dow + d) % 7
            wk = (today_dow + d) // 7
            dem.append(weekly[min(wk, len(weekly) - 1)] * DAY_SHAPE[dow])
            sig.append(spread[min(wk, len(spread) - 1)])
        return np.array(dem), np.clip(np.array(sig), 0.03, 0.6)
