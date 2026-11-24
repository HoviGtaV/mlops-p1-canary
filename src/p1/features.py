"""Feature schema and the raw-to-model cleaning step.

The cleaning step is a plain function used inside both sklearn pipelines, so the
serving code sends raw values (exactly as they appear in the CSV) and the model
artifact in MLflow carries its own preprocessing.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

TARGET = "readmitted"
POSITIVE_LABEL = "<30"
ID_COLS = ["encounter_id", "patient_nbr"]

# "weight" is 97% missing: dropped.
NUMERIC = [
    "time_in_hospital",
    "num_lab_procedures",
    "num_procedures",
    "num_medications",
    "number_outpatient",
    "number_emergency",
    "number_inpatient",
    "number_diagnoses",
]

CATEGORICAL = [
    "race", "gender", "age",
    "admission_type_id", "discharge_disposition_id", "admission_source_id",
    "payer_code", "medical_specialty",
    "diag_1", "diag_2", "diag_3",
    "max_glu_serum", "A1Cresult",
    "metformin", "repaglinide", "nateglinide", "chlorpropamide", "glimepiride",
    "acetohexamide", "glipizide", "glyburide", "tolbutamide", "pioglitazone",
    "rosiglitazone", "acarbose", "miglitol", "troglitazone", "tolazamide",
    "examide", "citoglipton", "insulin", "glyburide-metformin",
    "glipizide-metformin", "glimepiride-pioglitazone", "metformin-rosiglitazone",
    "metformin-pioglitazone", "change", "diabetesMed",
]

FEATURES = NUMERIC + CATEGORICAL

# Discharge codes meaning the patient died or went to hospice: they cannot be
# readmitted, so they are removed from training and from the replayed traffic.
EXCLUDED_DISCHARGE = {11, 13, 14, 19, 20, 21}

DIAG_COLS = ["diag_1", "diag_2", "diag_3"]


def _to_category(value):
    if value is None:
        return np.nan
    if isinstance(value, float) and math.isnan(value):
        return np.nan
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return np.nan if text in ("", "?", "nan", "None") else text


def _diag_group(value):
    """ICD-9 code '250.83' -> '250'; 'V57' stays 'V57'."""
    value = _to_category(value)
    if isinstance(value, float):
        return value
    return value.split(".")[0]


def clean_features(X: pd.DataFrame) -> pd.DataFrame:
    """Raw frame (any column order, missing columns allowed) -> clean model input.

    Missing columns are added as NaN and later filled by the pipeline's imputers.
    This is what makes the injected schema bug *silent*: a renamed column is not
    an error, it is just imputed.
    """
    X = X.reindex(columns=FEATURES)
    # Element-wise numpy ufuncs on object arrays: fast for one row (serving)
    # and fine for 70k rows (training).
    num = _NUM(X[NUMERIC].to_numpy(dtype=object)).astype("float64")
    cat = _CAT(X[CATEGORICAL].to_numpy(dtype=object))
    cat[:, _DIAG_IDX] = _DIAG(cat[:, _DIAG_IDX])
    return pd.concat([pd.DataFrame(num, columns=NUMERIC, index=X.index),
                      pd.DataFrame(cat, columns=CATEGORICAL, index=X.index, dtype=object)],
                     axis=1)


def _to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


_NUM = np.frompyfunc(_to_number, 1, 1)
_CAT = np.frompyfunc(_to_category, 1, 1)
_DIAG = np.frompyfunc(_diag_group, 1, 1)
_DIAG_IDX = [CATEGORICAL.index(c) for c in DIAG_COLS]


def make_target(df: pd.DataFrame) -> np.ndarray:
    return (df[TARGET] == POSITIVE_LABEL).astype(int).to_numpy()


def row_to_payload(row: pd.Series) -> dict:
    """One CSV row -> JSON-safe dict of raw feature values."""
    payload = {}
    for col in FEATURES:
        value = row[col]
        if value is None or (isinstance(value, float) and math.isnan(value)):
            payload[col] = None
        elif isinstance(value, (np.integer,)):
            payload[col] = int(value)
        elif isinstance(value, (np.floating,)):
            payload[col] = float(value)
        else:
            payload[col] = value
    return payload


class TabularEncoder(BaseEstimator, TransformerMixin):
    """Raw frame -> model matrix, in one fast step (fit/transform, sklearn-compatible).

    * numeric columns: median imputation (+ standardisation if `scale`)
    * categorical columns: categories seen at least `min_frequency` times are kept
      (at most `max_categories`, the rest -> "other"); missing -> "missing".
      mode="onehot"  -> sparse one-hot matrix (logistic regression)
      mode="ordinal" -> integer codes, for native categorical support (gradient boosting)

    Why not ColumnTransformer + OneHotEncoder: on a single row (online serving)
    they cost ~30 ms of Python overhead; this costs well under 1 ms.
    A column missing from the input (e.g. renamed upstream) is imputed, not rejected.
    """

    def __init__(self, mode="onehot", min_frequency=50, max_categories=None, scale=True):
        self.mode = mode
        self.min_frequency = min_frequency
        self.max_categories = max_categories
        self.scale = scale

    def __sklearn_is_fitted__(self):
        return hasattr(self, "maps_")

    # ----------------------------------------------------------------------
    @staticmethod
    def _prep(X):
        if isinstance(X, list):        # fast path for serving: list of raw dicts
            arr = np.array([[d.get(c) for c in FEATURES] for d in X], dtype=object)
        else:
            if not isinstance(X, pd.DataFrame):
                X = pd.DataFrame(X)
            arr = X.reindex(columns=FEATURES).to_numpy(dtype=object)
        n_num = len(NUMERIC)
        num = _NUM(arr[:, :n_num]).astype("float64")
        cat = _CAT(arr[:, n_num:])
        cat[:, _DIAG_IDX] = _DIAG(cat[:, _DIAG_IDX])
        return num, cat

    @staticmethod
    def _key(v):
        return "missing" if isinstance(v, float) else v

    def fit(self, X, y=None):
        num, cat = self._prep(X)
        self.medians_ = np.nanmedian(num, axis=0)
        num = np.where(np.isnan(num), self.medians_, num)
        self.means_ = num.mean(axis=0)
        self.stds_ = num.std(axis=0) + 1e-9
        self.maps_ = []
        for j in range(cat.shape[1]):
            counts = pd.Series([self._key(v) for v in cat[:, j]], dtype=object).value_counts()
            keep = counts[counts >= self.min_frequency]
            if self.max_categories:
                keep = keep.iloc[: self.max_categories - 1]   # one code reserved for "other"
            self.maps_.append({v: i for i, v in enumerate(keep.index)})
        widths = [len(m) + 1 for m in self.maps_]
        self.offsets_ = np.concatenate([[0], np.cumsum(widths)[:-1]]).astype(int)
        self.n_onehot_ = int(sum(widths))
        return self

    def transform(self, X):
        from scipy import sparse

        num, cat = self._prep(X)
        num = np.where(np.isnan(num), self.medians_, num)
        if self.scale:
            num = (num - self.means_) / self.stds_
        key = self._key
        codes = np.empty(cat.shape, dtype=np.int64)
        for j, m in enumerate(self.maps_):
            other = len(m)
            codes[:, j] = [m.get(key(v), other) for v in cat[:, j]]
        if self.mode == "ordinal":
            return np.hstack([num, codes.astype("float64")])
        n = len(num)
        rows = np.repeat(np.arange(n), codes.shape[1])
        cols = (codes + self.offsets_).ravel()
        onehot = sparse.csr_matrix((np.ones(len(cols)), (rows, cols)), shape=(n, self.n_onehot_))
        return sparse.hstack([sparse.csr_matrix(num), onehot], format="csr")

