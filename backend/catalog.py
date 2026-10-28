"""Master data for the fictional company: markets, sites, products, channels, events, road network.

Shared by the data generator and the engines so both use the same definitions.
"""
from __future__ import annotations

from datetime import date, timedelta

# --------------------------------------------------------------------------------------------
# Markets. fx = local currency per USD (constant, synthetic). share = share of LATAM net revenue.
MARKETS = {
    "MX": dict(name="Mexico", ccy="MXN", fx=18.6, share=0.440, growth=0.075, plan_growth=0.085,
               centroid=(23.6, -102.5), channels=dict(TT=0.58, MT=0.24, CONV=0.10, DISC=0.04, ECOM=0.04)),
    "BR": dict(name="Brazil", ccy="BRL", fx=5.40, share=0.250, growth=0.052, plan_growth=0.070,
               centroid=(-11.0, -52.0), channels=dict(TT=0.46, MT=0.26, CONV=0.04, DISC=0.18, ECOM=0.06)),
    "CO": dict(name="Colombia", ccy="COP", fx=4100.0, share=0.103, growth=0.095, plan_growth=0.085,
               centroid=(3.5, -73.5), channels=dict(TT=0.55, MT=0.22, CONV=0.05, DISC=0.14, ECOM=0.04)),
    "PE": dict(name="Peru", ccy="PEN", fx=3.75, share=0.061, growth=0.030, plan_growth=0.070,
               centroid=(-9.8, -75.2), channels=dict(TT=0.62, MT=0.22, CONV=0.05, DISC=0.07, ECOM=0.04)),
    "CL": dict(name="Chile", ccy="CLP", fx=940.0, share=0.056, growth=0.022, plan_growth=0.055,
               centroid=(-31.0, -71.2), channels=dict(TT=0.30, MT=0.48, CONV=0.08, DISC=0.06, ECOM=0.08)),
    "AR": dict(name="Argentina", ccy="ARS", fx=1450.0, share=0.045, growth=0.120, plan_growth=0.110,
               centroid=(-37.0, -64.5), channels=dict(TT=0.52, MT=0.30, CONV=0.08, DISC=0.05, ECOM=0.05)),
    "CA": dict(name="Central America", ccy="USD", fx=1.0, share=0.045, growth=0.060, plan_growth=0.065,
               centroid=(13.6, -86.5), channels=dict(TT=0.60, MT=0.25, CONV=0.08, DISC=0.03, ECOM=0.04)),
}

CHANNELS = {
    "TT": "Traditional trade", "MT": "Modern trade", "CONV": "Convenience",
    "DISC": "Discount / atacarejo", "ECOM": "E-commerce",
}
# true price elasticities used to generate POS data (the pricing engine has to re-discover them)
OWN_ELASTICITY = dict(TT=-1.1, MT=-2.9, CONV=-1.4, DISC=-3.2, ECOM=-2.0)
CROSS_ELASTICITY = dict(TT=0.4, MT=1.1, CONV=0.5, DISC=1.2, ECOM=0.7)
SHELF_FACTOR = dict(TT=1.05, MT=1.00, CONV=1.12, DISC=0.92, ECOM=0.98)

