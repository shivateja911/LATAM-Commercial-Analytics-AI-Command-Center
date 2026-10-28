"""Demo state: active scenarios, write-back queue and audit trail. Engines key their caches on `version`."""
from __future__ import annotations

import json
import threading
from datetime import datetime

from .config import AUDIT_LOG

SCENARIOS = {
    "huaico_pe": dict(label="Huaico in Peru", desc="Landslide closes Carretera Central at km 98 (San Mateo)", screen="routes"),
    "heat_mx": dict(label="Heat wave in northern Mexico", desc="Monterrey 41°C, Mérida 39°C: melt risk and a demand dip", screen="routes"),
    "rionegro_br": dict(label="Rio Negro low water", desc="Manaus barge capacity −35%, inbound lead time +7 days", screen="inventory"),
    "cocoa_up": dict(label="Cocoa futures +8%", desc="Cost shock flows into margin and the pass-through plan", screen="pricing"),
    "comp_deeper": dict(label="Competitor deepens cut", desc="Helvetia takes its 90g tablet to −18% in CDMX", screen="pricing"),
    "strike_br": dict(label="Trucker strike in Brazil", desc="BR-116 blockades for 48 h around Recife and Porto Alegre", screen="routes"),
}


class DemoState:
    def __init__(self):
        self.lock = threading.RLock()
        self.version = 0
        self.active: list[str] = []
        self.queue: list[dict] = []
        self.done: list[dict] = []
        self.events: list[dict] = []
        self._seq = 0

    def bump(self):
        self.version += 1

    def inject(self, name: str) -> bool:
        with self.lock:
            if name not in SCENARIOS or name in self.active:
                return False
            self.active.append(name)
            self.events.append(dict(kind="scenario", name=name, label=SCENARIOS[name]["label"], ts=datetime.now().isoformat(timespec="seconds")))
            self.bump()
            return True

    def clear(self, name: str) -> bool:
        with self.lock:
            if name not in self.active:
                return False
            self.active.remove(name)
            self.bump()
            return True

    def reset(self):
        with self.lock:
            self.active.clear()
            self.queue.clear()
            self.done.clear()
            self.events.clear()
            self.bump()

    def on(self, name: str) -> bool:
        return name in self.active

    def enqueue(self, item: dict) -> dict:
        with self.lock:
            key = item.get("key")
            for q in self.queue + self.done:
                if key and q.get("key") == key:
                    return q
            self._seq += 1
            item = dict(item, id=f"WB{self._seq:04d}", status="pending", created=datetime.now().isoformat(timespec="seconds"))
            self.queue.append(item)
            self.bump()
            return item

    def approve(self, item_id: str, user: str = "demo.presenter") -> dict | None:
        with self.lock:
            for q in self.queue:
                if q["id"] == item_id:
                    self.queue.remove(q)
                    q = dict(q, status="posted", approved_by=user, posted=datetime.now().isoformat(timespec="seconds"),
                             sap_document=f"{q.get('doc_prefix', '45')}{9800000 + len(self.done) + 1}")
                    self.done.append(q)
                    AUDIT_LOG.parent.mkdir(exist_ok=True)
                    with open(AUDIT_LOG, "a") as f:
                        f.write(json.dumps({k: v for k, v in q.items() if k != "preview"}, default=str) + "\n")
                    self.bump()
                    return q
        return None


STATE = DemoState()
