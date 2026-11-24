"""Report question 1: at 1% traffic, how many requests are needed before the
z-test can detect the injected error rate?

Three answers that should agree:
  1. the power formula (requests on v2 for 80% power),
  2. a Monte Carlo of the controller's actual rule (sequential checks, p < alpha,
     gap >= 1 point, 2 consecutive breaches),
  3. the live "errors" scenario (read from the rollout logs, if present).

Run inside the stack:  docker compose run --rm trainer python -m analysis.q1_sample_size
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
from p1.stats import binomial_pvalue, required_n_b, two_proportion_ztest

OUT = os.path.join(config.DATA_DIR, "report_figures")
BASE = 0.002           # background error rate on both variants (BASE_ERROR_RATE)
INJECTED = 0.05        # ERROR_RATE injected on v2 in the "errors" scenario
WEIGHT = 0.01
RATE = 150             # simulator requests/s
CHECK_S = 5
ALPHA, MIN_DIFF, CONSEC = 0.001, 0.01, 2


def simulate_detection(p_b, n_sims=4000, seed=0, max_checks=400):
    """Requests on v2 at the moment the controller rolls back."""
    rng = np.random.default_rng(seed)
    per_check_b = RATE * WEIGHT * CHECK_S
    per_check_a = RATE * (1 - WEIGHT) * CHECK_S
    out = []
    for _ in range(n_sims):
        n_b = x_b = n_a = x_a = 0
        streak = 0
        detected = None
        for _ in range(max_checks):
            nb = rng.poisson(per_check_b)
            na = rng.poisson(per_check_a)
            n_b += nb; x_b += rng.binomial(nb, p_b)
            n_a += na; x_a += rng.binomial(na, BASE)
            if n_b < 50:
                continue
            _, p = two_proportion_ztest(x_b, n_b, x_a, n_a)
            breach = (p < ALPHA and (x_b / n_b - x_a / n_a) >= MIN_DIFF
                      and binomial_pvalue(x_b, n_b, x_a, n_a) < ALPHA)
            streak = streak + 1 if breach else 0
            if streak >= CONSEC:
                detected = n_b
                break
        out.append(detected if detected is not None else np.nan)
    return np.array(out, dtype=float)


def live_results():
    rows = []
    for path in sorted(glob.glob(os.path.join(config.ROLLOUT_LOG_DIR, "*.jsonl"))):
        with open(path) as f:
            recs = [json.loads(line) for line in f]
        rb = [r for r in recs if r.get("event") == "rollback"]
        if rb and "error_rate" in rb[0]["guardrails"]:
            rows.append({"file": os.path.basename(path), "weight": rb[0]["weight"],
                         "n_b_at_rollback": rb[0]["n_b"]})
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    total = BASE + INJECTED
    results = {"base_error_rate": BASE, "v2_error_rate": total, "weight": WEIGHT,
               "alpha": ALPHA, "min_diff": MIN_DIFF}

    formula = {}
    for p_b in [0.012, 0.022, total, 0.102]:
        formula[f"{p_b:.3f}"] = required_n_b(BASE, p_b, ratio=(1 - WEIGHT) / WEIGHT,
                                             alpha=ALPHA, power=0.8)
    results["formula_n_b_80pct_power"] = formula

    sims = simulate_detection(total)
    results["monte_carlo"] = {
        "median_n_b": float(np.nanmedian(sims)), "p90_n_b": float(np.nanpercentile(sims, 90)),
        "detected_share": float(np.mean(~np.isnan(sims))),
        "median_seconds_at_1pct": float(np.nanmedian(sims) / (RATE * WEIGHT)),
    }
    results["live"] = live_results()

    # Figure: probability of detecting by n requests, for several injected rates.
    fig, ax = plt.subplots(figsize=(7, 4))
    for p_b, label in [(0.012, "+1 pt (1.2%)"), (0.022, "+2 pts (2.2%)"),
                       (total, f"+5 pts ({total:.1%}) - our scenario"), (0.102, "+10 pts")]:
        s = simulate_detection(p_b, n_sims=1500, seed=1)
        grid = np.arange(0, 1001, 10)
        ax.plot(grid, [(s <= g).mean() for g in grid], label=label)
    ax.axvline(results["monte_carlo"]["median_n_b"], color="grey", ls=":", lw=1)
    ax.set_xlabel("requests served by v2 (at 1% traffic)")
    ax.set_ylabel("P(controller has rolled back)")
    ax.set_title("How fast the error-rate guardrail detects a broken v2")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "q1_detection_curve.png"), dpi=130)

    with open(os.path.join(OUT, "q1_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