# --------------------------------------------------------------------------------------------
# Sites. scale = relative demand weight inside its market.
PLANTS = {
    "MX01": dict(name="Plant MX01 · Monterrey", city="Monterrey", country="MX", lat=25.67, lon=-100.31),
    "MX02": dict(name="Plant MX02 · Guadalajara", city="Guadalajara", country="MX", lat=20.67, lon=-103.35),
    "BR01": dict(name="Plant BR01 · Jundiaí", city="Jundiaí", country="BR", lat=-23.19, lon=-46.88),
}
DCS = {
    "MX1D": dict(code="CDMX", name="DC CDMX (Cuautitlán)", country="MX", region="MX-CDMX", lat=19.67, lon=-99.18, scale=0.36),
    "MX2D": dict(code="GDL", name="DC Guadalajara", country="MX", region="MX-BAJ", lat=20.67, lon=-103.35, scale=0.22),
    "MX3D": dict(code="MTY", name="DC Monterrey", country="MX", region="MX-NOR", lat=25.67, lon=-100.31, scale=0.20),
    "MX4D": dict(code="MID", name="DC Mérida", country="MX", region="MX-SUR", lat=20.97, lon=-89.62, scale=0.12),
    "MX5D": dict(code="TIJ", name="DC Tijuana", country="MX", region="MX-NOR", lat=32.51, lon=-117.04, scale=0.10),
    "GT1D": dict(code="GUA", name="DC Guatemala City", country="CA", region="CA-CAM", lat=14.63, lon=-90.51, scale=0.55),
    "PA1D": dict(code="PTY", name="Hub Colón FTZ", country="CA", region="CA-CAM", lat=9.36, lon=-79.90, scale=0.45),
    "CO1D": dict(code="BOG", name="DC Bogotá (Funza)", country="CO", region="CO-AND", lat=4.71, lon=-74.21, scale=0.48),
    "CO2D": dict(code="MDE", name="DC Medellín", country="CO", region="CO-AND", lat=6.24, lon=-75.58, scale=0.27),
    "CO3D": dict(code="BAQ", name="DC Barranquilla", country="CO", region="CO-CAR", lat=10.96, lon=-74.80, scale=0.25),
    "PE1D": dict(code="LIM", name="DC Lima (Lurín)", country="PE", region="PE-LIM", lat=-12.27, lon=-76.87, scale=0.74),
    "PE2D": dict(code="AQP", name="DC Arequipa", country="PE", region="PE-SUR", lat=-16.40, lon=-71.54, scale=0.26),
    "CL1D": dict(code="SCL", name="DC Santiago (Pudahuel)", country="CL", region="CL-RM", lat=-33.44, lon=-70.79, scale=1.0),
    "AR1D": dict(code="BUE", name="DC Buenos Aires (Pilar)", country="AR", region="AR-AMBA", lat=-34.46, lon=-58.91, scale=1.0),
    "BR1D": dict(code="CAJ", name="DC Cajamar SP", country="BR", region="BR-SP", lat=-23.36, lon=-46.88, scale=0.50),
    "BR2D": dict(code="REC", name="DC Recife", country="BR", region="BR-NE", lat=-8.05, lon=-34.95, scale=0.20),
    "BR3D": dict(code="MAO", name="DC Manaus", country="BR", region="BR-NO", lat=-3.12, lon=-60.02, scale=0.10),
    "BR4D": dict(code="POA", name="DC Porto Alegre", country="BR", region="BR-SUL", lat=-30.03, lon=-51.23, scale=0.20),
}
# POS regions (sell-out panel); share = share of the market's consumer demand
REGIONS = {
    "MX-NOR": dict(name="MX · Norte", country="MX", share=0.30, hot=True),
    "MX-BAJ": dict(name="MX · Bajío", country="MX", share=0.22, hot=False),
    "MX-CDMX": dict(name="MX · CDMX metro", country="MX", share=0.36, hot=False),
    "MX-SUR": dict(name="MX · Sureste", country="MX", share=0.12, hot=True),
    "BR-SP": dict(name="BR · São Paulo", country="BR", share=0.50, hot=False),
    "BR-SUL": dict(name="BR · Sul", country="BR", share=0.20, hot=False),
    "BR-NE": dict(name="BR · Nordeste", country="BR", share=0.20, hot=True),
    "BR-NO": dict(name="BR · Norte", country="BR", share=0.10, hot=True),
    "CO-AND": dict(name="CO · Andina", country="CO", share=0.75, hot=False),
    "CO-CAR": dict(name="CO · Caribe", country="CO", share=0.25, hot=True),
    "PE-LIM": dict(name="PE · Lima", country="PE", share=0.58, hot=False),
    "PE-CEN": dict(name="PE · Sierra centro", country="PE", share=0.16, hot=False),
    "PE-SUR": dict(name="PE · Sur", country="PE", share=0.26, hot=False),
    "CL-RM": dict(name="CL · RM", country="CL", share=1.0, hot=False),
    "AR-AMBA": dict(name="AR · AMBA", country="AR", share=1.0, hot=False),
    "CA-CAM": dict(name="CAM", country="CA", share=1.0, hot=True),
}
# which DC replenishes which POS region (sell-in = shipments from that DC)
REGION_DCS = {
    "MX-NOR": {"MX3D": 0.66, "MX5D": 0.34}, "MX-BAJ": {"MX2D": 1.0}, "MX-CDMX": {"MX1D": 1.0}, "MX-SUR": {"MX4D": 1.0},
    "BR-SP": {"BR1D": 1.0}, "BR-SUL": {"BR4D": 1.0}, "BR-NE": {"BR2D": 1.0}, "BR-NO": {"BR3D": 1.0},
    "CO-AND": {"CO1D": 0.64, "CO2D": 0.36}, "CO-CAR": {"CO3D": 1.0},
    "PE-LIM": {"PE1D": 1.0}, "PE-CEN": {"PE1D": 1.0}, "PE-SUR": {"PE2D": 1.0},
    "CL-RM": {"CL1D": 1.0}, "AR-AMBA": {"AR1D": 1.0}, "CA-CAM": {"GT1D": 0.55, "PA1D": 0.45},
}

