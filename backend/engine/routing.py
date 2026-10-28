"""Risk-aware distribution routing for the Peru network (OR-Tools VRP with time windows).

Legacy plan: cost-only routing that ignores heat and road risk, solved before any disruption.
AI plan: risk-weighted cost (freight + λ·risk), reefer required in hot towns, re-solved around road closures,
with non-urgent stops deferrable when serving them is riskier than a 36 h delay.
"""
from __future__ import annotations

import heapq
import math
import time

import numpy as np

from .. import catalog as C
from ..store import store

try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    HAVE_ORTOOLS = True
except Exception:  # pragma: no cover
    HAVE_ORTOOLS = False

FLEET = [("LUR", 12, 4), ("AQP", 6, 2)]     # depot, vehicles, of which reefer
CAPACITY = 1400                              # cases per truck
SERVICE_MIN = 25
RATE = dict(dry=3.9, reefer=5.2)             # PEN per km
FIXED = 350                                  # PEN per truck used
CASE_VALUE = 165                             # PEN net revenue per case
LAMBDA = 0.35
URBAN_KMH = 24
VIEW = [-78.6, -69.6, -17.1, -10.1]
WAYPOINTS = {"CNT", "HLY", "MAT", "TIC", "PIS", "AYA", "PQO", "JUL", "ORY", "CPS"}


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class Network:
    def __init__(self, closed: set[tuple[str, str]] = frozenset()):
        self.adj: dict[str, list] = {n: [] for n in C.PE_NODES}
        for a, b, km_, cls, ls, sec, alt in C.PE_EDGES:
            if (a, b) in closed or (b, a) in closed:
                continue
            hrs = km_ / C.ROAD_SPEED[cls] * (1.25 if cls == "unpaved" else 1.0)
            risk = (ls + sec) * km_
            e = dict(km=km_, h=hrs, risk=risk, cls=cls, sec=sec, ls=ls, alt=alt)
            self.adj[a].append((b, e))
            self.adj[b].append((a, e))
        self.paths = {n: self._dijkstra(n) for n in C.PE_NODES}

    def _dijkstra(self, src):
        dist = {src: (0.0, 0.0, 0.0)}
        prev = {}
        pq = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u][0] + 1e-9:
                continue
            for v, e in self.adj[u]:
                nd = d + e["h"]
                if v not in dist or nd < dist[v][0] - 1e-9:
                    dist[v] = (nd, dist[u][1] + e["km"], dist[u][2] + e["risk"])
                    prev[v] = (u, e)
                    heapq.heappush(pq, (nd, v))
        return dist, prev

    def route(self, a, b):
        """hours, km, risk-km, list of (from, to, edge) legs."""
        dist, prev = self.paths[a]
        if b not in dist:
            return None
        legs, cur = [], b
        while cur != a:
            p, e = prev[cur]
            legs.append((p, cur, e))
            cur = p
        h, k, r = dist[b]
        return h, k, r, legs[::-1]


