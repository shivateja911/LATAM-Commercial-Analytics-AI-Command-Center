"""SAP IBP-style statistical baseline: damped seasonal naive.

It sees only shipment history: no promotions, no POS signal, no weather. That gap is what the AI forecast closes.
"""
from __future__ import annotations

import numpy as np


def sap_baseline(y: np.ndarray, h: int, origin: int | None = None) -> np.ndarray:
    """Forecast weeks [origin, origin + h) from weekly history y[:origin]."""
    n = len(y) if origin is None else origin
    hist = np.asarray(y[:n], dtype=float)
    recent = hist[n - 13:n].sum()
    recent_ly = hist[n - 65:n - 52].sum() if n >= 65 else recent
    growth = float(np.clip(recent / recent_ly, 0.8, 1.3)) if recent_ly > 0 else 1.0
    level = hist[n - 13:n].mean()
    out = np.empty(h)
    for k in range(h):
        ly = hist[n - 52 + k] if n - 52 + k < n else hist[n - 104 + k]
        out[k] = 0.65 * ly * growth + 0.35 * level
    return np.maximum(out, 0.0)
