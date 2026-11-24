"""Statistics behind the guardrails (also used by the report analyses and tests)."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy.stats import norm


def two_proportion_ztest(x_b: int, n_b: int, x_a: int, n_a: int) -> tuple[float, float]:
    """One-sided test. H0: p_b <= p_a, H1: p_b > p_a (v2 fails more often than v1).

    Returns (z, p_value). Uses the pooled standard error.
    """
    if n_a <= 0 or n_b <= 0:
        return 0.0, 1.0
    p_a, p_b = x_a / n_a, x_b / n_b
    pooled = (x_a + x_b) / (n_a + n_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    if se == 0:
        return 0.0, 1.0
    z = (p_b - p_a) / se
    return z, float(norm.sf(z))


def required_n_b(p_a: float, p_b: float, ratio: float, alpha: float = 0.01,
                 power: float = 0.8) -> int:
    """Requests needed on variant B to detect p_b > p_a with a one-sided
    two-proportion z-test, when A gets `ratio` times more traffic than B
    (ratio = 99 at 1% canary traffic)."""
    z_a, z_b = norm.isf(alpha), norm.isf(1 - power)
    n_a_over_n_b = ratio
    pbar = (p_a * n_a_over_n_b + p_b) / (n_a_over_n_b + 1)
    k = 1 + 1 / n_a_over_n_b
    num = (z_a * math.sqrt(pbar * (1 - pbar) * k)
           + abs(z_b) * math.sqrt(p_b * (1 - p_b) + p_a * (1 - p_a) / n_a_over_n_b)) ** 2
    return int(math.ceil(num / (p_b - p_a) ** 2))


def psi(expected_counts: Sequence[float], actual_counts: Sequence[float],
        eps: float = 1e-4) -> float:
    """Population Stability Index between two histograms on the same bins."""
    e = np.asarray(expected_counts, dtype=float)
    a = np.asarray(actual_counts, dtype=float)
    if e.sum() <= 0 or a.sum() <= 0:
        return float("nan")
    e = np.clip(e / e.sum(), eps, None)
    a = np.clip(a / a.sum(), eps, None)
    return float(np.sum((a - e) * np.log(a / e)))


def bin_counts(values: Sequence[float], upper_bounds: Sequence[float]) -> np.ndarray:
    """Counts per bin with Prometheus semantics: bin i holds bounds[i-1] < v <= bounds[i]."""
    values = np.asarray(values, dtype=float)
    edges = np.concatenate([[-np.inf], np.asarray(upper_bounds, dtype=float)])
    edges[-1] = np.inf
    idx = np.searchsorted(edges, values, side="left") - 1
    idx = np.clip(idx, 0, len(upper_bounds) - 1)
    return np.bincount(idx, minlength=len(upper_bounds)).astype(float)


def histogram_quantile(q: float, upper_bounds: Sequence[float],
                       cumulative_counts: Sequence[float]) -> float:
    """Same linear interpolation as PromQL histogram_quantile().

    `upper_bounds` excludes +Inf; `cumulative_counts` has one more entry (the +Inf bucket).
    """
    cum = np.asarray(cumulative_counts, dtype=float)
    total = cum[-1]
    if total <= 0:
        return float("nan")
    rank = q * total
    bounds = list(upper_bounds)
    for i, c in enumerate(cum):
        if c >= rank:
            if i >= len(bounds):          # falls in the +Inf bucket
                return float(bounds[-1])
            lower = 0.0 if i == 0 else bounds[i - 1]
            prev = 0.0 if i == 0 else cum[i - 1]
            in_bucket = c - prev
            if in_bucket <= 0:
                return float(bounds[i])
            return float(lower + (bounds[i] - lower) * (rank - prev) / in_bucket)
    return float(bounds[-1])


def binomial_pvalue(x_b: int, n_b: int, x_a: int, n_a: int) -> float:
    """Exact one-sided check: P(X >= x_b) for X ~ Binomial(n_b, p_a), with p_a
    estimated on v1 (which has ~100x more traffic, so its rate is nearly known).

    Unlike the z-test, it stays valid when v2 has few requests and errors are
    rare (1 error in 58 requests is *not* evidence against a 0.2% base rate).
    """
    from scipy.stats import binom

    if n_b <= 0 or x_b <= 0:
        return 1.0
    p_a = max(x_a, 0.5) / max(n_a, 1)
    return float(binom.sf(x_b - 1, n_b, p_a))