class Router:
    def __init__(self):
        self.stops = store().table("PE_STOPS").reset_index(drop=True)
        self.cache: dict = {}

    def _nodes(self):
        st = self.stops
        nodes = [dict(id="LUR", town="LUR", lat=C.PE_NODES["LUR"][1], lon=C.PE_NODES["LUR"][2], demand=0, urgent=False, hot=False, depot=True),
                 dict(id="AQP", town="AQP", lat=C.PE_NODES["AQP"][1], lon=C.PE_NODES["AQP"][2], demand=0, urgent=False, hot=False, depot=True)]
        for r in st.itertuples():
            nodes.append(dict(id=r.STOP_ID, town=r.TOWN, lat=r.LAT, lon=r.LON, demand=int(r.DEMAND_CS), urgent=bool(r.URGENT), hot=bool(r.HOT),
                              customer=r.CUSTOMER, depot=False))
        return nodes

    def _matrices(self, net: Network, nodes, lam: float):
        n = len(nodes)
        T = np.zeros((n, n), dtype=np.int64)
        K = np.zeros((n, n))
        R = np.zeros((n, n))
        center = {t: (C.PE_NODES[t][1], C.PE_NODES[t][2]) for t in C.PE_NODES}
        loc = [hav((x["lat"], x["lon"]), center[x["town"]]) * 1.3 for x in nodes]
        big = 10 ** 7
        for i, a in enumerate(nodes):
            for j, b in enumerate(nodes):
                if i == j:
                    continue
                if a["town"] == b["town"]:
                    km_ = hav((a["lat"], a["lon"]), (b["lat"], b["lon"])) * 1.3
                    hrs, risk = km_ / URBAN_KMH, 0.0
                else:
                    r = net.route(a["town"], b["town"])
                    if r is None:
                        T[i, j], K[i, j], R[i, j] = big, 1e5, 0
                        continue
                    hrs = r[0] + (loc[i] + loc[j]) / URBAN_KMH
                    km_, risk = r[1] + loc[i] + loc[j], r[2]
                T[i, j] = int(round(hrs * 60)) + (0 if b["depot"] else SERVICE_MIN)
                K[i, j], R[i, j] = km_, risk
        return T, K, R

    def solve(self, closed: tuple, lam: float, reefer_rule: bool, allow_defer: bool) -> dict:
        key = (closed, lam, reefer_rule, allow_defer)
        if key in self.cache:
            return self.cache[key]
        t0 = time.time()
        net = Network(set(closed))
        nodes = self._nodes()
        T, K, R = self._matrices(net, nodes, lam)
        n = len(nodes)
        vehicles = []
        for depot, count, reefers in FLEET:
            for v in range(count):
                vehicles.append(dict(depot=0 if depot == "LUR" else 1, reefer=v < reefers, name=f"{depot}-{len(vehicles) + 1:02d}"))
        starts = [v["depot"] for v in vehicles]
        manager = pywrapcp.RoutingIndexManager(n, len(vehicles), starts, starts)
        routing = pywrapcp.RoutingModel(manager)
        # open routes: returning to the depot is free
        T_open, K_open, R_open = T.copy(), K.copy(), R.copy()
        T_open[:, :2] = 0
        K_open[:, :2] = 0
        R_open[:, :2] = 0
        cost_cbs = {}
        for vi, v in enumerate(vehicles):
            rate = RATE["reefer" if v["reefer"] else "dry"]
            mat = (K_open * rate + lam * R_open * 100).astype(np.int64)
            ck = (rate,)
            if ck not in cost_cbs:
                cost_cbs[ck] = routing.RegisterTransitCallback(lambda i, j, m=mat: int(m[manager.IndexToNode(i), manager.IndexToNode(j)]))
            routing.SetArcCostEvaluatorOfVehicle(cost_cbs[ck], vi)
            routing.SetFixedCostOfVehicle(FIXED, vi)
        tcb = routing.RegisterTransitCallback(lambda i, j: int(T_open[manager.IndexToNode(i), manager.IndexToNode(j)]))
        routing.AddDimension(tcb, 0, 36 * 60, True, "Time")
        time_dim = routing.GetDimensionOrDie("Time")
        dcb = routing.RegisterUnaryTransitCallback(lambda i: nodes[manager.IndexToNode(i)]["demand"])
        routing.AddDimensionWithVehicleCapacity(dcb, 0, [CAPACITY] * len(vehicles), True, "Load")
        reefer_ids = [i for i, v in enumerate(vehicles) if v["reefer"]]
        for idx in range(2, n):
            nd = nodes[idx]
            ri = manager.NodeToIndex(idx)
            hi = 14 * 60 if nd["town"] in ("LIM", "AQP") else (24 * 60 if nd["urgent"] else 34 * 60)
            time_dim.CumulVar(ri).SetRange(0, hi)
            if reefer_rule and nd["hot"]:
                routing.VehicleVar(ri).SetValues([-1] + reefer_ids)
            # deferring a non-urgent drop 36 h costs ~25% of its value (customer goodwill, lost impulse sales)
            penalty = 10 ** 8 if nd["urgent"] else (int(nd["demand"] * CASE_VALUE * 0.25) if allow_defer else 10 ** 7)
            routing.AddDisjunction([ri], penalty)
        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.solution_limit = 120
        params.time_limit.seconds = 6
        sol = routing.SolveWithParameters(params)
        routes, dropped = [], []
        if sol:
            for vi, v in enumerate(vehicles):
                idx = routing.Start(vi)
                seq = []
                while not routing.IsEnd(idx):
                    node = manager.IndexToNode(idx)
                    seq.append(node)
                    idx = sol.Value(routing.NextVar(idx))
                if len(seq) > 1:
                    routes.append(dict(vehicle=v["name"], reefer=v["reefer"], seq=seq))
            served = {s for r in routes for s in r["seq"]}
            dropped = [i for i in range(2, n) if i not in served]
        out = dict(nodes=nodes, routes=routes, dropped=dropped, solve_s=round(time.time() - t0, 1), closed=closed,
                   lam=lam, reefer_rule=reefer_rule, solver="OR-Tools VRP-TW" if HAVE_ORTOOLS else "heuristic")
        self.cache[key] = out
        return out

    # --------------------------------------------------------------- evaluation
    def evaluate(self, plan: dict, closed: tuple) -> dict:
        """Replay a plan on today's road network (with closures), at 06:00 dispatch."""
        net = Network(set(closed))
        plan_net = Network(set(plan["closed"]))
        nodes = plan["nodes"]
        res = dict(on_time=0, demand=0, cost=0.0, km=0.0, risk_exposure=0.0, melt=0, late_stops=[], routes=[])
        for r in plan["routes"]:
            t_min, blocked, km_tot, path, via = 0.0, False, 0.0, [], []
            stops_out = []
            seq = r["seq"]
            route_melt = False
            for a, b in zip(seq, seq[1:]):
                A, B = nodes[a], nodes[b]
                if A["town"] == B["town"]:
                    km_ = hav((A["lat"], A["lon"]), (B["lat"], B["lon"])) * 1.3
                    hrs, legs = km_ / URBAN_KMH, []
                else:
                    planned = plan_net.route(A["town"], B["town"])
                    legs = planned[3] if planned else []
                    uses_closed = any((x, y) in closed or (y, x) in closed for x, y, _ in legs)
                    if uses_closed:
                        blocked = True
                    hrs, km_ = (planned[0], planned[1]) if planned else (99, 0)
                for x, y, e in legs:
                    res["risk_exposure"] += e["risk"] / 100
                    path.append((C.PE_NODES[x][1], C.PE_NODES[x][2]))
                    if y in WAYPOINTS and y not in via:
                        via.append(y)
                path.append((B["lat"], B["lon"]))
                t_min += hrs * 60 + SERVICE_MIN
                km_tot += km_
                hi = 14 * 60 if B["town"] in ("LIM", "AQP") else (24 * 60 if B["urgent"] else 34 * 60)
                ok = (not blocked) and t_min <= hi + 1
                if B["hot"] and not r["reefer"]:
                    route_melt = True
                res["demand"] += B["demand"]
                if ok:
                    res["on_time"] += B["demand"]
                else:
                    res["late_stops"].append(b)
                stops_out.append(dict(id=B["id"], town=B["town"], eta_h=round(t_min / 60, 1), ok=ok))
            res["melt"] += int(route_melt)
            rate = RATE["reefer" if r["reefer"] else "dry"]
            res["cost"] += km_tot * rate + FIXED
            res["km"] += km_tot
            start = nodes[seq[0]]
            towns = _towns(nodes, seq)
            res["routes"].append(dict(vehicle=r["vehicle"], reefer=r["reefer"], blocked=blocked, km=round(km_tot), stops=stops_out,
                                      path=[(start["lat"], start["lon"])] + path, towns=towns, via=[v for v in via if v not in towns]))
        for d in plan["dropped"]:
            res["demand"] += nodes[d]["demand"]
            res["late_stops"].append(d)
        res["on_time_pct"] = res["on_time"] / max(res["demand"], 1)
        res["sales_at_risk"] = sum(nodes[i]["demand"] for i in res["late_stops"]) * CASE_VALUE
        return res

    def payload(self, scenarios: tuple) -> dict:
        closed = (C.HUAICO_EDGE,) if "huaico_pe" in scenarios else ()
        legacy = self.solve((), 0.0, False, False)
        ai = self.solve(closed, LAMBDA, True, bool(closed))
        ev_legacy = self.evaluate(legacy, closed)
        ev_ai = self.evaluate(ai, closed)
        nodes = ai["nodes"]
        deferred = [nodes[i] for i in ai["dropped"]]
        kpis = [
            ("On-time delivery", f"{ev_legacy['on_time_pct'] * 100:.0f}%", f"{ev_ai['on_time_pct'] * 100:.0f}%", ev_ai["on_time_pct"] >= ev_legacy["on_time_pct"]),
            ("Freight cost", f"S/ {ev_legacy['cost'] / 1e3:.1f}k", f"S/ {ev_ai['cost'] / 1e3:.1f}k ({(ev_ai['cost'] / ev_legacy['cost'] - 1) * 100:+.1f}%)", ev_ai["cost"] <= ev_legacy["cost"]),
            ("Sales at risk", f"S/ {ev_legacy['sales_at_risk'] / 1e6:.2f}M", f"S/ {ev_ai['sales_at_risk'] / 1e6:.2f}M", ev_ai["sales_at_risk"] <= ev_legacy["sales_at_risk"]),
            ("Melt-risk loads (dry truck > 28°C)", str(ev_legacy["melt"]), str(ev_ai["melt"]), ev_ai["melt"] <= ev_legacy["melt"]),
            ("Road-risk exposure index", f"{ev_legacy['risk_exposure']:.0f}", f"{ev_ai['risk_exposure']:.0f}", ev_ai["risk_exposure"] <= ev_legacy["risk_exposure"]),
            ("Stops deferred (customer notified)", "0", str(len(deferred)), True),
        ]
        changed = [r for r in ev_ai["routes"] if any(t in ("HYO", "JAU", "TAR", "ORY", "CPS", "HCO", "CUZ", "JUL", "AYA", "ICA", "NAZ") for t in r["towns"])]
        cards = []
        for r in sorted(changed, key=lambda r: -r["km"])[:4]:
            title = " → ".join(C.PE_NODES[t][0] for t in r["towns"])
            flags = []
            if r["via"]:
                flags.append("via " + "–".join(C.PE_NODES[v][0] for v in r["via"]))
            if "CNT" in r["via"] or "HLY" in r["via"]:
                flags.append("unpaved segment: daylight only, escort advised")
            if r["reefer"]:
                flags.append("reefer")
            last = r["stops"][-1]["eta_h"] if r["stops"] else 0
            cards.append(dict(vehicle=r["vehicle"], title=title, detail=f"{len(r['stops'])} stops · {r['km']:,} km · last drop +{last:.0f} h" + (f" · {' · '.join(flags)}" if flags else ""),
                              color="neg" if r["blocked"] else ("gold" if r["vehicle"].startswith("AQP") else "teal")))
        if deferred:
            towns = sorted({C.PE_NODES[d['town']][0] for d in deferred})
            cards.append(dict(vehicle="—", title=f"{len(deferred)} non-urgent stops held 36 h", detail=f"{', '.join(towns)} · re-planned when the road reopens · customers notified via pre-venta app", color="tx3"))
        map_routes = []
        for r in ev_legacy["routes"]:
            if r["blocked"]:
                map_routes.append(dict(kind="blocked", pts=_clip(r["path"])))
        for r in ev_ai["routes"]:
            map_routes.append(dict(kind="ai" if any(t in r["towns"] for t in ("HYO", "JAU", "TAR", "ORY", "CPS", "HCO")) else ("south" if nodes[0] and r["vehicle"].startswith("AQP") else "other"),
                                   pts=_clip(r["path"])))
        return dict(
            disruption="huaico_pe" in scenarios, closed_edge=list(C.HUAICO_EDGE), solver=ai["solver"], solve_s=ai["solve_s"] + legacy["solve_s"],
            stops=len(nodes) - 2, vehicles=sum(f[1] for f in FLEET), used=len(ai["routes"]), kpis=kpis, cards=cards,
            map=dict(view=VIEW, routes=map_routes, towns=[dict(code=k, name=v[0], lat=v[1], lon=v[2]) for k, v in C.PE_NODES.items()],
                     closure=dict(lat=(C.PE_NODES["SMT"][1] + C.PE_NODES["TIC"][1]) / 2, lon=(C.PE_NODES["SMT"][2] + C.PE_NODES["TIC"][2]) / 2) if closed else None),
            ev_ai=dict(on_time=ev_ai["on_time_pct"], cost=ev_ai["cost"], sales_at_risk=ev_ai["sales_at_risk"], melt=ev_ai["melt"], deferred=len(deferred)),
            ev_legacy=dict(on_time=ev_legacy["on_time_pct"], cost=ev_legacy["cost"], sales_at_risk=ev_legacy["sales_at_risk"], melt=ev_legacy["melt"]),
            lanes=lane_risk(scenarios),
        )


