"""How the score-PSI threshold was chosen.

The canary sends a *subset of patients* (sticky by user) to v2. At low traffic
that subset is small, so v2's score distribution differs from v1's just because
the patients differ, even when v2 is perfectly healthy. This simulation draws
many random patient subsets of the size the canary gives at each step and
compares the PSI of a healthy v2 with the PSI of v2 with the schema bug.

Run inside the stack:  docker compose run --rm trainer python -m analysis.psi_calibration
"""
from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np

from p1 import config
from p1.data import load_split
from p1.features import FEATURES
from p1.stats import bin_counts, psi

OUT = os.path.join(config.DATA_DIR, "report_figures")
CASES = [(0.01, 300), (0.05, 500), (0.05, 700), (0.25, 1000)]
THRESHOLD = 0.15


def main(n_sims=400):
    os.makedirs(OUT, exist_ok=True)
    mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
    v1 = mlflow.sklearn.load_model(f"models:/{config.MODEL_NAME}@champion")
    v2 = mlflow.sklearn.load_model(f"models:/{config.MODEL_NAME}@challenger")
    test = load_split("test")
    X = test[FEATURES]
    s1 = v1.predict_proba(X)[:, 1]
    s2 = v2.predict_proba(X)[:, 1]
    s2_bug = v2.predict_proba(X.rename(columns={"number_inpatient": "num_inpatient"}))[:, 1]
    B = config.SCORE_BUCKETS

    patients = test["patient_nbr"].to_numpy()
    uniq, inv = np.unique(patients, return_inverse=True)
    rng = np.random.default_rng(config.SEED)
    res = {"population_psi": {"v2_vs_v1": psi(bin_counts(s1, B), bin_counts(s2, B)),
                              "v2_bug_vs_v1": psi(bin_counts(s1, B), bin_counts(s2_bug, B))},
           "threshold": THRESHOLD, "cases": []}
    fig, axes = plt.subplots(1, len(CASES), figsize=(15, 3.8), sharey=True)
    for ax, (w, n) in zip(axes, CASES):
        healthy, bug = [], []
        for _ in range(n_sims):
            on_b = (rng.random(len(uniq)) < w)[inv]
            idx_b = rng.choice(np.flatnonzero(on_b), n)
            idx_a = rng.choice(np.flatnonzero(~on_b), 20_000)
            ref = bin_counts(s1[idx_a], B)
            healthy.append(psi(ref, bin_counts(s2[idx_b], B)))
            bug.append(psi(ref, bin_counts(s2_bug[idx_b], B)))
        healthy, bug = np.array(healthy), np.array(bug)
        case = {"weight": w, "n_b": n, "patients_on_v2": int(w * len(uniq)),
                "healthy_p50": float(np.median(healthy)), "healthy_p99": float(np.percentile(healthy, 99)),
                "bug_p5": float(np.percentile(bug, 5)), "bug_p50": float(np.median(bug)),
                "false_alarm_at_threshold": float((healthy > THRESHOLD).mean()),
                "detection_at_threshold": float((bug > THRESHOLD).mean())}
        res["cases"].append(case)
        bins = np.linspace(0, max(0.6, np.percentile(bug, 99)), 40)
        ax.hist(healthy, bins=bins, alpha=0.6, label="healthy v2", color="tab:green")
        ax.hist(bug, bins=bins, alpha=0.6, label="v2 + schema bug", color="tab:red")
        ax.axvline(THRESHOLD, color="black", ls="--", lw=1)
        ax.set_title(f"{w:.0%} traffic (~{case['patients_on_v2']} patients), {n} requests\n"
                     f"false alarm {case['false_alarm_at_threshold']:.0%}, "
                     f"detection {case['detection_at_threshold']:.0%}", fontsize=9)
        ax.set_xlabel("PSI(v2 scores vs v1 scores)")
    axes[0].set_ylabel("simulated canaries")
    axes[0].legend(fontsize=8)
    fig.suptitle(f"Why the PSI guardrail only starts at 5% traffic (threshold {THRESHOLD})")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "psi_calibration.png"), dpi=120)
    with open(os.path.join(OUT, "psi_calibration.json"), "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