# --------------------------------------------------------------------------------------------
# Products. base = weekly cases at a reference DC; price/cogs = USD per consumer unit (sell-in net).
SKUS = {
    "100012": dict(name="Rayo 12g", brand="Rayo", grams=12, upc=120, price=0.33, cogs=0.19, base=1800, life=270),
    "100013": dict(name="Rayo 25g", brand="Rayo", grams=25, upc=96, price=0.58, cogs=0.33, base=900, life=270),
    "100041": dict(name="Dulcera Milk 40g", brand="Dulcera", grams=40, upc=48, price=0.85, cogs=0.49, base=2200, life=300),
    "100045": dict(name="Dulcera Milk 90g", brand="Dulcera", grams=90, upc=24, price=1.55, cogs=0.88, base=2600, life=300),
    "100048": dict(name="Dulcera Milk 150g", brand="Dulcera", grams=150, upc=18, price=2.40, cogs=1.38, base=850, life=300),
    "100051": dict(name="Dulcera Zero 80g", brand="Dulcera", grams=80, upc=24, price=1.85, cogs=1.02, base=520, life=270),
    "100031": dict(name="Crunchita 35g", brand="Crunchita", grams=35, upc=60, price=0.55, cogs=0.31, base=1500, life=240),
    "100032": dict(name="Crunchita Multipack 5×35g", brand="Crunchita", grams=175, upc=12, price=2.30, cogs=1.36, base=600, life=240),
    "100061": dict(name="Cacao Alto 70% 100g", brand="Cacao Alto", grams=100, upc=20, price=2.60, cogs=1.30, base=700, life=360),
    "100062": dict(name="Cacao Alto 85% 100g", brand="Cacao Alto", grams=100, upc=20, price=2.70, cogs=1.34, base=300, life=360),
    "100071": dict(name="Almendra Real 45g", brand="Almendra Real", grams=45, upc=48, price=0.95, cogs=0.56, base=1000, life=270),
    "100072": dict(name="Almendra Real 120g", brand="Almendra Real", grams=120, upc=20, price=2.30, cogs=1.35, base=450, life=270),
    "100058": dict(name="Fiesta Bites 150g", brand="Fiesta Bites", grams=150, upc=16, price=3.10, cogs=1.74, base=1100, life=240),
    "100059": dict(name="Fiesta Calaverita 25g", brand="Fiesta Bites", grams=25, upc=96, price=0.42, cogs=0.24, base=0, life=200,
                   seasonal="muertos", markets=["MX"]),
    "100063": dict(name="Cacao Alto Gift Box 200g", brand="Cacao Alto", grams=200, upc=10, price=6.20, cogs=3.10, base=0, life=300,
                   seasonal="navidad"),
    "100091": dict(name="Navidad Assortment 300g", brand="Fiesta Bites", grams=300, upc=12, price=5.60, cogs=3.05, base=0, life=240,
                   seasonal="navidad"),
    "100081": dict(name="Ovo de Páscoa Dulcera 200g", brand="Dulcera", grams=200, upc=12, price=4.80, cogs=2.60, base=0, life=150,
                   seasonal="pascoa", markets=["BR"]),
    "100082": dict(name="Ovo de Páscoa Cacao Alto 250g", brand="Cacao Alto", grams=250, upc=8, price=7.50, cogs=3.70, base=0, life=150,
                   seasonal="pascoa", markets=["BR"]),
}
SEASONAL_PEAK = {"muertos": 2600, "navidad": 1300, "pascoa": 2400}
COCOA_SHARE_OF_COGS = 0.42   # share of COGS exposed to cocoa beans/butter