def _towns(nodes, seq):
    out = []
    for i in seq:
        t = nodes[i]["town"]
        if not out or out[-1] != t:
            out.append(t)
    return out


def _clip(pts):
    out = []
    for p in pts:
        if not out or abs(out[-1][0] - p[0]) + abs(out[-1][1] - p[1]) > 0.02:
            out.append((round(p[0], 3), round(p[1], 3)))
    return out


LANES = [
    ("PE · Lima → Huancayo (Carretera Central)", "Road", "Landslide-prone in rainy season", 52, "Monitor road alerts", "huaico_pe", 42, "Closed at km 98 · use the Canta route"),
    ("BR · Jundiaí → Manaus", "Road + river", "River level seasonal low", 48, "Book barge slots early", "rionegro_br", 30, "Barge capacity −35% · pre-build 3 weeks of stock"),
    ("MX · Monterrey → CDMX (57D)", "Road", "Cargo-theft corridor Querétaro–Edomex", 71, "Convoy window 06:00–15:00, GPS lock", None, 0, ""),
    ("MX · Monterrey → Mérida", "Road", "Heat, melt risk", 44, "Reefer above 28°C", "heat_mx", 22, "41°C forecast · reefer + 04:00 dispatch"),
    ("BR · Cajamar → Recife (BR-116)", "Road", "Long haul, fatigue", 35, "Two-driver teams", "strike_br", 40, "Trucker blockades 48 h · re-sequence via BR-101"),
    ("PE · Lima → Huancayo via Canta", "Road", "Unpaved segments, altitude", 58, "Daylight only, escort", None, 0, ""),
    ("CL · Santiago ← Buenos Aires (Cristo Redentor)", "Road", "Snow closure risk (seasonal)", 46, "Sea backup via San Antonio", None, 0, ""),
    ("CO · Bogotá → Barranquilla", "Road", "Rain on Ruta del Sol", 38, "Monitor", None, 0, ""),
    ("PE · Arequipa → Cusco", "Road", "Altitude 4,300 m", 33, "OK", None, 0, ""),
]


def lane_risk(scenarios: tuple) -> list[dict]:
    out = []
    for name, mode, risk, score, action, scn, add, scn_action in LANES:
        active = scn is not None and scn in scenarios
        out.append(dict(lane=name, mode=mode, risk=scn_action.split(" · ")[0] if active else risk, score=min(score + (add if active else 0), 99),
                        action=scn_action if active else action, active=active))
    out.sort(key=lambda r: -r["score"])
    return out
