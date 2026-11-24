"""Report question 2: how often does the controller roll back a *healthy* v2
(false alarms from repeated checks)?

Monte Carlo: thousands of simulated rollouts of a healthy v2. Every request is
bootstrapped from what the real stack produced (router access logs: error
flag, end-to-end latency and score of v1 and of a healthy v2). The rollout
schedule, the checks and the guardrails are the controller's own.

We compare guardrail configurations, from naive to the one we ship.

Run inside the stack:  docker compose run --rm trainer python -m analysis.q2_false_alarms
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from p1 import config
from p1.stats import binomial_pvalue, bin_counts, histogram_quantile, psi, two_proportion_ztest

OUT = os.path.join(config.DATA_DIR, "report_figures")
RATE = 150
STEPS = [0.01, 0.05, 0.25, 1.0]
STEP_MIN_S = 30
STEP_MIN_REQ = [400, 700, 1000, 1500]


@dataclass
class Rule:
    name: str
    alpha: float
    min_diff: float
    consec: int
    psi_threshold: float
    min_n_error: int = 50
    min_n_latency: int = 300
    min_n_psi: int = 200
    check_s: float = 5.0
    exact: bool = False
    psi_min_weight: float = 0.0
    latency_allowance_s: float | None = None   # None = the controller's allowance


def load_pools():
    """Per-request samples of v1 and of healthy v2 from the access logs."""
    windows = []
    for path in glob.glob(os.path.join(config.ROLLOUT_LOG_DIR, "*.jsonl")):
        recs = [json.loads(line) for line in open(path)]
        start = [r for r in recs if r.get("event") == "start"]
        passed = [r for r in recs if r.get("event") == "passed"]
        if start and passed:
            windows.append((start[0]["t"], passed[0]["t"]))
    pools = {"a": [], "b": []}
    for path in glob.glob(os.path.join(config.ROUTER_LOG_DIR, "*.jsonl")):
        for line in open(path):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            v = r["variant"]
            # Only traffic from the healthy rollouts (both variants, same conditions).
            if not any(s <= r["t"] <= e for s, e in windows):
                continue
            pools[v].append((r["status"] >= 500, r["latency_ms"] / 1000.0,
                             r["score"] if r["score"] is not None else np.nan))
    return {k: np.array(v, dtype=float) for k, v in pools.items()}, len(windows)


class Side:
    def __init__(self):
        self.n = 0
        self.err = 0
        self.lat = np.zeros(len(config.LATENCY_BUCKETS))
        self.sc = np.zeros(len(config.SCORE_BUCKETS))

    def add(self, rows):
        self.n += len(rows)
        self.err += int(rows[:, 0].sum())
        self.lat += bin_counts(rows[:, 1], config.LATENCY_BUCKETS)
        ok = rows[~np.isnan(rows[:, 2])]
        self.sc += bin_counts(ok[:, 2], config.SCORE_BUCKETS)

    def p99(self):
        cum = np.cumsum(self.lat).tolist()
        return histogram_quantile(0.99, config.LATENCY_BUCKETS, cum + [cum[-1]])


ALLOWANCE_S = 0.0


def one_rollout(rng, pools, rule: Rule):
    allowance = ALLOWANCE_S if rule.latency_allowance_s is None else rule.latency_allowance_s
    a = Side()
    for i, w in enumerate(STEPS):
        b = Side()
        streak = {"error": 0, "latency": 0, "psi": 0}
        t = 0.0
        while True:
            t += rule.check_s
            nb = rng.poisson(RATE * w * rule.check_s)
            na = rng.poisson(RATE * (1 - w) * rule.check_s)
            if nb:
                b.add(pools["b"][rng.integers(0, len(pools["b"]), nb)])
            if na:
                a.add(pools["a"][rng.integers(0, len(pools["a"]), na)])
            breach = {}
            if b.n >= rule.min_n_error:
                _, p = two_proportion_ztest(b.err, b.n, a.err, a.n)
                breach["error"] = p < rule.alpha and (b.err / b.n - a.err / a.n) >= rule.min_diff
                if rule.exact:
                    breach["error"] = breach["error"] and                         binomial_pvalue(b.err, b.n, a.err, a.n) < rule.alpha
            if b.n >= rule.min_n_latency:
                breach["latency"] = b.p99() > 1.1 * (a.p99() + allowance)
            if w >= rule.psi_min_weight and b.sc.sum() >= rule.min_n_psi:
                breach["psi"] = psi(a.sc, b.sc) > rule.psi_threshold
            for g in streak:
                streak[g] = streak[g] + 1 if breach.get(g) else 0
                if streak[g] >= rule.consec:
                    return g, i
            if t >= STEP_MIN_S and b.n >= STEP_MIN_REQ[i]:
                break
    return None, None


def run(rule: Rule, pools, n=1000, seed=0):
    rng = np.random.default_rng(seed)
    by_guardrail = {"error": 0, "latency": 0, "psi": 0}
    for _ in range(n):
        g, _ = one_rollout(rng, pools, rule)
        if g:
            by_guardrail[g] += 1
    total = sum(by_guardrail.values())
    return {"rule": rule.name, "false_rollback_rate": total / n,
            "by_guardrail": {k: v / n for k, v in by_guardrail.items()}}


def main():
    os.makedirs(OUT, exist_ok=True)
    pools, n_windows = load_pools()
    if len(pools["b"]) < 500:
        raise SystemExit("Not enough healthy-v2 traffic in the logs: run the healthy scenario first.")
    summary = json.load(open(os.path.join(config.DATA_DIR, "training_summary.json")))
    psi_auto = summary["offline_psi_v2_vs_v1"] + 0.10
    shipped = dict(min_n_psi=500, psi_min_weight=0.05)
    global ALLOWANCE_S
    # Same allowance as the controller: 1.5 x v2's offline extra cost.
    ALLOWANCE_S = 1.5 * summary["offline_latency_overhead_ms"] / 1000

    rules = [
        Rule("literal rules: p99 <= 1.1 x v1, alpha=0.05, PSI>0.10", 0.05, 0.0, 1, 0.10, 30, 20, 30,
             latency_allowance_s=0.0),
        Rule("+ allow v2's known extra latency", 0.05, 0.0, 1, 0.10, 30, 20, 30),
        Rule("+ minimum samples per guardrail", 0.05, 0.0, 1, 0.10),
        Rule("+ PSI threshold = offline baseline + 0.10", 0.05, 0.0, 1, psi_auto),
        Rule("+ alpha=0.01 and gap >= 1 pt", 0.01, 0.01, 1, psi_auto),
        Rule("+ 2 consecutive breaches", 0.01, 0.01, 2, psi_auto),
        Rule("+ exact binomial confirmation", 0.01, 0.01, 2, psi_auto, exact=True),
        Rule("+ PSI from 5% traffic, n>=500, threshold 0.15", 0.01, 0.01, 2, 0.15,
             exact=True, **shipped),
        Rule("+ alpha=0.001 for ~85 repeated checks (shipped)", 0.001, 0.01, 2, 0.15,
             exact=True, **shipped),
    ]
    results = {"healthy_rollouts_in_logs": n_windows, "latency_allowance_ms": ALLOWANCE_S * 1000,
               "pool_sizes": {k: int(len(v)) for k, v in pools.items()},
               "observed_error_rate": {k: float(v[:, 0].mean()) for k, v in pools.items()},
               "observed_p99_ms": {k: float(np.percentile(v[:, 1], 99) * 1000) for k, v in pools.items()},
               "psi_threshold_auto": psi_auto, "rules": []}
    for rule in rules:
        res = run(rule, pools)
        results["rules"].append(res)
        print(f"{res['false_rollback_rate']:.1%}  {rule.name}  {res['by_guardrail']}", flush=True)

    # Effect of checking more often (same shipped rule vs naive alpha, single breach).
    intervals = [1, 2, 5, 10, 20]
    curves = {}
    for label, alpha, consec in [("alpha=0.05, 1 breach", 0.05, 1), ("shipped rule", 0.001, 2)]:
        curves[label] = []
        for c in intervals:
            extra = shipped if consec == 2 else {}
            r = Rule(label, alpha, 0.01 if consec == 2 else 0.0, consec,
                     0.15 if consec == 2 else psi_auto, check_s=c, exact=consec == 2, **extra)
            curves[label].append(run(r, pools, n=500, seed=c)["false_rollback_rate"])
    results["check_interval_curve"] = {"intervals_s": intervals, **curves}

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    names = [r["rule"] for r in results["rules"]]
    stack = np.array([[r["by_guardrail"][g] for g in ("error", "latency", "psi")]
                      for r in results["rules"]])
    left = np.zeros(len(names))
    for j, (g, col) in enumerate([("error rate", "#d62728"), ("p99 latency", "#ff7f0e"),
                                  ("score PSI", "#1f77b4")]):
        axes[0].barh(names, stack[:, j], left=left, color=col, label=g)
        left += stack[:, j]
    for y, v in enumerate(left):
        axes[0].text(v + 0.01, y, f"{v:.0%}", va="center", fontsize=9)
    axes[0].invert_yaxis()
    axes[0].set_xlim(0, 1.1)
    axes[0].set_xlabel("share of healthy rollouts wrongly rolled back")
    axes[0].set_title("False rollbacks of a healthy v2, by guardrail")
    axes[0].legend(fontsize=8, loc="lower right")
    for label, ys in curves.items():
        axes[1].plot(intervals, ys, marker="o", label=label)
    axes[1].set_xlabel("seconds between checks")
    axes[1].set_ylabel("false rollback rate")
    axes[1].set_title("Checking more often = more false alarms")
    axes[1].grid(alpha=0.3)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "q2_false_alarms.png"), dpi=130)

    with open(os.path.join(OUT, "q2_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
