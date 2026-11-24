"""Settings shared by every service. Everything can be overridden by environment variables."""
from __future__ import annotations

import os

SEED = int(os.getenv("SEED", "42"))

MODEL_NAME = os.getenv("MODEL_NAME", "readmission")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
EXPERIMENT_NAME = os.getenv("EXPERIMENT_NAME", "p1-readmission")

DATA_DIR = os.getenv("DATA_DIR", "/data")
RAW_CSV = os.path.join(DATA_DIR, "raw", "diabetic_data.csv")
SPLIT_DIR = os.path.join(DATA_DIR, "splits")
ROLLOUT_LOG_DIR = os.path.join(DATA_DIR, "rollouts")
ROUTER_LOG_DIR = os.path.join(DATA_DIR, "router_logs")

# Upper bounds of the score histogram (Prometheus buckets). The same edges are
# used offline (reference distribution) and online (PSI guardrail), so the two
# are directly comparable. Scores concentrate below 0.3 (base rate ~ 11%), so
# the buckets are finer there.
SCORE_BUCKETS = [0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20,
                 0.25, 0.30, 0.40, 0.50, 0.70, 1.0]

# End-to-end latency buckets (seconds) measured by the router.
LATENCY_BUCKETS = [0.002, 0.004, 0.006, 0.008, 0.010, 0.012, 0.015, 0.020,
                   0.025, 0.0275, 0.030, 0.0325, 0.035, 0.0375, 0.040, 0.045,
                   0.050, 0.055, 0.060, 0.070, 0.080, 0.090, 0.100, 0.125, 0.150,
                   0.200, 0.250, 0.500, 1.0, 2.5]
