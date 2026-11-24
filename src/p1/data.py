"""Load the UCI Diabetes data and split it by patient (70/15/15, fixed seed)."""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

from p1 import config
from p1.features import EXCLUDED_DISCHARGE


def load_raw() -> pd.DataFrame:
    if not os.path.exists(config.RAW_CSV):
        from ucimlrepo import fetch_ucirepo

        print("Downloading UCI dataset #296 ...", flush=True)
        d = fetch_ucirepo(id=296)
        df = pd.concat([d.data.ids, d.data.features, d.data.targets], axis=1)
        os.makedirs(os.path.dirname(config.RAW_CSV), exist_ok=True)
        df.to_csv(config.RAW_CSV, index=False)
    return pd.read_csv(config.RAW_CSV, low_memory=False, na_values=["?"])


def split_by_patient(df: pd.DataFrame, seed: int = config.SEED,
                     fractions=(0.70, 0.15, 0.15)) -> dict[str, pd.DataFrame]:
    """Each patient_nbr lands in exactly one split, so a patient's later
    encounters can never leak from train into validation or test."""
    df = df[~df["discharge_disposition_id"].isin(EXCLUDED_DISCHARGE)].reset_index(drop=True)
    patients = np.sort(df["patient_nbr"].unique())
    rng = np.random.default_rng(seed)
    rng.shuffle(patients)
    n = len(patients)
    n_train = int(round(fractions[0] * n))
    n_val = int(round(fractions[1] * n))
    groups = {
        "train": set(patients[:n_train]),
        "val": set(patients[n_train:n_train + n_val]),
        "test": set(patients[n_train + n_val:]),
    }
    return {name: df[df["patient_nbr"].isin(ids)].reset_index(drop=True)
            for name, ids in groups.items()}


def write_splits(splits: dict[str, pd.DataFrame]) -> dict:
    os.makedirs(config.SPLIT_DIR, exist_ok=True)
    summary = {}
    for name, part in splits.items():
        part.to_csv(os.path.join(config.SPLIT_DIR, f"{name}.csv"), index=False)
        summary[name] = {
            "encounters": int(len(part)),
            "patients": int(part["patient_nbr"].nunique()),
            "positive_rate": round(float((part["readmitted"] == "<30").mean()), 4),
        }
    with open(os.path.join(config.SPLIT_DIR, "split_summary.json"), "w") as f:
        json.dump({"seed": config.SEED, "splits": summary}, f, indent=2)
    return summary


def load_split(name: str) -> pd.DataFrame:
    return pd.read_csv(os.path.join(config.SPLIT_DIR, f"{name}.csv"), low_memory=False)
