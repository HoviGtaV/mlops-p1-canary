"""Offline comparison of v1 and v2 (validation + test), and the score
distributions that explain the healthy PSI baseline. Also measures how much the
silent schema bug moves v2's scores offline.

Run inside the stack:  docker compose run --rm trainer python -m analysis.offline_models
"""
from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
from sklearn.metrics import roc_auc_score, roc_curve

from p1 import config
from p1.data import load_split
from p1.features import FEATURES, make_target
from p1.stats import bin_counts, psi

OUT = os.path.join(config.DATA_DIR, "report_figures")


def main():
    os.makedirs(OUT, exist_ok=True)
    mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
    v1 = mlflow.sklearn.load_model(f"models:/{config.MODEL_NAME}@champion")
    v2 = mlflow.sklearn.load_model(f"models:/{config.MODEL_NAME}@challenger")
    test = load_split("test")
    X, y = test[FEATURES], make_target(test)
    s1, s2 = v1.predict_proba(X)[:, 1], v2.predict_proba(X)[:, 1]
    bug = X.rename(columns={"number_inpatient": "num_inpatient"})
    s2_bug = v2.predict_proba(bug)[:, 1]

    b = config.SCORE_BUCKETS
    res = {
        "test_auc": {"v1": roc_auc_score(y, s1), "v2": roc_auc_score(y, s2),
                     "v2_with_schema_bug": roc_auc_score(y, s2_bug)},
        "mean_score": {"v1": s1.mean(), "v2": s2.mean(), "v2_with_schema_bug": s2_bug.mean()},
        "psi_vs_v1": {"v2": psi(bin_counts(s1, b), bin_counts(s2, b)),
                      "v2_with_schema_bug": psi(bin_counts(s1, b), bin_counts(s2_bug, b))},
        "psi_v2_bug_vs_v2": psi(bin_counts(s2, b), bin_counts(s2_bug, b)),
        "positive_rate": float(y.mean()),
    }

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for s, label, c in [(s1, f"v1 logistic regression (AUC {res['test_auc']['v1']:.3f})", "tab:blue"),
                        (s2, f"v2 gradient boosting (AUC {res['test_auc']['v2']:.3f})", "tab:orange"),
                        (s2_bug, f"v2 + schema bug (AUC {res['test_auc']['v2_with_schema_bug']:.3f})",
                         "tab:red")]:
        fpr, tpr, _ = roc_curve(y, s)
        axes[0].plot(fpr, tpr, label=label, color=c)
    axes[0].plot([0, 1], [0, 1], color="grey", ls=":")
    axes[0].set_xlabel("false positive rate")
    axes[0].set_ylabel("true positive rate")
    axes[0].set_title("ROC on the test split (patients never seen in training)")
    axes[0].legend(fontsize=8)

    edges = [0.0] + b
    widths = np.diff(edges)
    for s, label, c, off in [(s1, "v1", "tab:blue", 0.0), (s2, "v2", "tab:orange", 1 / 3),
                             (s2_bug, "v2 + schema bug", "tab:red", 2 / 3)]:
        share = bin_counts(s, b) / len(s)
        axes[1].bar(np.arange(len(b)) + off, share, width=1 / 3, label=label, color=c, align="edge")
    axes[1].set_xticks(np.arange(len(b)) + 0.5)
    axes[1].set_xticklabels([f"{e:.2f}" for e in b], rotation=60, fontsize=7)
    axes[1].set_xlabel("score bucket (upper bound)")
    axes[1].set_ylabel("share of patients")
    axes[1].set_title(f"Score distributions - PSI(v2 vs v1) = {res['psi_vs_v1']['v2']:.3f}, "
                      f"with bug = {res['psi_vs_v1']['v2_with_schema_bug']:.3f}", fontsize=10)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "offline_models.png"), dpi=130)

    with open(os.path.join(OUT, "offline_results.json"), "w") as f:
        json.dump(res, f, indent=2, default=float)
    print(json.dumps(res, indent=2, default=float))


if __name__ == "__main__":
    main()
