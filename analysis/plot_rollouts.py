"""One figure per rollout (timeline of weight, errors, latency, scores and the
guardrail statistics), built from the controller's decision log and the
Prometheus history. Also writes rollouts_summary.json for the report.

Run inside the stack:  docker compose run --rm trainer python -m analysis.plot_rollouts
"""
from __future__ import annotations

import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from p1 import config
from p1.prom import Prometheus

OUT = os.path.join(config.DATA_DIR, "report_figures")
prom = Prometheus(os.getenv("PROMETHEUS_URL", "http://prometheus:9090"))
COL = {"a": "tab:blue", "b": "tab:orange"}


def scenario_at(t: float) -> str:
    flags = {m["flag"]: v for m, v in prom.instant('model_injected_flag{variant="b"}', t)}
    if flags.get("schema_bug", 0) > 0:
        return "schema"
    if flags.get("error_rate", 0) > 0:
        return "errors"
    if flags.get("extra_latency_ms", 0) > 0:
        return "latency"
    return "healthy"


def series(query, start, end, step=2.0):
    out = {}
    for metric, values in prom.range(query, start, end, step):
        key = metric.get("variant", "value")
        arr = np.array(values, dtype=float)
        out[key] = (arr[:, 0] - start, arr[:, 1])
    return out


def plot(path):
    recs = [json.loads(line) for line in open(path)]
    start = next(r for r in recs if r["event"] == "start")
    end_ev = next((r for r in recs if r["event"] in ("passed", "rollback", "abort", "crash")), None)
    if end_ev is None:
        return None
    t0, t1 = start["t"], end_ev["t"]
    scen = scenario_at(t0 + 5)
    checks = [r for r in recs if r["event"] == "check"]
    steps = [r for r in recs if r["event"] == "step"]
    lo, hi = t0 - 20, t1 + 40

    fig, axes = plt.subplots(5, 1, figsize=(10, 12), sharex=True)
    s = series("router_canary_weight", lo, hi)
    for k, (x, y) in s.items():
        axes[0].step(x + (lo - t0), y * 100, where="post", color="black")
    axes[0].set_ylabel("traffic on v2 (%)")
    axes[0].set_yscale("symlog", linthresh=1)
    axes[0].set_yticks([0, 1, 5, 25, 100])
    axes[0].set_yticklabels(["0", "1", "5", "25", "100"])

    q = ('sum by (variant) (rate(router_requests_total{outcome="error"}[30s])) / '
         'sum by (variant) (rate(router_requests_total[30s]))')
    for k, (x, y) in series(q, lo, hi).items():
        axes[1].plot(x + (lo - t0), y * 100, color=COL.get(k), label=f"v{1 if k == 'a' else 2}")
    axes[1].set_ylabel("error rate (%)")
    axes[1].legend(loc="upper left", fontsize=8)

    q = 'histogram_quantile(0.99, sum by (variant, le) (rate(router_request_seconds_bucket[30s])))'
    for k, (x, y) in series(q, lo, hi).items():
        axes[2].plot(x + (lo - t0), y * 1000, color=COL.get(k), label=f"v{1 if k == 'a' else 2}")
    axes[2].set_ylabel("p99 latency (ms)")

    q = ('sum by (variant) (rate(model_score_sum[30s])) / '
         'sum by (variant) (rate(model_score_count[30s]))')
    for k, (x, y) in series(q, lo, hi).items():
        axes[3].plot(x + (lo - t0), y, color=COL.get(k), label=f"v{1 if k == 'a' else 2}")
    axes[3].set_ylabel("mean score")

    ct = np.array([c["t"] - t0 for c in checks])
    for g, color, label in [("score_psi", "tab:purple", "PSI / threshold"),
                            ("latency_p99", "tab:orange", "p99 v2 / limit"),
                            ("error_rate", "tab:red", "error gap / 1 pt")]:
        xs, ys = [], []
        for c, x in zip(checks, ct):
            r = c["guardrails"].get(g)
            if r and r["threshold"]:
                xs.append(x)
                ys.append(r["value"] / r["threshold"])
        if xs:
            axes[4].plot(xs, ys, marker=".", color=color, label=label)
    axes[4].axhline(1.0, color="red", ls="--", lw=1)
    axes[4].set_ylabel("guardrail value\n/ threshold")
    axes[4].set_xlabel("seconds since rollout start")
    axes[4].legend(loc="upper left", fontsize=8)

    for ax in axes:
        for st in steps:
            ax.axvline(st["t"] - t0, color="grey", lw=0.6, ls=":")
        ax.axvline(t1 - t0, color="red" if end_ev["event"] == "rollback" else "green", lw=1.5)
        ax.grid(alpha=0.25)
    verdict = end_ev["event"].upper()
    if end_ev["event"] == "rollback":
        verdict += f" by {', '.join(end_ev['guardrails'])} at {end_ev['weight']:.0%} " \
                   f"after {end_ev['n_b']:.0f} v2 requests in the step"
    fig.suptitle(f"Scenario '{scen}': {verdict}", fontsize=11)
    fig.tight_layout()
    name = f"rollout_{scen}_{int(t0)}.png"
    fig.savefig(os.path.join(OUT, name), dpi=110)
    plt.close(fig)
    return {"file": os.path.basename(path), "figure": name, "scenario": scen,
            "outcome": end_ev["event"], "seconds": t1 - t0,
            "guardrails": end_ev.get("guardrails"), "weight": end_ev.get("weight"),
            "n_b": end_ev.get("n_b"), "details": end_ev.get("details"),
            "psi_threshold": start.get("psi_threshold"),
            "checks": len(checks)}


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for path in sorted(glob.glob(os.path.join(config.ROLLOUT_LOG_DIR, "*.jsonl"))):
        try:
            row = plot(path)
        except Exception as exc:
            print("skip", path, exc)
            continue
        if row:
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("scenario", "outcome", "guardrails", "weight",
                                                  "n_b", "seconds")}, default=float))
    with open(os.path.join(OUT, "rollouts_summary.json"), "w") as f:
        json.dump(rows, f, indent=2, default=float)


if __name__ == "__main__":
    main()