# Head-to-head competitor product used for price-gap tracking, per own SKU.
COMPETITORS = {
    "Helvetia": dict(kind="global", color="info"),
    "Andina Dulces": dict(kind="regional", color="ai"),
    "Private label": dict(kind="pl", color="tx3"),
}
COMP_PRODUCT = {"100045": "Helvetia Classic 90g", "100041": "Helvetia Classic 40g", "100061": "Helvetia Noir 70% 100g",
                "100058": "Helvetia Pralinés 150g", "100031": "Andina Wafer 35g", "100012": "Andina Mini 12g"}
# our value share by market (MAT) and competitor split of the remainder
SHARE_BASE = {"MX": (27.9, 24.1, 9.2, 6.0), "BR": (18.4, 29.5, 12.0, 5.1), "CO": (21.7, 17.9, 22.4, 4.0),
              "PE": (19.2, 21.0, 15.3, 6.2), "CL": (16.8, 26.4, 8.8, 9.9), "AR": (14.1, 19.8, 24.6, 5.4),
              "CA": (23.5, 20.2, 10.1, 3.8)}

# --------------------------------------------------------------------------------------------
# Calendar events. Each returns an intensity 0..1 for (market, iso_year, iso_week).
EASTER = {2024: date(2024, 3, 31), 2025: date(2025, 4, 20), 2026: date(2026, 4, 5), 2027: date(2027, 3, 28)}

EVENT_LABELS = {
    "muertos": "Día de Muertos", "buen_fin": "Buen Fin", "navidad": "Navidad", "valentine": "San Valentín",
    "kids": "Día del Niño", "mothers": "Día de las Madres", "pascoa": "Páscoa / Easter", "halloween": "Halloween",
    "black_friday": "Black Friday", "patrias": "Fiestas Patrias", "amor_amistad": "Amor y Amistad",
}
# event uplift on consumer demand per market (multiplier - 1 at full intensity)
EVENT_LIFT = {
    "MX": dict(muertos=0.30, buen_fin=0.10, navidad=0.34, valentine=0.36, kids=0.22, mothers=0.18),
    "BR": dict(pascoa=0.65, navidad=0.30, black_friday=0.12, kids=0.20, valentine=0.15),
    "CO": dict(amor_amistad=0.30, halloween=0.25, navidad=0.32, mothers=0.15, black_friday=0.08),
    "PE": dict(halloween=0.18, navidad=0.36, mothers=0.16),
    "CL": dict(patrias=0.20, navidad=0.30, pascoa=0.20, black_friday=0.08),
    "AR": dict(kids=0.28, navidad=0.30, pascoa=0.30),
    "CA": dict(navidad=0.32, pascoa=0.12, valentine=0.18),
}


def iso_week_monday(iso_year: int, iso_week: int) -> date:
    return date.fromisocalendar(iso_year, iso_week, 1)


