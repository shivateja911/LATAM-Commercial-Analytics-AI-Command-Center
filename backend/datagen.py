"""Seeded synthetic data generator.

Builds three years of consumer demand (POS) from a known price/promo/event/weather model, derives DC shipments
(SAP sell-in), and writes SAP-shaped tables plus external signals to data/cabi.duckdb. The engines then
rediscover the planted stories (competitor price cut, Día de Muertos surge, stock imbalances) from the data.

Run:  .venv/bin/python -m backend.datagen
"""
from __future__ import annotations

import math
import time
from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd

from . import catalog as C
from .config import DATA, DB_PATH, EXTRACTS, settings, today
from .engine.baseline import sap_baseline

HIST = 156          # weeks of history ending with the current week
FUT = 30            # future weeks generated for lead-time and promo-plan purposes
PROMO_CH = ("MT", "DISC", "CONV", "ECOM")
AFFINITY = {
    "Rayo": dict(TT=1.3, MT=0.7, CONV=1.4, DISC=0.8, ECOM=0.5),
    "Crunchita": dict(TT=1.2, MT=0.8, CONV=1.3, DISC=1.0, ECOM=0.6),
    "Dulcera": dict(TT=1.0, MT=1.1, CONV=0.9, DISC=1.0, ECOM=1.0),
    "Cacao Alto": dict(TT=0.5, MT=1.6, CONV=0.8, DISC=0.6, ECOM=2.0),
    "Almendra Real": dict(TT=1.0, MT=1.0, CONV=1.1, DISC=0.9, ECOM=0.9),
    "Fiesta Bites": dict(TT=0.8, MT=1.4, CONV=0.7, DISC=1.1, ECOM=1.2),
}
GIFT_BRANDS = {"Fiesta Bites", "Cacao Alto"}
GIFT_EVENTS = {"muertos", "navidad", "valentine", "mothers"}
INFLATION = dict(MX=0.045, BR=0.045, CO=0.060, PE=0.030, CL=0.040, AR=0.30, CA=0.030)
# current shelf prices (local currency) that the demo talks about; everything else follows a price-point rule
SHELF_OVERRIDE = {("MX", "100012", "TT"): 10.0, ("MX", "100041", "TT"): 22.0, ("MX", "100045", "MT"): 39.90,
                  ("MX", "100058", "MT"): 79.0, ("MX", "100061", "MT"): 64.0, ("MX", "100051", "MT"): 46.0}
TEMP_CLIMATE = {"MX-NOR": (29, 7, 27), "MX-BAJ": (26, 4, 22), "MX-CDMX": (23, 3, 20), "MX-SUR": (32, 3, 22),
                "BR-SP": (26, 4, 3), "BR-SUL": (24, 6, 3), "BR-NE": (30, 2, 3), "BR-NO": (32, 1.5, 40),
                "CO-AND": (19, 1, 10), "CO-CAR": (32, 1.5, 30), "PE-LIM": (22, 4, 6), "PE-CEN": (18, 2, 6),
                "PE-SUR": (22, 3, 6), "CL-RM": (23, 7, 3), "AR-AMBA": (23, 7, 3), "CA-CAM": (31, 2, 16)}
SEASON_CURVES = {
    "muertos": {39: .2, 40: .35, 41: .55, 42: .75, 43: 1.0, 44: .85, 45: .1},
    "navidad": {45: .15, 46: .3, 47: .45, 48: .6, 49: .8, 50: 1.0, 51: .95, 52: .55, 53: .3},
}
PASCOA_CURVE = {7: .1, 6: .2, 5: .35, 4: .55, 3: .75, 2: .9, 1: 1.0, 0: .8}


def week_grid() -> pd.DataFrame:
    y, w, _ = today().isocalendar()
    cur = date.fromisocalendar(y, w, 1)
    mondays = [cur - timedelta(weeks=HIST - 1 - i) for i in range(HIST + FUT)]
    iso = [m.isocalendar() for m in mondays]
    return pd.DataFrame({"t": range(HIST + FUT), "week_start": mondays,
                         "iso_year": [i[0] for i in iso], "iso_week": [i[1] for i in iso]})


