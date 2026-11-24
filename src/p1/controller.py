"""Rollout controller.

Ramps the share of users on v2 (variant B): 1% -> 5% -> 25% -> 100%.
At every check (every CHECK_INTERVAL_S seconds) it queries the Prometheus API
and evaluates four guardrails, comparing v2 traffic *since the step started*
with v1 traffic *since the rollout started*:

  error_rate   one-sided two-proportion z-test, v2 vs v1
               (breach if p < ALPHA and the gap >= MIN_ERROR_DIFF, confirmed by an
               exact binomial test because errors are rare and v2 traffic is small)
  latency_p99  p99_v2 <= LATENCY_RATIO x (p99_v1 + v2's offline extra cost)
               (end-to-end, from the router; see latency_allow_offline_overhead)
  score_psi    PSI of v2's score distribution vs v1's <= PSI_THRESHOLD
               (from the 5% step on: at 1% v2 sees too few patients)
  invalid      share of NaN / out-of-range scores <= INVALID_MAX

A guardrail is only evaluated once v2 has enough requests in the step for it to
mean something (MIN_N_*). A guardrail must be breached on CONSECUTIVE_BREACHES
checks in a row to trigger a rollback (protection against false alarms).

Rollback = router weight back to 0. The registry aliases are never changed:
v1 stays @champion, v2 stays @challenger.

A step passes when it has lasted STEP_MIN_SECONDS and v2 has served at least
STEP_MIN_REQUESTS requests in it with no rollback.

HTTP API (port 8090): POST /rollout/start, POST /rollout/abort,
GET /rollout/status, GET /metrics.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field

import httpx
from fastapi import FastAPI, HTTPException
from mlflow import MlflowClient
from prometheus_client import Counter, Gauge, make_asgi_app

from p1 import config
from p1.prom import Prometheus, cumulative_to_bins, histogram_from_delta
from p1.stats import binomial_pvalue, histogram_quantile, psi, two_proportion_ztest

log = logging.getLogger("controller")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

PROM_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
ROUTER_URL = os.getenv("ROUTER_URL", "http://router:8000")


def _floats(text: str) -> list[float]:
    return [float(x) for x in text.split(",") if x.strip()]


@dataclass
class Settings:
    steps: list = field(default_factory=lambda: _floats(os.getenv("STEPS", "0.01,0.05,0.25,1.0")))
    check_interval_s: float = float(os.getenv("CHECK_INTERVAL_S", "5"))
    step_min_seconds: float = float(os.getenv("STEP_MIN_SECONDS", "30"))
    step_min_requests: list = field(default_factory=lambda: _floats(
        os.getenv("STEP_MIN_REQUESTS", "400,700,1000,1500")))
    step_max_seconds: float = float(os.getenv("STEP_MAX_SECONDS", "900"))
    alpha: float = float(os.getenv("ALPHA", "0.001"))
    min_error_diff: float = float(os.getenv("MIN_ERROR_DIFF", "0.01"))
    # The z-test is unreliable with few requests and rare errors: require an
    # exact binomial test to agree before calling a breach.
    exact_confirm: bool = os.getenv("EXACT_CONFIRM", "1") == "1"
    latency_ratio: float = float(os.getenv("LATENCY_RATIO", "1.1"))
    latency_quantile: float = float(os.getenv("LATENCY_QUANTILE", "0.99"))
    # v2 is heavier by design. If true, the limit is ratio x (p99_v1 + v2's extra
    # compute measured offline); if false, the literal rule ratio x p99_v1.
    latency_allow_offline_overhead: bool = os.getenv("LATENCY_ALLOW_OFFLINE_OVERHEAD", "1") == "1"
    # The offline benchmark (one row, idle CPU) underestimates v2's extra cost under
    # concurrent load (measured live: 29 ms idle -> ~40 ms at 25% traffic).
    latency_overhead_factor: float = float(os.getenv("LATENCY_OVERHEAD_FACTOR", "1.5"))
    # Calibrated offline (analysis/psi_calibration.py): healthy v2 at 5% traffic and
    # 500+ requests stays below ~0.15 (p99), the schema bug lands above it. At 1%
    # traffic v2 sees ~100 patients and PSI cannot separate them, so it starts at 5%.
    psi_threshold: str = os.getenv("PSI_THRESHOLD", "0.15")   # or "auto" = offline PSI + PSI_MARGIN
    psi_margin: float = float(os.getenv("PSI_MARGIN", "0.10"))
    psi_min_weight: float = float(os.getenv("PSI_MIN_WEIGHT", "0.05"))
    invalid_max: float = float(os.getenv("INVALID_MAX", "0.001"))
    consecutive_breaches: int = int(os.getenv("CONSECUTIVE_BREACHES", "2"))
    min_n_error: int = int(os.getenv("MIN_N_ERROR", "50"))
    min_n_latency: int = int(os.getenv("MIN_N_LATENCY", "300"))
    min_n_psi: int = int(os.getenv("MIN_N_PSI", "500"))
    min_n_invalid: int = int(os.getenv("MIN_N_INVALID", "20"))


GUARDRAILS = ["error_rate", "latency_p99", "score_psi", "invalid_scores"]

# Every metric is about the challenger (variant b), and says so with a label.
G_STATE = Gauge("canary_rollout_state", "0 idle, 1 running, 2 passed, 3 rolled back, 4 aborted",
                ["variant"]).labels("b")
G_STEP = Gauge("canary_step_weight", "Weight of the current step", ["variant"]).labels("b")
G_VALUE = Gauge("canary_guardrail_value", "Latest guardrail statistic", ["variant", "guardrail"])
G_THRESH = Gauge("canary_guardrail_threshold", "Guardrail threshold", ["variant", "guardrail"])
G_BREACH = Gauge("canary_guardrail_breach", "1 if breached at the last check", ["variant", "guardrail"])
G_PVALUE = Gauge("canary_error_pvalue", "p-value of the error-rate z-test", ["variant"]).labels("b")
G_N_B = Gauge("canary_v2_requests_in_step", "v2 requests since the step started",
              ["variant"]).labels("b")
C_ROLLBACK = Counter("canary_rollbacks_total", "Rollbacks", ["variant", "guardrail"])
C_CHECKS = Counter("canary_checks_total", "Guardrail checks run", ["variant"]).labels("b")

STATE_CODES = {"idle": 0, "running": 1, "passed": 2, "rolled_back": 3, "aborted": 4}


class Rollout:
    def __init__(self, settings: Settings):
        self.s = settings
        self.prom = Prometheus(PROM_URL)
        self.http = httpx.Client(timeout=5)
        self.status = "idle"
        self.reason = None
        self.current_weight = 0.0
        self.checks: list[dict] = []
        self.events: list[dict] = []
        self.stop = threading.Event()
        self.started_at = None
        self.psi_threshold = None
        self.latency_overhead_s = 0.0
        self.challenger_version = None
        os.makedirs(config.ROLLOUT_LOG_DIR, exist_ok=True)
        self.log_path = os.path.join(config.ROLLOUT_LOG_DIR, f"rollout-{int(time.time())}.jsonl")

    # ----------------------------------------------------------------- helpers
    def _write(self, rec: dict):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(rec, default=float) + "\n")

    def _event(self, kind: str, **kw):
        rec = {"t": time.time(), "event": kind, **kw}
        self.events.append(rec)
        self._write(rec)
        log.info("%s %s", kind, json.dumps(kw, default=float))

    def _set_weight(self, w: float):
        self.http.post(ROUTER_URL + "/admin/weight", json={"weight": w}).raise_for_status()
        self.current_weight = w
        G_STEP.set(w)

    def _registry(self):
        client = MlflowClient(config.MLFLOW_TRACKING_URI)
        mv = client.get_model_version_by_alias(config.MODEL_NAME, "challenger")
        self.challenger_version = mv.version
        return client, mv

    def _resolve_baselines(self):
        """Offline baselines stored on the challenger version in the registry."""
        try:
            _, mv = self._registry()
            tags = mv.tags
        except Exception:
            tags = {}
        offline_psi = float(tags.get("offline_psi_vs_champion", "0"))
        self.psi_threshold = (float(self.s.psi_threshold) if self.s.psi_threshold != "auto"
                              else round(offline_psi + self.s.psi_margin, 4))
        self.latency_overhead_s = (float(tags.get("offline_latency_overhead_ms", "0")) / 1000
                                   * self.s.latency_overhead_factor
                                   if self.s.latency_allow_offline_overhead else 0.0)

    # -------------------------------------------------------------- the checks
    def measure(self, t_rollout: float, t_step: float, now: float) -> dict:
        p = self.prom
        req_b = p.delta('sum by (variant, outcome) (router_requests_total{variant="b"})',
                        t_step, now, ("variant", "outcome"))
        req_a = p.delta('sum by (variant, outcome) (router_requests_total{variant="a"})',
                        t_rollout, now, ("variant", "outcome"))
        n_b = sum(req_b.values())
        x_b = req_b.get(("b", "error"), 0.0)
        n_a = sum(req_a.values())
        x_a = req_a.get(("a", "error"), 0.0)

        lat_b = p.delta('sum by (variant, le) (router_request_seconds_bucket{variant="b"})',
                        t_step, now, ("variant", "le"))
        lat_a = p.delta('sum by (variant, le) (router_request_seconds_bucket{variant="a"})',
                        t_rollout, now, ("variant", "le"))
        sc_b = p.delta('sum by (variant, le) (model_score_bucket{variant="b"})',
                       t_step, now, ("variant", "le"))
        sc_a = p.delta('sum by (variant, le) (model_score_bucket{variant="a"})',
                       t_rollout, now, ("variant", "le"))
        inv_b = p.delta('sum by (variant) (model_invalid_scores_total{variant="b"})',
                        t_step, now, ("variant",))

        lb, lcb = histogram_from_delta(lat_b, "b")
        la, lca = histogram_from_delta(lat_a, "a")
        sb, scb = histogram_from_delta(sc_b, "b")
        sa, sca = histogram_from_delta(sc_a, "a")
        q = self.s.latency_quantile
        return {
            "n_b": n_b, "x_b": x_b, "n_a": n_a, "x_a": x_a,
            "p99_b": histogram_quantile(q, lb, lcb) if lb else float("nan"),
            "p99_a": histogram_quantile(q, la, lca) if la else float("nan"),
            "scores_b": cumulative_to_bins(scb) if sb else [],
            "scores_a": cumulative_to_bins(sca) if sa else [],
            "n_scores_b": scb[-1] if scb else 0.0,
            "invalid_b": inv_b.get(("b",), 0.0),
        }

    def evaluate(self, m: dict, weight: float = 1.0) -> dict:
        s, res = self.s, {}
        n_b = m["n_b"]

        if n_b >= s.min_n_error and m["n_a"] > 0:
            z, pval = two_proportion_ztest(int(m["x_b"]), int(n_b), int(m["x_a"]), int(m["n_a"]))
            exact = binomial_pvalue(int(m["x_b"]), int(n_b), int(m["x_a"]), int(m["n_a"]))
            diff = m["x_b"] / n_b - m["x_a"] / m["n_a"]
            breach = pval < s.alpha and diff >= s.min_error_diff
            if s.exact_confirm:
                breach = breach and exact < s.alpha
            res["error_rate"] = {"value": diff, "threshold": s.min_error_diff, "p_value": pval,
                                 "exact_p_value": exact, "z": z, "breach": breach}
        if n_b >= s.min_n_latency and m["p99_a"] == m["p99_a"] and m["p99_b"] == m["p99_b"]:
            limit = s.latency_ratio * (m["p99_a"] + self.latency_overhead_s)
            res["latency_p99"] = {"value": m["p99_b"], "threshold": limit,
                                  "v1": m["p99_a"], "breach": m["p99_b"] > limit}
        if (weight >= s.psi_min_weight and m["n_scores_b"] >= s.min_n_psi
                and sum(m["scores_a"]) > 0):
            value = psi(m["scores_a"], m["scores_b"])
            res["score_psi"] = {"value": value, "threshold": self.psi_threshold,
                                "breach": value > self.psi_threshold}
        n_scored = m["n_scores_b"] + m["invalid_b"]
        if n_scored >= s.min_n_invalid:
            share = m["invalid_b"] / n_scored
            res["invalid_scores"] = {"value": share, "threshold": s.invalid_max,
                                     "breach": share > s.invalid_max}
        return res

    # ------------------------------------------------------------------- loop
    def run(self):
        self.status = "running"
        G_STATE.set(STATE_CODES["running"])
        try:
            self._run()
        except Exception as exc:
            log.exception("rollout crashed")
            self._event("crash", error=str(exc))
            try:
                self._set_weight(0.0)
            except Exception:
                pass
            self.status, self.reason = "aborted", f"controller error: {exc}"
        G_STATE.set(STATE_CODES[self.status])

    def _run(self):
        s = self.s
        self._resolve_baselines()
        for g in GUARDRAILS:
            G_BREACH.labels("b", g).set(0)
        G_THRESH.labels("b", "score_psi").set(self.psi_threshold)
        G_THRESH.labels("b", "invalid_scores").set(s.invalid_max)
        G_THRESH.labels("b", "error_rate").set(s.min_error_diff)
        try:
            self._registry()
        except Exception:
            pass
        self.started_at = t_rollout = time.time()
        self._event("start", settings=asdict(s), psi_threshold=self.psi_threshold,
                    latency_overhead_s=self.latency_overhead_s,
                    challenger_version=self.challenger_version)

        for i, weight in enumerate(s.steps):
            self._set_weight(weight)
            t_step = time.time()
            min_req = s.step_min_requests[min(i, len(s.step_min_requests) - 1)]
            self._event("step", index=i, weight=weight, min_requests=min_req)
            streak = {g: 0 for g in GUARDRAILS}
            while True:
                if self.stop.wait(s.check_interval_s):
                    self._set_weight(0.0)
                    self.status, self.reason = "aborted", "aborted by operator"
                    self._event("abort")
                    return
                now = time.time()
                m = self.measure(t_rollout, t_step, now)
                res = self.evaluate(m, weight)
                C_CHECKS.inc()
                G_N_B.set(m["n_b"])
                if "error_rate" in res:
                    G_PVALUE.set(res["error_rate"]["p_value"])
                for g, r in res.items():
                    G_VALUE.labels("b", g).set(r["value"])
                    G_BREACH.labels("b", g).set(1 if r["breach"] else 0)
                    if g == "latency_p99":
                        G_THRESH.labels("b", g).set(r["threshold"])
                    streak[g] = streak[g] + 1 if r["breach"] else 0
                rec = {"t": now, "event": "check", "step": i, "weight": weight,
                       "elapsed_step_s": now - t_step,
                       "n_b": m["n_b"], "x_b": m["x_b"], "n_a": m["n_a"], "x_a": m["x_a"],
                       "p99_b": m["p99_b"], "p99_a": m["p99_a"], "invalid_b": m["invalid_b"],
                       "guardrails": res, "streak": dict(streak)}
                self.checks.append(rec)
                self._write(rec)

                tripped = [g for g in GUARDRAILS if streak[g] >= s.consecutive_breaches]
                if tripped:
                    self._rollback(tripped, i, weight, m, res)
                    return
                elapsed = now - t_step
                if elapsed >= s.step_min_seconds and m["n_b"] >= min_req:
                    self._event("step_passed", index=i, weight=weight, n_b=m["n_b"],
                                seconds=elapsed)
                    break
                if elapsed >= s.step_max_seconds:
                    self._set_weight(0.0)
                    self.status = "aborted"
                    self.reason = f"step {weight:.0%} did not reach {min_req:.0f} requests"
                    self._event("abort", reason=self.reason)
                    return

        self.status, self.reason = "passed", "all steps passed; v2 serves 100% of traffic"
        self._event("passed", seconds=time.time() - t_rollout)
        self._tag("passed")

    def _rollback(self, tripped, i, weight, m, res):
        self._set_weight(0.0)
        for g in tripped:
            C_ROLLBACK.labels("b", g).inc()
        self.status = "rolled_back"
        self.reason = f"{', '.join(tripped)} breached at {weight:.0%} traffic"
        self._event("rollback", guardrails=tripped, step=i, weight=weight,
                    n_b=m["n_b"], details={g: res[g] for g in tripped})
        self._tag(f"rolled_back: {', '.join(tripped)}")

    def _tag(self, value: str):
        try:
            client, mv = self._registry()
            client.set_model_version_tag(config.MODEL_NAME, mv.version, "canary_result", value)
        except Exception as exc:
            log.warning("could not tag model version: %s", exc)

    def summary(self) -> dict:
        last = self.checks[-1] if self.checks else None
        return {"status": self.status, "reason": self.reason, "weight": self.current_weight,
                "started_at": self.started_at, "checks": len(self.checks),
                "psi_threshold": self.psi_threshold, "challenger_version": self.challenger_version,
                "last_check": last, "events": self.events, "log_file": self.log_path}


app = FastAPI(title="rollout controller")
app.mount("/metrics", make_asgi_app())
_current: dict = {"rollout": None, "history": []}
_lock = threading.Lock()
G_STATE.set(0)


@app.post("/rollout/start")
def start(overrides: dict | None = None):
    with _lock:
        cur = _current["rollout"]
        if cur is not None and cur.status == "running":
            raise HTTPException(409, "a rollout is already running")
        settings = Settings()
        for k, v in (overrides or {}).items():
            if not hasattr(settings, k):
                raise HTTPException(400, f"unknown setting {k}")
            setattr(settings, k, v)
        ro = Rollout(settings)
        _current["rollout"] = ro
        threading.Thread(target=ro.run, daemon=True).start()
        return {"started": True, "settings": asdict(settings), "log_file": ro.log_path}


@app.post("/rollout/abort")
def abort():
    ro = _current["rollout"]
    if ro is None or ro.status != "running":
        raise HTTPException(409, "no running rollout")
    ro.stop.set()
    return {"aborting": True}


@app.get("/rollout/status")
def status():
    ro = _current["rollout"]
    return {"status": "idle"} if ro is None else ro.summary()


@app.get("/health")
def health():
    return {"ok": True}