def event_intensity(market: str, iso_year: int, iso_week: int) -> dict[str, float]:
    monday = iso_week_monday(iso_year, iso_week)
    out: dict[str, float] = {}
    w = iso_week
    if market == "MX":
        out["muertos"] = {43: 0.55, 44: 1.0}.get(w, 0.0)
        out["buen_fin"] = 1.0 if w == 46 else 0.0
        out["kids"] = 1.0 if w in (17, 18) and _contains(monday, 4, 30) else (0.4 if w == 17 else 0.0)
        out["mothers"] = 1.0 if _contains(monday, 5, 10) else 0.0
    if market in ("MX", "CA"):
        out["valentine"] = 1.0 if _contains(monday, 2, 14) else 0.0
    if market == "BR":
        out["valentine"] = 1.0 if _contains(monday, 6, 12) else 0.0
        out["kids"] = 1.0 if _contains(monday, 10, 12) else 0.0
    if market == "AR":
        out["kids"] = 1.0 if w == 33 else 0.0
    if market in ("BR", "CO", "CL"):
        out["black_friday"] = 1.0 if w == 48 else 0.0
    if market in ("CO", "PE"):
        out["halloween"] = 1.0 if w == 44 else 0.0
    if market == "CO":
        out["amor_amistad"] = 1.0 if w == 38 else 0.0
        out["mothers"] = 1.0 if _contains(monday, 5, 10) else 0.0
    if market == "PE":
        out["mothers"] = 1.0 if _contains(monday, 5, 10) else 0.0
    if market == "CL":
        out["patrias"] = 1.0 if w == 38 else 0.0
    out["navidad"] = {49: 0.25, 50: 0.6, 51: 1.0, 52: 0.9, 53: 0.3}.get(w, 0.0)
    if market in ("BR", "CL", "AR", "CA"):
        out["pascoa"] = pascoa_intensity(monday)
    return {k: v for k, v in out.items() if v > 0}


def pascoa_intensity(monday: date) -> float:
    easter = EASTER.get(monday.year) or EASTER.get(monday.year + 1)
    if easter is None:
        return 0.0
    weeks_before = (easter - monday).days / 7.0
    if 0 <= weeks_before < 1:
        return 1.0
    if 1 <= weeks_before < 4:
        return 1.0 - (weeks_before - 1) * 0.22
    return 0.0


def _contains(monday: date, month: int, day: int) -> bool:
    try:
        d = date(monday.year, month, day)
    except ValueError:
        return False
    return monday <= d <= monday + timedelta(days=6)


