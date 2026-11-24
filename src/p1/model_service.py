"""Inference service. variant-a and variant-b run this same image; they differ
only by environment variables:

  VARIANT          a | b                  (label on every metric)
  MODEL_ALIAS      champion | challenger  (which registry alias to load)

Failure injection (variant-b only in the scenarios):
  EXTRA_LATENCY_MS  added sleep per request                       (failure 1)
  ERROR_RATE        probability of answering HTTP 500             (failure 2)
  SCHEMA_BUG        1 = upstream renamed number_inpatient, the     (failure 3)
                    service imputes the missing column and still answers 200
Background:
  BASE_ERROR_RATE   small natural error rate on both variants (flaky dependency)
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import random
import threading
import time
from contextlib import asynccontextmanager

import mlflow
from fastapi import FastAPI, HTTPException
from mlflow import MlflowClient
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, make_asgi_app
from prometheus_client import multiprocess
from pydantic import BaseModel

from p1 import config

log = logging.getLogger("model_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

VARIANT = os.getenv("VARIANT", "a")
MODEL_ALIAS = os.getenv("MODEL_ALIAS", "champion")
EXTRA_LATENCY_MS = float(os.getenv("EXTRA_LATENCY_MS", "0") or 0)
ERROR_RATE = float(os.getenv("ERROR_RATE", "0") or 0)
BASE_ERROR_RATE = float(os.getenv("BASE_ERROR_RATE", "0") or 0)
SCHEMA_BUG = os.getenv("SCHEMA_BUG", "0") == "1"

PREDICTIONS = Counter("model_predictions_total", "Predictions served", ["variant", "model_version"])
ERRORS = Counter("model_errors_total", "Failed predictions", ["variant", "kind"])
SCORE = Histogram("model_score", "Predicted readmission probability", ["variant"],
                  buckets=config.SCORE_BUCKETS)
INVALID = Counter("model_invalid_scores_total", "NaN or out-of-range scores", ["variant"])
INFER_LATENCY = Histogram("model_inference_seconds", "Time spent inside the service", ["variant"],
                          buckets=config.LATENCY_BUCKETS)
INFO = Gauge("model_info", "Loaded model (value 1)", ["variant", "alias", "model_version"],
             multiprocess_mode="max")
FLAGS = Gauge("model_injected_flag", "Injected failure flags", ["variant", "flag"],
              multiprocess_mode="max")

state: dict = {"model": None, "version": None}
# Seeded per process so injected failures are reproducible.
rng = random.Random(config.SEED + os.getpid())


def _load_model_forever():
    mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
    client = MlflowClient()
    while True:
        try:
            mv = client.get_model_version_by_alias(config.MODEL_NAME, MODEL_ALIAS)
            model = mlflow.sklearn.load_model(f"models:/{config.MODEL_NAME}@{MODEL_ALIAS}")
            # Warm-up so the first real request is not slow.
            model.predict_proba([{}])
            state["model"], state["version"] = model, str(mv.version)
            INFO.labels(VARIANT, MODEL_ALIAS, str(mv.version)).set(1)
            log.info("variant=%s loaded %s@%s (version %s)", VARIANT, config.MODEL_NAME,
                     MODEL_ALIAS, mv.version)
            return
        except Exception as exc:  # registry not ready yet
            log.info("waiting for model %s@%s: %s", config.MODEL_NAME, MODEL_ALIAS, exc)
            time.sleep(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for flag, value in [("extra_latency_ms", EXTRA_LATENCY_MS), ("error_rate", ERROR_RATE),
                        ("schema_bug", float(SCHEMA_BUG)), ("base_error_rate", BASE_ERROR_RATE)]:
        FLAGS.labels(VARIANT, flag).set(value)
    log.info("variant=%s flags: extra_latency_ms=%s error_rate=%s schema_bug=%s base_error_rate=%s",
             VARIANT, EXTRA_LATENCY_MS, ERROR_RATE, SCHEMA_BUG, BASE_ERROR_RATE)
    threading.Thread(target=_load_model_forever, daemon=True).start()
    yield


app = FastAPI(title=f"readmission model - variant {VARIANT}", lifespan=lifespan)
if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
    # Several uvicorn worker processes: aggregate their metrics at scrape time.
    _registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(_registry)
    app.mount("/metrics", make_asgi_app(registry=_registry))
else:
    app.mount("/metrics", make_asgi_app())


class PredictRequest(BaseModel):
    user_id: str
    features: dict


@app.get("/health")
def health():
    if state["model"] is None:
        raise HTTPException(503, "model not loaded")
    return {"variant": VARIANT, "alias": MODEL_ALIAS, "model_version": state["version"]}


@app.post("/predict")
async def predict(req: PredictRequest):
    # Runs on the event loop (no thread hop): prediction is ~1-10 ms of CPU and
    # each worker process handles one at a time; several workers give parallelism.
    t0 = time.perf_counter()
    model = state["model"]
    if model is None:
        ERRORS.labels(VARIANT, "not_ready").inc()
        raise HTTPException(503, "model not loaded")
    try:
        r = rng.random()
        if r < ERROR_RATE:
            ERRORS.labels(VARIANT, "injected").inc()
            raise HTTPException(500, "injected failure")
        if r < ERROR_RATE + BASE_ERROR_RATE:
            ERRORS.labels(VARIANT, "background").inc()
            raise HTTPException(500, "dependency timeout")

        features = dict(req.features)
        if SCHEMA_BUG and "number_inpatient" in features:
            # An upstream change renamed the column. Nothing fails: the model's
            # cleaning step sees a missing column and the imputer fills it.
            features["num_inpatient"] = features.pop("number_inpatient")

        score = float(model.predict_proba([features])[0, 1])
        if EXTRA_LATENCY_MS > 0:
            await asyncio.sleep(EXTRA_LATENCY_MS / 1000.0 * rng.uniform(0.8, 1.2))

        if math.isnan(score) or not 0.0 <= score <= 1.0:
            INVALID.labels(VARIANT).inc()
        else:
            SCORE.labels(VARIANT).observe(score)
        PREDICTIONS.labels(VARIANT, state["version"]).inc()
        return {"variant": VARIANT, "model_version": state["version"], "score": score}
    except HTTPException:
        raise
    except Exception as exc:
        ERRORS.labels(VARIANT, "exception").inc()
        log.exception("prediction failed")
        raise HTTPException(500, str(exc))
    finally:
        INFER_LATENCY.labels(VARIANT).observe(time.perf_counter() - t0)
