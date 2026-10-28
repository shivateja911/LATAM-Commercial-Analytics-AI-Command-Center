"""End-to-end checks: the data tells the planted stories, the models find them, the LLM layer is grounded and
works with no model (cache mode), and every API endpoint responds."""
from __future__ import annotations

import time

import pytest

from backend import catalog as C
from backend.llm import GATEWAY, grounded


@pytest.fixture(scope="session", autouse=True)
def cache_mode(tmp_path_factory):
    import backend.state as st
    GATEWAY.mode = "cache"          # never load the model in tests
    st.AUDIT_LOG = tmp_path_factory.mktemp("audit") / "audit.log"
    yield


@pytest.fixture(scope="session")
def h():
    from backend.hub import hub
    return hub()


def test_revenue_scaled_to_target(h):
    si = h.com.si
    rev52 = si[si.WEEK_START > si.WEEK_START.max() - __import__("pandas").Timedelta(weeks=52)].NET_USD.sum()
    assert abs(rev52 / 1.15e9 - 1) < 0.03


def test_pricing_recovers_elasticities_and_picks_shallow_tpr(h):
    p = h.pricing
    assert -3.8 < p.e < -2.3, p.e
    assert 0.7 < p.c < 1.5, p.c
    o = p.options(p.comp_cut)
    assert any(g["ok"] == "x" for g in o["hold"]["guardrails"]), "holding price should break the price-index band"
    assert 0 < o["ai"]["depth"] < p.comp_cut
    assert o["ai"]["dgp"] > o["hold"]["dgp"] and o["ai"]["dgp"] > o["match"]["dgp"]


def test_forecast_beats_sap_baseline_without_bias(h):
    acc = h.fc.accuracy()["ALL"]
    assert acc["ai"] > acc["sap"] + 0.02
    assert abs(acc["bias_ai"]) < 0.03
    br = h.fc.bridge("MX1D", "100045")
    assert abs(sum(b["value"] for b in br if b["kind"] == "delta") - (br[-1]["value"] - br[0]["value"])) <= 8


def test_inventory_finds_cdmx_stockout_and_transfers_from_gdl(h):
    inv = h.inventory()
    s = inv["series"][("MX1D", "100058")]
    assert s["p14"] > 0.8 and s["stockout_day"] is not None
    act = next(a for a in inv["actions"] if a["kind"] == "rebalance" and a["dc"] == "MX1D")
    assert act["sto"]["donor"] == "MX2D"
    assert min(act["proj_plan"][1:15]) >= 0


def test_routing_reroutes_around_huaico(h):
    from backend.engine.routing import Network
    closed = (C.HUAICO_EDGE,)
    legacy = h.router.solve((), 0.0, False, False)
    ai = h.router.solve(closed, 0.35, True, True)
    ev_l, ev_a = h.router.evaluate(legacy, closed), h.router.evaluate(ai, closed)
    assert ev_a["on_time_pct"] > ev_l["on_time_pct"]
    assert ev_a["melt"] == 0
    hrs, km, risk, legs = Network(set(closed)).route("LUR", "HYO")
    assert not any({a, b} == set(C.HUAICO_EDGE) for a, b, _ in legs)


def test_grounding_guard():
    facts = {"x": "MXN 815k", "y": "160,857 cases", "z": "+9%", "p": "probability_14d"}
    assert grounded("Saves MXN 815k; 160.857 caixas (+9%) over 14 days", facts)[0]
    ok, bad = grounded("Revenue grew 47% to 2,345 cases", facts)
    assert not ok and bad


def test_cache_mode_works_without_model(h):
    from backend.narratives import narrative
    t0 = time.time()
    r = narrative("pricing")
    assert r["text"] and time.time() - t0 < 2


def test_copilot_routes_multilingual_questions():
    from backend.copilot import detect_lang, route
    assert route("¿Por qué estamos perdiendo participación en CDMX canal moderno esta semana?")[0] == "share_loss"
    assert detect_lang("¿Por qué estamos perdiendo participación en CDMX canal moderno esta semana?") == "es"
    assert route("Resumo da Páscoa 2027 em português")[0] == "pascoa"
    assert detect_lang("Resumo da Páscoa 2027 em português") == "pt"
    assert route("What if cocoa costs rise another 10%?") == ("cost_shock", {"pct": 10.0})
    assert route("Which DCs will stock out in the next 14 days?")[0] == "stockout_scan"


def test_scenarios_change_outputs(h):
    from backend.state import STATE
    STATE.reset()
    base = {s["id"] for s in h.signals()}
    STATE.inject("huaico_pe")
    STATE.inject("rionegro_br")
    after = {s["id"] for s in h.signals()}
    STATE.reset()
    assert {"route", "river"} <= after and not ({"route", "river"} & base)


def test_api_endpoints():
    from fastapi.testclient import TestClient
    from backend.app import app
    with TestClient(app) as c:
        for ep in ("meta", "overview", "pricing", "market", "forecast", "inventory", "routes", "sap", "demo", "copilot/suggestions"):
            r = c.get(f"/api/{ep}")
            assert r.status_code == 200, ep
        r = c.post("/api/pricing/simulate", json={"depth": 5, "weeks": 3, "comp": 12})
        assert r.status_code == 200 and r.json()["result"]["price"] == pytest.approx(37.9, abs=0.01)
        r = c.post("/api/copilot", json={"q": "Draft an STO in SAP for CDMX"})
        assert r.status_code == 200 and "code" in r.json()
        item = c.post("/api/recs/rec-sto/approve").json()
        posted = c.post(f"/api/sap/queue/{item['id']}/approve").json()
        assert posted["status"] == "posted"
        assert c.get("/").status_code == 200