# --------------------------------------------------------------------------------------------
# Peru road network for the route optimizer (km, road class, risks). Coordinates are approximate.
PE_NODES = {
    "LUR": ("DC Lima · Lurín", -12.27, -76.87), "AQP": ("DC Arequipa", -16.40, -71.54), "LIM": ("Lima", -12.05, -77.04),
    "HUA": ("Huaral", -11.50, -77.21), "HCH": ("Huacho", -11.11, -77.61), "BAR": ("Barranca", -10.75, -77.76),
    "CHB": ("Chimbote", -9.07, -78.59), "TRU": ("Trujillo", -8.11, -79.03), "CIX": ("Chiclayo", -6.77, -79.84),
    "PIU": ("Piura", -5.19, -80.63), "CHN": ("Chincha", -13.42, -76.13), "PIS": ("Pisco", -13.71, -76.20),
    "ICA": ("Ica", -14.07, -75.73), "NAZ": ("Nazca", -14.83, -74.94), "CMN": ("Camaná", -16.62, -72.71),
    "MOQ": ("Moquegua", -17.19, -70.94), "TAC": ("Tacna", -18.01, -70.25), "MAT": ("Matucana", -11.84, -76.38),
    "SMT": ("San Mateo", -11.76, -76.30), "TIC": ("Ticlio", -11.60, -76.19), "ORY": ("La Oroya", -11.52, -75.90),
    "TAR": ("Tarma", -11.42, -75.69), "JAU": ("Jauja", -11.78, -75.50), "HYO": ("Huancayo", -12.07, -75.20),
    "CNT": ("Canta", -11.47, -76.62), "HLY": ("Huayllay", -11.00, -76.37), "CPS": ("Cerro de Pasco", -10.68, -76.26),
    "HCO": ("Huánuco", -9.93, -76.24), "HTA": ("Huanta", -12.94, -74.25), "AYA": ("Ayacucho", -13.16, -74.22),
    "JUL": ("Juliaca", -15.50, -70.13), "PUN": ("Puno", -15.84, -70.02), "CUZ": ("Cusco", -13.53, -71.97),
    "ABA": ("Abancay", -13.64, -72.88), "PQO": ("Puquio", -14.70, -74.13),
}
# (a, b, km, class, landslide, security, max_alt_m). class: coast | andes | unpaved | urban
PE_EDGES = [
    ("LUR", "LIM", 30, "urban", 0.0, 0.2, 100), ("LIM", "HUA", 75, "coast", 0.0, 0.1, 200), ("HUA", "HCH", 70, "coast", 0.0, 0.1, 100),
    ("HCH", "BAR", 55, "coast", 0.0, 0.1, 100), ("BAR", "CHB", 215, "coast", 0.0, 0.2, 300), ("CHB", "TRU", 130, "coast", 0.0, 0.3, 100),
    ("TRU", "CIX", 210, "coast", 0.0, 0.3, 100), ("CIX", "PIU", 210, "coast", 0.0, 0.3, 100), ("LUR", "CHN", 165, "coast", 0.0, 0.1, 100),
    ("CHN", "PIS", 35, "coast", 0.0, 0.1, 50), ("PIS", "ICA", 75, "coast", 0.0, 0.1, 400), ("ICA", "NAZ", 140, "coast", 0.0, 0.1, 600),
    ("NAZ", "CMN", 390, "coast", 0.1, 0.1, 500), ("CMN", "AQP", 175, "coast", 0.1, 0.1, 2300), ("AQP", "MOQ", 230, "coast", 0.0, 0.1, 1400),
    ("MOQ", "TAC", 160, "coast", 0.0, 0.1, 600), ("AQP", "JUL", 280, "andes", 0.2, 0.2, 4500), ("JUL", "PUN", 45, "andes", 0.0, 0.1, 3900),
    ("JUL", "CUZ", 345, "andes", 0.3, 0.2, 4300), ("LIM", "MAT", 75, "andes", 0.5, 0.2, 2400), ("MAT", "SMT", 20, "andes", 0.7, 0.1, 3200),
    ("SMT", "TIC", 40, "andes", 0.7, 0.1, 4818), ("TIC", "ORY", 35, "andes", 0.3, 0.1, 3750), ("ORY", "TAR", 60, "andes", 0.2, 0.1, 3050),
    ("ORY", "JAU", 75, "andes", 0.2, 0.1, 3400), ("JAU", "HYO", 45, "andes", 0.1, 0.2, 3250), ("TAR", "JAU", 60, "andes", 0.2, 0.1, 3400),
    ("ORY", "CPS", 130, "andes", 0.2, 0.2, 4330), ("CPS", "HCO", 105, "andes", 0.3, 0.2, 4100), ("HUA", "CNT", 80, "andes", 0.4, 0.2, 2800),
    ("CNT", "HLY", 95, "unpaved", 0.5, 0.4, 4600), ("HLY", "CPS", 45, "unpaved", 0.3, 0.3, 4400), ("PIS", "AYA", 330, "andes", 0.4, 0.3, 4750),
    ("AYA", "HTA", 50, "andes", 0.2, 0.3, 2650), ("HTA", "HYO", 240, "unpaved", 0.5, 0.4, 3800), ("NAZ", "PQO", 155, "andes", 0.3, 0.2, 4200),
    ("PQO", "ABA", 305, "andes", 0.4, 0.3, 4300), ("ABA", "CUZ", 195, "andes", 0.3, 0.2, 3900),
]
ROAD_SPEED = dict(coast=62, andes=38, unpaved=20, urban=24)   # km/h
HOT_TOWNS = {"ICA", "NAZ", "PIU", "CIX", "TRU"}                  # > 28°C midday: chocolate needs reefer
HUAICO_EDGE = ("SMT", "TIC")                                     # Carretera Central km 98, San Mateo
