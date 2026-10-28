"""LLM gateway: Hugging Face model on this machine, with a cached-answer fallback.

Modes (config / Demo Control):
  auto  : reuse an identical earlier answer if one exists, else generate with the HF model; if the model is missing,
          slow, failing or produces figures that are not in the facts, fall back to the cache, then to a template.
  live  : always generate with the HF model (template only if the model cannot run).
  cache : never call the model; cached answers, else a template built from the same facts.

The UI never shows which path produced a narrative; only the Demo Control screen exposes that.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import deque

from .config import CACHE_PATH, settings

SYSTEM = (
    "You are CABI, the AI analyst inside a commercial command center for {company}, a chocolate manufacturer operating in "
    "Latin America. Write in {language}. Use ONLY the facts provided. Copy every number exactly as written in the facts, "
    "including its unit or currency. Never invent numbers, dates, names or causes. Be concise and specific, for senior "
    "commercial and supply-chain leaders. Plain text; you may use **bold** and lines starting with '- '. No headings, no preamble."
)
LANGS = {"en": "English", "es": "Spanish (Latin American)", "pt": "Brazilian Portuguese"}
NUM_RE = re.compile(r"(?<![\w])[-−+]?\d[\d,]*(?:\.\d+)?\s?(?:k|M|bn|pp|%)?")


def _nums(text: str, locale_variants: bool = False) -> list[tuple[float, str]]:
    """Numbers with an optional k/M/bn/pp/% suffix. With locale_variants, '160.857' and '12,5' (ES/PT style) also parse."""
    out = []
    for m in NUM_RE.finditer(text):
        raw = m.group(0).replace("−", "-").replace(" ", "")
        suf = ""
        for s in ("pp", "bn", "k", "M", "%"):
            if raw.endswith(s):
                suf, raw = s, raw[: -len(s)]
                break
        variants = {raw.replace(",", "")}
        if locale_variants:
            variants.add(raw.replace(".", "").replace(",", "."))
        vals = []
        for v in variants:
            try:
                vals.append(abs(float(v)))
            except ValueError:
                pass
        if vals:
            out.append((tuple(vals), suf) if locale_variants else (vals[0], suf))
    return out


def grounded(text: str, facts) -> tuple[bool, list[str]]:
    """Every number in `text` must appear in the facts (same value, ±rounding)."""
    blob = json.dumps(facts, ensure_ascii=False)
    allowed = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", blob):      # loose: also numbers inside keys like "probability_14d"
        try:
            allowed.add(round(float(m.group(0).replace(",", "")), 4))
        except ValueError:
            pass
    for v, suf in _nums(blob):
        allowed.add(round(v, 4))
        mult = dict(k=1e3, M=1e6, bn=1e9).get(suf, 1)
        allowed.add(round(v * mult, 4))
    bad = []
    for vals, suf in _nums(text, locale_variants=True):
        v = vals[0]
        if any(x <= 12 and float(x).is_integer() for x in vals) or any(2020 <= x <= 2030 for x in vals):
            continue                    # list numbering, "3 weeks", day counts, years
        mult = dict(k=1e3, M=1e6, bn=1e9).get(suf, 1)
        cands = [c for x in vals for c in (x, x * mult)]
        if not any(abs(a - c) <= max(0.051, 0.006 * abs(a)) for c in cands for a in allowed):
            bad.append(f"{v:g}{suf}")
    return (not bad), bad


class Gateway:
    def __init__(self):
        cfg = settings()["llm"]
        self.mode = cfg["mode"]
        self.model_id = cfg["model"]
        self.timeout = cfg["timeout_s"]
        self.max_tokens = cfg["max_tokens"]
        self.temperature = cfg["temperature"]
        self.models = cfg.get("models", [])
        self.status = "not_loaded"
        self.error = ""
        self.load_seconds = None
        self.tps = None
        self._model = self._tok = None
        self._gen_lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self.cache = self._read_cache()
        self.stats = dict(live=0, cache=0, template=0, rejected=0, errors=0)
        self.log = deque(maxlen=40)
        self.last_rejected: list[str] = []
        self.prewarm_state = dict(running=False, done=0, total=0)

    # ------------------------------------------------------------ model lifecycle
    def downloaded(self, model_id: str | None = None) -> bool:
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(model_id or self.model_id, local_files_only=True)
            return True
        except Exception:
            return False

    def load_async(self, model_id: str | None = None, download: bool = False):
        if model_id and model_id != self.model_id:
            with self._gen_lock:
                self._model = self._tok = None
            self.model_id = model_id
            self.status = "not_loaded"
        if self.status in ("loading", "ready", "downloading"):
            return
        threading.Thread(target=self._load, args=(download,), daemon=True).start()

    def _load(self, download: bool):
        with self._load_lock:
            if self.status == "ready":
                return
            try:
                if not self.downloaded():
                    if not download:
                        self.status, self.error = "missing", "Model not downloaded yet"
                        return
                    self.status = "downloading"
                    from huggingface_hub import snapshot_download
                    snapshot_download(self.model_id)
                self.status = "loading"
                t0 = time.time()
                from mlx_lm import load
                model, tok = load(self.model_id)
                with self._gen_lock:
                    self._model, self._tok = model, tok
                self.load_seconds = round(time.time() - t0, 1)
                self.status, self.error = "ready", ""
            except Exception as e:  # pragma: no cover - depends on host
                self.status, self.error = "error", f"{type(e).__name__}: {e}"[:300]

    def _generate(self, system: str, user: str) -> tuple[str, int, float]:
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt = self._tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        t0, text, n = time.time(), "", 0
        for r in stream_generate(self._model, self._tok, prompt, max_tokens=self.max_tokens, sampler=make_sampler(temp=self.temperature)):
            text += r.text
            n = r.generation_tokens
            self.tps = round(r.generation_tps, 1)
            if time.time() - t0 > self.timeout:
                raise TimeoutError(f"generation exceeded {self.timeout}s")
        return text.strip(), n, time.time() - t0

    # ------------------------------------------------------------ cache
    def _read_cache(self) -> dict:
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            return {}

    def _write_cache(self):
        with self._cache_lock:
            CACHE_PATH.parent.mkdir(exist_ok=True)
            for k, v in self._read_cache().items():      # merge entries written by other processes (e.g. the cache builder)
                self.cache.setdefault(k, v)
            tmp = CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0))
            tmp.replace(CACHE_PATH)

    @staticmethod
    def key(task: str, facts, lang: str) -> str:
        blob = json.dumps(dict(task=task, facts=facts, lang=lang), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:20]

    # ------------------------------------------------------------ main entry
    def narrate(self, task: str, facts, lang: str, instruction: str, template, force: bool = False) -> dict:
        lang = lang if lang in LANGS else "en"
        k = self.key(task, facts, lang)
        t0 = time.time()
        cached = self.cache.get(k)
        res = None
        if self.mode in ("auto", "cache") and cached and not (force and self.mode == "auto"):
            res = dict(text=cached["text"], source="cache", tokens=cached.get("tokens", 0))
        elif self.mode in ("auto", "live"):
            if self.status == "not_loaded":
                self.load_async()
            if self.status == "loading":
                self._load_lock.acquire(timeout=30)
                self._load_lock.release()
            if self.status == "ready":
                try:
                    system = SYSTEM.format(company=settings()["company"]["name"], language=LANGS[lang])
                    user = f"TASK: {instruction}\n\nFACTS (JSON):\n{json.dumps(facts, ensure_ascii=False, indent=1, default=str)}"
                    with self._gen_lock:
                        text, n, secs = self._generate(system, user)
                    ok, bad = grounded(text, facts)
                    if not ok:
                        self.stats["rejected"] += 1
                        self.last_rejected = bad
                        with self._gen_lock:
                            text, n, secs = self._generate(system + " Your previous answer used figures not in the facts: "
                                                           + ", ".join(bad[:5]) + ". Use only the facts.", user)
                        ok, bad = grounded(text, facts)
                    if ok and text:
                        with self._cache_lock:
                            self.cache[k] = dict(text=text, task=task, lang=lang, tokens=n, model=self.model_id, ts=time.strftime("%Y-%m-%d %H:%M"))
                        self._write_cache()
                        res = dict(text=text, source="live", tokens=n)
                    else:
                        self.stats["rejected"] += 1
                except Exception as e:
                    self.stats["errors"] += 1
                    self.error = f"{type(e).__name__}: {e}"[:300]
            if res is None and cached and self.mode == "auto":
                res = dict(text=cached["text"], source="cache", tokens=cached.get("tokens", 0))
        if res is None:
            res = dict(text=template(facts, lang), source="template", tokens=0)
        res["ms"] = int((time.time() - t0) * 1000)
        res["grounded"] = True
        self.stats[res["source"]] += 1
        self.log.appendleft(dict(task=task, lang=lang, source=res["source"], ms=res["ms"], tokens=res["tokens"], ts=time.strftime("%H:%M:%S")))
        return res

    def info(self) -> dict:
        return dict(mode=self.mode, model=self.model_id, status=self.status, error=self.error, load_seconds=self.load_seconds,
                    tps=self.tps, downloaded=self.downloaded(), cache_entries=len(self.cache), stats=self.stats,
                    log=list(self.log)[:12], models=self.models, prewarm=self.prewarm_state, runtime="MLX (Apple Silicon)")


GATEWAY = Gateway()