def price_point(m: str, v: float) -> float:
    if m == "MX":
        return float(round(v)) if v < 30 else math.floor(v) + 0.90
    if m == "BR":
        return math.floor(v) + (0.49 if v - math.floor(v) < 0.5 else 0.99)
    if m == "CO":
        return float(round(v / 100) * 100)
    if m == "PE":
        return math.floor(v) + (0.50 if v - math.floor(v) < 0.5 else 0.90)
    if m in ("CL", "AR"):
        return float(round(v / 10) * 10)
    return round(v, 2) - 0.01 if v > 1 else round(v, 2)


def seasonal_curve(kind: str, weeks: pd.DataFrame) -> np.ndarray:
    if kind == "pascoa":
        out = []
        for ws in weeks.week_start:
            ws = pd.Timestamp(ws).date()
            easter = C.EASTER.get(ws.year) if C.EASTER.get(ws.year, date.min) >= ws else C.EASTER.get(ws.year + 1)
            wb = int(round((easter - ws).days / 7)) if easter else 99
            out.append(PASCOA_CURVE.get(wb, 0.0))
        return np.array(out)
    curve = SEASON_CURVES[kind]
    return np.array([curve.get(w, 0.0) for w in weeks.iso_week])


def place_promos(rng, n: int, per_year: float, depths, protect=()) -> np.ndarray:
    arr = np.zeros(n)
    k = int(per_year * n / 52)
    for _ in range(k):
        s = int(rng.integers(0, n - 2))
        if arr[s:s + 2].any() or any(p in (s, s + 1) for p in protect):
            continue
        arr[s:s + 2] = rng.choice(depths, p=[0.4, 0.4, 0.2])
    return arr


