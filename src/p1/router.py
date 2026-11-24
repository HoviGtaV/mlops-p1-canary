"""Router: the single entry point. Sends each user to variant A or B.

Assignment is sticky: a user's bucket is hash(user_id) mod 10,000 and the user
goes to B when bucket < weight * 10,000. Raising the weight from 1% to 5% keeps
every user already on B on B, and adds new ones.

The router measures what users actually see (end-to-end latency and errors),
with a `variant` label on every metric.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from pydantic import BaseModel, Field

from p1 import config

log = logging.getLogger("router")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

URLS = {
    "a": os.getenv("VARIANT_A_URL", "http://variant-a:8080"),
    "b": os.getenv("VARIANT_B_URL", "http://variant-b:8080"),
}
TIMEOUT_S = float(os.getenv("UPSTREAM_TIMEOUT_S", "2.0"))
ACCESS_LOG = os.getenv("ACCESS_LOG", "1") == "1"

REQUESTS = Counter("router_requests_total", "Requests by variant and outcome", ["variant", "outcome"])
LATENCY = Histogram("router_request_seconds", "End-to-end latency seen by users", ["variant"],
                    buckets=config.LATENCY_BUCKETS)
WEIGHT = Gauge("router_canary_weight", "Share of users routed to variant B", ["variant"])

state = {"weight": float(os.getenv("INITIAL_WEIGHT", "0"))}
WEIGHT.labels("b").set(state["weight"])


class _AccessLog:
    """Per-request log (variant, latency, status): raw data for the report."""

    def __init__(self):
        self._lock = threading.Lock()
        self._fh = None
        if ACCESS_LOG:
            os.makedirs(config.ROUTER_LOG_DIR, exist_ok=True)
            path = os.path.join(config.ROUTER_LOG_DIR, f"access-{int(time.time())}.jsonl")
            self._fh = open(path, "a", buffering=1 << 16)

    def write(self, rec: dict):
        if self._fh:
            with self._lock:
                self._fh.write(json.dumps(rec) + "\n")

    def flush(self):
        if self._fh:
            with self._lock:
                self._fh.flush()


access_log = _AccessLog()


def bucket(user_id: str) -> int:
    return int(hashlib.sha256(str(user_id).encode()).hexdigest()[:8], 16) % 10_000


def choose_variant(user_id: str, weight: float) -> str:
    return "b" if bucket(user_id) < round(weight * 10_000) else "a"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
        connector=aiohttp.TCPConnector(limit=300, limit_per_host=150))
    yield
    await app.state.client.close()
    access_log.flush()


app = FastAPI(title="canary router", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


@app.post("/predict")
async def predict(request: Request):
    body = await request.json()
    user_id = str(body.get("user_id", ""))
    variant = choose_variant(user_id, state["weight"])
    t0 = time.perf_counter()
    status, payload = 502, {"error": "upstream unreachable", "variant": variant}
    try:
        async with app.state.client.post(URLS[variant] + "/predict", json=body) as r:
            status = r.status
            payload = await r.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        payload = {"error": f"upstream failure: {type(exc).__name__}", "variant": variant}
    elapsed = time.perf_counter() - t0
    outcome = "error" if status >= 500 else "ok"
    REQUESTS.labels(variant, outcome).inc()
    LATENCY.labels(variant).observe(elapsed)
    access_log.write({"t": round(time.time(), 3), "variant": variant, "status": status,
                      "latency_ms": round(elapsed * 1000, 3),
                      "score": payload.get("score") if isinstance(payload, dict) else None})
    return JSONResponse(payload, status_code=status)


class WeightUpdate(BaseModel):
    weight: float = Field(ge=0.0, le=1.0)


@app.get("/admin/weight")
def get_weight():
    return {"weight": state["weight"]}


@app.post("/admin/weight")
def set_weight(update: WeightUpdate):
    state["weight"] = update.weight
    WEIGHT.labels("b").set(update.weight)
    access_log.flush()
    log.info("canary weight set to %.2f%%", update.weight * 100)
    return {"weight": state["weight"]}


@app.get("/health")
async def health():
    out = {}
    for name, url in URLS.items():
        try:
            async with app.state.client.get(url + "/health") as r:
                out[name] = await r.json() if r.status == 200 else {"status": r.status}
        except (aiohttp.ClientError, asyncio.TimeoutError):
            out[name] = {"status": "unreachable"}
    ready = all("model_version" in v for v in out.values())
    if not ready:
        raise HTTPException(503, out)
    return {"weight": state["weight"], "variants": out}
