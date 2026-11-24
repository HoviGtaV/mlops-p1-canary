"""Train v1 (logistic regression) and v2 (gradient boosting), register both in
MLflow, and set the aliases v1 -> @champion, v2 -> @challenger.

Idempotent: if both aliases already exist the script exits, unless FORCE_RETRAIN=1.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

import mlflow
import numpy as np
import pandas as pd
from mlflow import MlflowClient
from mlflow.models import infer_signature
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline

from p1 import config
from p1.data import load_raw, split_by_patient, write_splits
from p1.features import CATEGORICAL, FEATURES, NUMERIC, TabularEncoder, make_target
from p1.stats import bin_counts, psi


def build_v1() -> Pipeline:
    """Logistic regression on one-hot categories and standardised numerics."""
    return Pipeline([
        ("encode", TabularEncoder(mode="onehot", min_frequency=50, scale=True)),
        ("model", LogisticRegression(max_iter=3000, C=0.5)),
    ])


def build_v2() -> Pipeline:
    """Gradient boosting with native categorical support (top-10 categories per column)."""
    is_cat = [False] * len(NUMERIC) + [True] * len(CATEGORICAL)
    model = HistGradientBoostingClassifier(
        learning_rate=0.1, max_iter=1500, max_leaf_nodes=31, min_samples_leaf=100,
        l2_regularization=1.0, categorical_features=is_cat, early_stopping=True,
        validation_fraction=0.1, n_iter_no_change=60, random_state=config.SEED,
    )
    return Pipeline([
        ("encode", TabularEncoder(mode="ordinal", min_frequency=50, max_categories=10, scale=False)),
        ("model", model),
    ])


def top_k_recall(y, s, frac=0.15):
    k = int(len(s) * frac)
    idx = np.argsort(-s)[:k]
    return float(y[idx].sum() / max(y.sum(), 1))


def single_row_latency_ms(pipe, X: pd.DataFrame, n: int = 400) -> dict:
    """Latency of one prediction as the service does it (one raw dict, one thread)."""
    from threadpoolctl import threadpool_limits

    rows = X.sample(n, random_state=config.SEED).to_dict("records")
    times = []
    with threadpool_limits(1):
        for r in rows[:20]:                       # warm-up
            pipe.predict_proba([r])
        for r in rows:
            t0 = time.perf_counter()
            pipe.predict_proba([r])
            times.append((time.perf_counter() - t0) * 1000)
    times = np.array(times)
    return {"p50_ms": float(np.percentile(times, 50)), "p99_ms": float(np.percentile(times, 99))}


def aliases_exist(client: MlflowClient) -> bool:
    try:
        client.get_model_version_by_alias(config.MODEL_NAME, "champion")
        client.get_model_version_by_alias(config.MODEL_NAME, "challenger")
        return True
    except Exception:
        return False


def wait_for_mlflow(timeout=120):
    import httpx
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(config.MLFLOW_TRACKING_URI + "/health", timeout=3).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("MLflow server not reachable")


def main():
    mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
    wait_for_mlflow()
    client = MlflowClient()
    if aliases_exist(client) and os.getenv("FORCE_RETRAIN", "0") != "1" \
            and os.path.exists(os.path.join(config.SPLIT_DIR, "test.csv")):
        print("Models already registered (@champion, @challenger). Skipping training.")
        return

    raw = load_raw()
    splits = split_by_patient(raw)
    summary = write_splits(splits)
    print("Split by patient:", json.dumps(summary))

    X = {k: v[FEATURES] for k, v in splits.items()}
    y = {k: make_target(v) for k, v in splits.items()}

    mlflow.set_experiment(config.EXPERIMENT_NAME)
    results = {}
    val_scores = {}
    for name, builder, algo in [("v1", build_v1, "logistic_regression"),
                                ("v2", build_v2, "hist_gradient_boosting")]:
        pipe = builder()
        with mlflow.start_run(run_name=f"{name}-{algo}") as run:
            t0 = time.time()
            pipe.fit(X["train"], y["train"])
            fit_s = time.time() - t0
            metrics = {"fit_seconds": fit_s}
            for split in ("val", "test"):
                s = pipe.predict_proba(X[split])[:, 1]
                metrics[f"{split}_auc"] = roc_auc_score(y[split], s)
                metrics[f"{split}_avg_precision"] = average_precision_score(y[split], s)
                metrics[f"{split}_brier"] = brier_score_loss(y[split], s)
                metrics[f"{split}_recall_top15"] = top_k_recall(y[split], s)
                if split == "val":
                    val_scores[name] = s
            lat = single_row_latency_ms(pipe, X["val"])
            metrics.update({f"single_row_{k}": v for k, v in lat.items()})
            mlflow.log_metrics(metrics)
            mlflow.log_params({"algorithm": algo, "seed": config.SEED,
                               "split": "by patient_nbr 70/15/15",
                               "target": "readmitted == '<30'",
                               "n_train": len(X["train"])})
            if name == "v2":
                mlflow.log_param("n_iter", int(pipe.named_steps["model"].n_iter_))

            # Reference score distribution on validation, saved with the model
            # version: it is what the online PSI is compared against.
            ref = {"bucket_upper_bounds": config.SCORE_BUCKETS,
                   "val_counts": bin_counts(val_scores[name], config.SCORE_BUCKETS).tolist(),
                   "val_mean_score": float(np.mean(val_scores[name])),
                   "single_row_latency": lat}
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "reference.json")
                with open(path, "w") as f:
                    json.dump(ref, f, indent=2)
                mlflow.log_artifact(path)

            example = X["val"].head(3)
            info = mlflow.sklearn.log_model(
                pipe, name="model", registered_model_name=config.MODEL_NAME,
                input_example=example,
                # MLflow 3 defaults to skops, which refuses HistGradientBoosting
                # internals. These models are produced and consumed only inside
                # this stack, so the classic cloudpickle format is acceptable.
                serialization_format="cloudpickle",
                signature=infer_signature(example, pipe.predict_proba(example)[:, 1]),
            )
            results[name] = {"run_id": run.info.run_id, "metrics": metrics,
                             "version": info.registered_model_version}
            print(f"{name}: " + ", ".join(f"{k}={v:.4f}" for k, v in metrics.items()), flush=True)

    # Expected PSI between healthy v2 and v1 (same patients, different models):
    # the online guardrail threshold must sit above this baseline.
    v1_counts = bin_counts(val_scores["v1"], config.SCORE_BUCKETS)
    v2_counts = bin_counts(val_scores["v2"], config.SCORE_BUCKETS)
    baseline_psi = psi(v1_counts, v2_counts)
    print(f"Offline PSI(v2 vs v1) on validation: {baseline_psi:.4f}")

    v1_version, v2_version = results["v1"]["version"], results["v2"]["version"]
    client.set_registered_model_alias(config.MODEL_NAME, "champion", v1_version)
    client.set_registered_model_alias(config.MODEL_NAME, "challenger", v2_version)
    client.set_model_version_tag(config.MODEL_NAME, v2_version, "offline_psi_vs_champion",
                                 f"{baseline_psi:.4f}")
    # Extra compute v2 costs per request (accepted when v2 was approved offline).
    # The online latency guardrail allows for it and catches anything beyond.
    overhead = max(results["v2"]["metrics"]["single_row_p99_ms"]
                   - results["v1"]["metrics"]["single_row_p99_ms"], 0.0)
    client.set_model_version_tag(config.MODEL_NAME, v2_version, "offline_latency_overhead_ms",
                                 f"{overhead:.2f}")
    for name, ver in [("v1", v1_version), ("v2", v2_version)]:
        client.set_model_version_tag(config.MODEL_NAME, ver, "role", name)
        client.set_model_version_tag(config.MODEL_NAME, ver, "val_auc",
                                     f"{results[name]['metrics']['val_auc']:.4f}")

    out = {"v1": results["v1"], "v2": results["v2"],
           "offline_psi_v2_vs_v1": baseline_psi, "offline_latency_overhead_ms": overhead, "split_summary": summary}
    with open(os.path.join(config.DATA_DIR, "training_summary.json"), "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"Registered {config.MODEL_NAME} v{v1_version} @champion, v{v2_version} @challenger")


if __name__ == "__main__":
    main()