def generate(seed: int | None = None) -> dict:
    t_start = time.time()
    cfg = settings()
    seed = cfg["demo"]["seed"] if seed is None else seed
    rng = np.random.default_rng(seed)
    weeks = week_grid()
    n = len(weeks)
    tt = weeks.t.values
    years = (tt - (HIST - 1)) / 52.0
    months = np.array([(ws.year - 2023) * 12 + ws.month for ws in weeks.week_start])
    cur_i = HIST - 1
    idx_of = {(int(y), int(w)): i for i, (y, w) in enumerate(zip(weeks.iso_year, weeks.iso_week))}

    # ---------------- market-level arrays: events, price indices, promos ----------------
    ev = {m: {e: np.zeros(n) for e in C.EVENT_LABELS} for m in C.MARKETS}
    for i, (y, w) in enumerate(zip(weeks.iso_year, weeks.iso_week)):
        for m in C.MARKETS:
            for e, v in C.event_intensity(m, int(y), int(w)).items():
                ev[m][e][i] = v
    cat_lvl, our_lvl, comp_lvl = {}, {}, {}
    for m in C.MARKETS:
        if m == "AR":
            cat_lvl[m] = 1.022 ** (months + (weeks.week_start.map(lambda d: d.day).values / 30.0))
            our_lvl[m] = 1.022 ** (months + 0.6)
            comp_lvl[m] = 1.022 ** (months + 0.2)
        else:
            # category prices drift smoothly; we step list prices each January, the competitor each March
            pi = INFLATION[m]
            frac_year = np.array([ws.year + (ws.timetuple().tm_yday / 365.0) for ws in weeks.week_start]) - 2026.0
            cat_lvl[m] = (1 + pi) ** frac_year
            our_lvl[m] = (1 + pi) ** (np.floor(frac_year) + 0.5)
            comp_lvl[m] = (1 + pi) ** (np.floor(frac_year - 2 / 12) + 0.5 + 2 / 12)
    usd_idx = 1.035 ** years

    our_promo, comp_promo = {}, {}
    for m in C.MARKETS:
        for sku, sd in C.SKUS.items():
            if sd.get("seasonal"):
                our_promo[(m, sku)] = np.zeros(n)
                comp_promo[(m, sku)] = np.zeros(n)
                continue
            protect = []
            if m == "MX" and sku in ("100041", "100045"):
                protect = [idx_of.get((2025, 46), -1), idx_of.get((2025, 45), -1)]
            our_promo[(m, sku)] = place_promos(rng, n, 7.5, [0.10, 0.15, 0.20], protect)
            cp = place_promos(rng, n, 5.0, [0.10, 0.15, 0.20]) if sku in C.COMP_PRODUCT else np.zeros(n)
            if m == "MX" and sku == "100045":
                cp[cur_i - 6:cur_i + 4] = 0.0
            comp_promo[(m, sku)] = cp
    # planned events the demo talks about: no own promo on Dulcera 90g around the competitor cut,
    # and a Buen Fin TPR this year that did not run last year (so the SAP baseline cannot see it)
    our_promo[("MX", "100045")][cur_i - 4:cur_i + 4] = 0.0
    bf = idx_of[(today().isocalendar()[0], 46)]
    for sku in ("100041", "100045"):
        our_promo[("MX", sku)][bf - 1:bf + 2] = 0.0
        our_promo[("MX", sku)][bf] = 0.15
    for i, w in enumerate(weeks.iso_week):
        if w == 48:
            our_promo[("BR", "100045")][i] = 0.10
    region_comp_cut = {("MX-CDMX", "100045", "MT"): {cur_i: 0.12, cur_i + 1: 0.12, cur_i + 2: 0.12}}

    # ---------------- weather ----------------
    temp = {}
    for r, (mean, amp, peak) in TEMP_CLIMATE.items():
        base = mean + amp * np.cos(2 * np.pi * (weeks.iso_week.values - peak) / 52.0)
        noise = rng.normal(0, 1.1, n)
        noise[HIST:] = 0.0
        temp[r] = base + noise
    temp["MX-NOR"][cur_i - 1:cur_i + 1] += 4.5
    temp["MX-SUR"][cur_i] += 2.0

    # ---------------- shelf prices ----------------
    base_shelf = {}
    for m, md in C.MARKETS.items():
        for sku, sd in C.SKUS.items():
            for ch in md["channels"]:
                key = (m, sku, ch)
                now = SHELF_OVERRIDE.get(key) or price_point(m, sd["price"] / 0.72 * md["fx"] * C.SHELF_FACTOR[ch])
                base_shelf[key] = now / our_lvl[m][cur_i]

    # ---------------- consumer demand (POS) ----------------
    pos_rows, share_rows = [], []
    units = {}           # (region, ch, sku) -> units array over all n weeks
    value_exp = {}       # (region, ch) -> expected value array (for share base)
    for r, rd in C.REGIONS.items():
        m = rd["country"]
        md = C.MARKETS[m]
        trend = (1 + md["growth"] - 0.035) ** years
        temp_eff = np.exp(-0.015 * np.maximum(0.0, temp[r] - 28.0))
        boost = np.ones(n)
        if r in ("MX-CDMX", "MX-BAJ"):
            boost[cur_i - 1:cur_i + 1] = 1.13
        for ch, ch_share in md["channels"].items():
            vexp = np.zeros(n)
            for sku, sd in C.SKUS.items():
                if sd.get("markets") and m not in sd["markets"]:
                    continue
                aff = AFFINITY[sd["brand"]][ch]
                if sd.get("seasonal"):
                    if sd["seasonal"] == "pascoa" and m != "BR":
                        continue
                    lvl = C.SEASONAL_PEAK[sd["seasonal"]] * seasonal_curve(sd["seasonal"], weeks)
                    evm = np.ones(n)
                else:
                    lvl = np.full(n, float(sd["base"]))
                    evm = np.ones(n)
                    for e, lift in C.EVENT_LIFT[m].items():
                        mult = 1.8 if (sd["brand"] in GIFT_BRANDS and e in GIFT_EVENTS) else (1.4 if e == "kids" and sd["brand"] in ("Rayo", "Crunchita") else 1.0)
                        evm = evm + lift * mult * ev[m][e]
                u_base = lvl * sd["upc"] * md["share"] * rd["share"] * ch_share * aff
                key = (m, sku, ch)
                list_lc = base_shelf[key] * our_lvl[m]
                depth = our_promo[(m, sku)] if ch in PROMO_CH else np.zeros(n)
                shelf = list_lc * (1 - depth)
                own_rel = shelf / (base_shelf[key] * cat_lvl[m])
                cdepth = comp_promo[(m, sku)].copy() if ch in PROMO_CH else np.zeros(n)
                for i, d in region_comp_cut.get((r, sku, ch), {}).items():
                    cdepth[i] = d
                comp_shelf = base_shelf[key] * 1.04 * comp_lvl[m] * (1 - cdepth)
                comp_rel = comp_shelf / (base_shelf[key] * 1.04 * cat_lvl[m])
                display = np.where((depth > 0) & (ch in ("MT", "DISC")), 1.05, 1.0)
                sigma = 0.05 if ch == "TT" else 0.07
                noise = np.exp(rng.normal(0, sigma, n) - sigma ** 2 / 2)
                b = boost * (1.07 if sd["brand"] == "Fiesta Bites" else 1.0) if r in ("MX-CDMX", "MX-BAJ") else boost
                u = u_base * trend * evm * own_rel ** C.OWN_ELASTICITY[ch] * comp_rel ** C.CROSS_ELASTICITY[ch] * display * temp_eff * b * noise
                units[(r, ch, sku)] = u
                vexp += u_base * trend * evm * temp_eff * list_lc
                if sd.get("seasonal") and lvl[:HIST].sum() == 0:
                    continue
                has_comp = sku in C.COMP_PRODUCT
                pos_rows.append(pd.DataFrame({
                    "WEEK_START": weeks.week_start[:HIST], "ISO_YEAR": weeks.iso_year[:HIST], "ISO_WEEK": weeks.iso_week[:HIST],
                    "COUNTRY": m, "REGION": r, "CHANNEL": ch, "MATNR": sku, "UNITS": u[:HIST],
                    "SHELF_PRICE_LC": shelf[:HIST], "LIST_PRICE_LC": list_lc[:HIST], "PROMO_DEPTH": depth[:HIST],
                    "COMP_PRICE_LC": comp_shelf[:HIST] if has_comp else np.nan, "COMP_LIST_LC": (base_shelf[key] * 1.04 * comp_lvl[m])[:HIST] if has_comp else np.nan,
                    "CAT_INDEX": cat_lvl[m][:HIST], "TEMP_C": temp[r][:HIST]}))
            value_exp[(r, ch)] = vexp

    # ---------------- DC shipments (sell-in) and revenue calibration ----------------
    sell = {}
    for (r, ch, sku), u in units.items():
        lead = 2 if C.SKUS[sku].get("seasonal") else 0
        shifted = np.concatenate([u[lead:], np.zeros(lead)]) if lead else u
        for dc, split in C.REGION_DCS[r].items():
            sell[(dc, sku)] = sell.get((dc, sku), 0) + shifted * split / C.SKUS[sku]["upc"]
    for k in sell:
        sell[k] = sell[k] * np.exp(rng.normal(0, 0.21, n) - 0.21 ** 2 / 2)

    def net_usd_case(dc, sku):
        m = C.DCS[dc]["country"]
        sd = C.SKUS[sku]
        promo_share = sum(v for c, v in C.MARKETS[m]["channels"].items() if c in PROMO_CH)
        return sd["upc"] * sd["price"] * usd_idx * (1 - 0.75 * our_promo[(m, sku)] * promo_share)

    rev52 = sum((sell[k] * net_usd_case(*k))[HIST - 52:HIST].sum() for k in sell)
    K = cfg["demo"]["annual_revenue_usd"] / rev52
    for k in sell:
        sell[k] *= K
    for k in units:
        units[k] *= K
    for k in value_exp:
        value_exp[k] *= K

    sellin_rows = []
    for (dc, sku), q in sell.items():
        m = C.DCS[dc]["country"]
        promo_share = sum(v for c, v in C.MARKETS[m]["channels"].items() if c in PROMO_CH)
        sellin_rows.append(pd.DataFrame({
            "WEEK_START": weeks.week_start[:HIST], "ISO_YEAR": weeks.iso_year[:HIST], "ISO_WEEK": weeks.iso_week[:HIST],
            "WERKS": dc, "MATNR": sku, "COUNTRY": m, "QTY_CS": np.round(q[:HIST], 1),
            "NET_USD": np.round((q * net_usd_case(dc, sku))[:HIST], 2),
            "PROMO_DEPTH": our_promo[(m, sku)][:HIST] * promo_share,
            "TEMP_C": temp[C.DCS[dc]["region"]][:HIST]}))
    sellin = pd.concat(sellin_rows, ignore_index=True)

    pos = pd.concat(pos_rows, ignore_index=True)
    pos["UNITS"] = (pos["UNITS"] * K).round(0)
    pos["VALUE_LC"] = (pos["UNITS"] * pos["SHELF_PRICE_LC"]).round(2)

    # ---------------- category share by player ----------------
    sh_base = {m: dict(zip(["Northstar", "Helvetia", "Andina Dulces", "Private label"], v)) for m, v in C.SHARE_BASE.items()}
    our_val = pos.groupby(["REGION", "CHANNEL", "WEEK_START"])["VALUE_LC"].sum()
    for (r, ch), vexp in value_exp.items():
        m = C.REGIONS[r]["country"]
        sb = sh_base[m]
        others = 100 - sum(sb.values())
        cat = vexp[:HIST] / (sb["Northstar"] / 100)
        hel_promo = comp_promo.get((m, "100045"), np.zeros(n))[:HIST].copy() if ch in PROMO_CH else np.zeros(HIST)
        for i, d in region_comp_cut.get((r, "100045", ch), {}).items():
            if i < HIST:
                hel_promo[i] = d
        hel = cat * sb["Helvetia"] / 100 * (1 + 0.35 * ((1 - hel_promo) ** -1.9 - 1)) * np.exp(rng.normal(0, 0.03, HIST))
        andina = cat * sb["Andina Dulces"] / 100 * np.exp(rng.normal(0, 0.04, HIST))
        pl_growth = 1.08 ** years[:HIST] if ch == "DISC" else 1.0
        pl = cat * sb["Private label"] / 100 * pl_growth * np.exp(rng.normal(0, 0.04, HIST))
        oth = cat * others / 100 * np.exp(rng.normal(0, 0.03, HIST))
        ours = our_val.loc[(r, ch)].reindex(weeks.week_start[:HIST]).fillna(0).values
        for player, vals in (("Northstar", ours), ("Helvetia", hel), ("Andina Dulces", andina), ("Private label", pl), ("Others", oth)):
            share_rows.append(pd.DataFrame({"WEEK_START": weeks.week_start[:HIST], "COUNTRY": m, "REGION": r, "CHANNEL": ch,
                                            "PLAYER": player, "VALUE_LC": np.round(vals, 2)}))
    pos_share = pd.concat(share_rows, ignore_index=True)

    # ---------------- master data ----------------
    t001w = pd.DataFrame([dict(WERKS=k, NAME1=v["name"], TYPE="PLANT", LAND1=v["country"], CITY=v["city"], LAT=v["lat"], LON=v["lon"]) for k, v in C.PLANTS.items()]
                         + [dict(WERKS=k, NAME1=v["name"], TYPE="DC", LAND1=v["country"], CITY=v["code"], LAT=v["lat"], LON=v["lon"]) for k, v in C.DCS.items()])
    mara = pd.DataFrame([dict(MATNR=k, MAKTX=v["name"], BRAND=v["brand"], NTGEW_G=v["grams"], UNITS_PER_CS=v["upc"],
                              NET_PRICE_USD=v["price"], COGS_USD=v["cogs"], MHDHB_DAYS=v["life"], SEASONAL=v.get("seasonal", ""))
                         for k, v in C.SKUS.items()])

    # ---------------- stock, MRP, open orders, PIRs, planned receipts ----------------
    plant_for = lambda dc: "MX01" if dc in ("MX1D", "MX3D", "MX5D", "MX4D") else "MX02" if dc == "MX2D" else "BR01" if dc.startswith("BR") else ("BR01" if C.DCS[dc]["country"] in ("CL", "AR") else "MX01")
    mard, marc, vbap, pbed, plaf, batches = [], [], [], [], [], []
    plnum = 451200
    planted_dos = {("MX2D", "100058"): 70, ("BR3D", "100045"): 9, ("BR3D", "100012"): 8, ("CO3D", "100061"): 88,
                   ("BR2D", "100051"): 5, ("PE1D", "100031"): 12, ("PE2D", "100031"): 52, ("MX5D", "100059"): 0, ("MX3D", "100059"): 0}
    t0 = today()
    for (dc, sku), q in sell.items():
        hist = q[:HIST]
        if hist[HIST - 26:].sum() < 1:
            continue
        sd = C.SKUS[sku]
        recent_daily = hist[HIST - 4:].mean() / 7.0
        cur_daily = hist[cur_i] / 7.0
        avg8 = hist[HIST - 8:].mean() / 7.0
        if (dc, sku) == ("MX1D", "100058"):
            stock = 4.4 * cur_daily
        elif sd.get("seasonal") == "muertos":
            peak = hist[cur_i - 4:cur_i + 1].max()
            stock = 0.9 * peak if dc in ("MX3D", "MX5D") else 0.15 * peak
        elif sd.get("seasonal"):
            stock = rng.uniform(0.6, 1.2) * hist[cur_i] + 50
        else:
            stock = planted_dos.get((dc, sku), rng.uniform(9, 38)) * recent_daily
        stock = round(max(stock, 0) / 10) * 10
        mard.append(dict(MATNR=sku, WERKS=dc, LGORT="0001", LABST=stock, DATE=t0))
        marc.append(dict(MATNR=sku, WERKS=dc, DISMM="PD", DISLS="EX", EISBE=round(5 * avg8 / 10) * 10, PLIFZ=2 if C.DCS[dc]["country"] in ("MX", "BR") else 9))
        # batches / shelf life
        remaining = stock
        nb = 1 if stock < 200 else int(rng.integers(2, 4))
        for b in range(nb):
            qty = remaining if b == nb - 1 else round(remaining * rng.uniform(0.3, 0.6) / 10) * 10
            remaining -= qty
            if sd.get("seasonal") == "muertos":
                days_left = 52
            elif sd.get("seasonal"):
                days_left = int(rng.uniform(90, 150))
            else:
                days_left = int(rng.uniform(0.25, 0.95) * sd["life"])
                if rng.random() < 0.04:
                    days_left = int(rng.uniform(20, 58))
            batches.append(dict(MATNR=sku, WERKS=dc, CHARG=f"B{rng.integers(10000, 99999)}", CLABS=qty, VFDAT=t0 + timedelta(days=days_left)))
        # open customer orders for the next 7 days
        for d, frac in enumerate([0.75, 0.65, 0.5, 0.38, 0.26, 0.16, 0.1], start=1):
            qty = round(cur_daily * frac * rng.uniform(0.9, 1.1))
            if qty > 0:
                vbap.append(dict(VBELN=f"00012{rng.integers(10000, 99999)}", POSNR="000010", MATNR=sku, WERKS=dc, EDATU=t0 + timedelta(days=d), KWMENG=qty))
        # PIRs = SAP statistical baseline: current week from last week's run, then the run after this week
        base = np.concatenate([sap_baseline(hist, 1, origin=cur_i), sap_baseline(hist, 26, origin=HIST)])
        for k in range(27):
            ws = weeks.week_start[cur_i + k]
            pbed.append(dict(MATNR=sku, WERKS=dc, VERSB="00", PDATU=ws, ISO_WEEK=int(weeks.iso_week[cur_i + k]), PLNMG=round(base[k])))
        # planned replenishment receipts (MRP covers each week's PIR)
        for k in range(0, 5):
            if (dc, sku) == ("MX1D", "100058") and k == 0:
                continue
            ws = weeks.week_start[cur_i + k]
            rdate = (t0 + timedelta(days=3)) if k == 0 else ws + timedelta(days=2)
            qty = round(base[k] * (0.45 if k == 0 else 1.0) / 10) * 10
            if qty <= 0:
                continue
            plnum += 1
            src = plant_for(dc)
            kind = "PlOrd" if C.DCS[dc]["country"] in ("MX", "BR") else "ShpgNt"
            num = "0000451221" if (dc, sku, k) == ("MX1D", "100058", 1) else f"0000{plnum}"
            plaf.append(dict(PLNUM=num, MATNR=sku, PLWRK=src, WERKS=dc, PSTTR=rdate, GSMNG=qty, TYPE=kind))

    # ---------------- Peru delivery stops for the route optimizer ----------------
    stops = []
    plan = dict(LIM=64, HUA=3, HCH=3, BAR=2, CHB=4, TRU=6, CIX=5, PIU=4, CHN=2, PIS=2, ICA=4, NAZ=2, CMN=1, MOQ=2, TAC=3,
                MAT=1, ORY=2, TAR=3, JAU=4, HYO=9, CNT=1, CPS=3, HCO=3, HTA=1, AYA=3, JUL=4, PUN=2, CUZ=6, ABA=2, PQO=1, AQP=10)
    urgent_towns = {"ORY", "TAR", "JAU", "HYO"}
    sid = 0
    for town, k in plan.items():
        _, lat, lon = C.PE_NODES[town]
        for j in range(k):
            sid += 1
            spread = 0.11 if town == "LIM" else (0.06 if town == "AQP" else 0.015)
            stops.append(dict(STOP_ID=f"PE{sid:03d}", TOWN=town, LAT=lat + rng.normal(0, spread), LON=lon + rng.normal(0, spread),
                              DEMAND_CS=int(rng.integers(30, 120) if town in ("LIM", "AQP") else rng.integers(60, 220)),
                              URGENT=town in urgent_towns and rng.random() < 0.7, HOT=town in C.HOT_TOWNS,
                              CUSTOMER=("Bodega" if rng.random() < 0.6 else "Distribuidor") + f" {town.title()} {j + 1}"))

    # ---------------- external signals ----------------
    trend_defs = [("zero_sugar", "Sin azúcar / zero sugar", ["MX", "CO", "CL"], 0.38), ("premium_dark", "Premium dark 70%+", ["BR", "CL", "MX"], 0.22),
                  ("single_serve", "Single-serve ≤ MXN 10 / R$ 3", ["MX", "BR", "CO", "PE"], 0.17), ("gifting", "Gifting · Navidad & Páscoa", ["BR", "MX"], 0.11),
                  ("value_seeking", "Value seeking: discount & atacarejo", ["BR", "CO", "PE"], 0.14), ("protein", "Protein / better-for-you", ["MX", "CL"], 0.09)]
    trends = []
    for code, label, mkts, yoy in trend_defs:
        g = (1 + yoy) ** (1 / 52)
        v = 100.0
        for i in range(HIST):
            v *= g * math.exp(rng.normal(0, 0.012))
            trends.append(dict(TREND=code, LABEL=label, MARKETS=",".join(mkts), WEEK_START=weeks.week_start[i], INDEX=round(v, 2)))
    macro = []
    for m, md in C.MARKETS.items():
        for mo in range(34):
            y, mm = 2024 + mo // 12, mo % 12 + 1
            cpi = (0.022 + rng.normal(0, 0.003)) if m == "AR" else INFLATION[m] / 12 + rng.normal(0, 0.0015)
            fx = md["fx"] * ((1.018 ** (mo - 33)) if m == "AR" else (1 + rng.normal(0, 0.01)))
            macro.append(dict(COUNTRY=m, MONTH=date(y, mm, 1), CPI_MOM=round(cpi, 4), FX_PER_USD=round(fx, 2)))
    last_ar = max(i for i, row in enumerate(macro) if row["COUNTRY"] == "AR")
    macro[last_ar]["CPI_MOM"] = 0.021
    cocoa_vals = [100, 108, 121, 138, 152, 149, 141, 146, 158, 162, 155, 149, 151, 147, 139, 133, 128, 131, 136, 140, 137, 134,
                  138, 141, 143, 140, 137, 139, 141, 144, 142, 140, 141, 141]
    cocoa = pd.DataFrame({"MONTH": [date(2024 + i // 12, i % 12 + 1, 1) for i in range(34)], "INDEX": cocoa_vals})
    river = pd.DataFrame({"WEEK_START": weeks.week_start[:HIST],
                          "LEVEL_M": np.round(22 + 6 * np.cos(2 * np.pi * (weeks.iso_week[:HIST].values - 25) / 52) - np.where(years[:HIST] > -0.2, 1.6, 0) + rng.normal(0, 0.3, HIST), 2)})
    pre = []
    for season, easter, mult in ((2026, C.EASTER[2026], 1.0), (2027, C.EASTER[2027], 1.11)):
        cum = 0.0
        for wb in range(30, 21, -1):
            cum += 900 * mult * (1 + (30 - wb) * 0.25) * rng.uniform(0.95, 1.05)
            pre.append(dict(SEASON=season, WEEKS_BEFORE_EASTER=wb, CUM_CASES=round(cum * K / 6)))
    promo_plan = pd.DataFrame([
        dict(PROMO="Fiesta Bites 150g · Día de Muertos display", MATNR="100058", START_WEEK=43, WEEKS=2, MECHANIC="Display + 2x MXN 150", ROI=1.8, STATUS="running"),
        dict(PROMO="Dulcera Milk 90g · TPR (response to competitor)", MATNR="100045", START_WEEK=44, WEEKS=3, MECHANIC="TPR", ROI=None, STATUS="ai_draft"),
        dict(PROMO="Dulcera Milk 40g · Buen Fin 3x2", MATNR="100041", START_WEEK=46, WEEKS=1, MECHANIC="3x2 (−33%)", ROI=0.9, STATUS="planned"),
        dict(PROMO="Dulcera Milk 90g · Buen Fin TPR −15%", MATNR="100045", START_WEEK=46, WEEKS=1, MECHANIC="TPR −15%", ROI=1.3, STATUS="planned"),
        dict(PROMO="Rayo 12g · tienda pre-venta incentive", MATNR="100012", START_WEEK=47, WEEKS=4, MECHANIC="Retailer incentive", ROI=1.2, STATUS="planned"),
        dict(PROMO="Crunchita 35g · convenience combo", MATNR="100031", START_WEEK=45, WEEKS=4, MECHANIC="Combo with beverage", ROI=1.1, STATUS="planned"),
        dict(PROMO="Cacao Alto · Navidad gift pack", MATNR="100063", START_WEEK=49, WEEKS=4, MECHANIC="Gift pack + display", ROI=1.5, STATUS="planned"),
    ])
    future_promos = []
    for (m, sku), arr in our_promo.items():
        for i in range(HIST, n):
            if arr[i] > 0:
                future_promos.append(dict(COUNTRY=m, MATNR=sku, WEEK_START=weeks.week_start[i], ISO_WEEK=int(weeks.iso_week[i]), DEPTH=arr[i]))
    comp_feed = pd.DataFrame([
        dict(WHEN="Yesterday", TEXT="Andina Dulces launches an 18g wafer at COP 1,500 in Colombian tiendas", SOURCE="Shelf audit", TYPE="Launch"),
        dict(WHEN="Mon", TEXT="Private-label 100g tablet enters atacarejo São Paulo at R$ 6.99", SOURCE="Retailer portal", TYPE="Entry"),
        dict(WHEN="Fri", TEXT="Helvetia pre-sells Páscoa 2027 to key accounts 2 weeks earlier than last year", SOURCE="Field sales notes", TYPE="Seasonal"),
        dict(WHEN="Thu", TEXT="Andina Dulces raises list prices 8% in Argentina, its 2nd increase in 6 weeks", SOURCE="Price tracker", TYPE="Price"),
    ])
    shipments = []
    for i in range(3200):
        dc = list(C.DCS)[int(rng.integers(0, len(C.DCS)))]
        shipments.append(dict(TKNUM=f"{7700000 + i}", WERKS=dc, DATBG=t0 - timedelta(days=int(rng.integers(0, 90))), LOADS=1, KM=int(rng.integers(20, 1200))))

    tables = {
        "WEEKS": weeks, "T001W": t001w, "MARA": mara, "MARC": pd.DataFrame(marc), "MARD": pd.DataFrame(mard), "MCHB": pd.DataFrame(batches),
        "VBAP_OPEN": pd.DataFrame(vbap), "PBED": pd.DataFrame(pbed), "PLAF": pd.DataFrame(plaf), "SELLIN_WEEKLY": sellin,
        "POS_WEEKLY": pos, "POS_SHARE": pos_share, "PROMO_FUTURE": pd.DataFrame(future_promos), "PROMO_PLAN_MX": promo_plan,
        "PE_STOPS": pd.DataFrame(stops), "TRENDS": pd.DataFrame(trends), "MACRO": pd.DataFrame(macro), "COCOA": cocoa,
        "RIVER_NEGRO": river, "PREORDERS_PASCOA": pd.DataFrame(pre), "COMP_FEED": comp_feed, "VTTK": pd.DataFrame(shipments),
    }
    DATA.mkdir(exist_ok=True)
    EXTRACTS.mkdir(exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = duckdb.connect(str(tmp))
    for name, df in tables.items():
        con.register("df_view", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM df_view")
        con.unregister("df_view")
        if name in ("T001W", "MARA", "MARC", "MARD", "MCHB", "VBAP_OPEN", "PBED", "PLAF", "SELLIN_WEEKLY", "VTTK"):
            con.execute(f"COPY {name} TO '{EXTRACTS / (name.lower() + '.parquet')}' (FORMAT PARQUET)")
    con.close()
    tmp.replace(DB_PATH)
    return {name: len(df) for name, df in tables.items()} | {"seconds": round(time.time() - t_start, 1), "scale_K": round(K, 4)}


if __name__ == "__main__":
    for k, v in generate().items():
        print(f"{k:18s} {v}")
