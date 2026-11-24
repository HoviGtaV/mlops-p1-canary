import numpy as np
import pandas as pd

from p1.features import FEATURES, clean_features
from p1.router import bucket, choose_variant
from p1.stats import (bin_counts, histogram_quantile, psi, required_n_b,
                      two_proportion_ztest)


def test_ztest_detects_higher_error_rate():
    z, p = two_proportion_ztest(x_b=30, n_b=500, x_a=100, n_a=50_000)
    assert z > 0 and p < 1e-6


def test_ztest_one_sided_ignores_better_variant():
    _, p = two_proportion_ztest(x_b=0, n_b=500, x_a=500, n_a=50_000)
    assert p > 0.5


def test_required_n_grows_when_effect_shrinks():
    assert required_n_b(0.002, 0.05, 99) < required_n_b(0.002, 0.02, 99)


def test_psi_zero_for_identical_and_positive_for_shift():
    a = [10, 20, 30, 40]
    assert psi(a, a) < 1e-9
    assert psi(a, [40, 30, 20, 10]) > 0.25


def test_bin_counts_prometheus_semantics():
    counts = bin_counts([0.02, 0.021, 0.5, 1.0], [0.02, 0.1, 1.0])
    assert counts.tolist() == [1, 1, 2]


def test_histogram_quantile_matches_numpy_roughly():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 1, 100_000)
    bounds = list(np.linspace(0.05, 1.0, 20))
    cum = np.cumsum(bin_counts(x, bounds)).tolist() + [len(x)]
    assert abs(histogram_quantile(0.99, bounds, cum) - 0.99) < 0.01


def test_router_is_sticky_and_monotonic():
    users = [str(i) for i in range(5000)]
    at_1 = {u for u in users if choose_variant(u, 0.01) == "b"}
    at_5 = {u for u in users if choose_variant(u, 0.05) == "b"}
    assert at_1 <= at_5                       # users on B stay on B when the weight grows
    assert 0.03 < len(at_5) / len(users) < 0.07
    assert bucket("123") == bucket("123")
    assert all(choose_variant(u, 0.0) == "a" for u in users[:100])


def test_clean_features_imputes_missing_column_silently():
    raw = pd.DataFrame([{"num_inpatient": 3, "age": "[70-80)", "diag_1": "250.83"}])
    out = clean_features(raw)
    assert list(out.columns) == FEATURES
    assert np.isnan(out.loc[0, "number_inpatient"])   # the renamed column is just missing
    assert out.loc[0, "diag_1"] == "250"


def test_exact_test_does_not_fire_on_one_rare_error():
    from p1.stats import binomial_pvalue
    z, p_z = two_proportion_ztest(1, 58, 20, 10_000)      # z-test says "significant"
    assert p_z < 0.01
    assert binomial_pvalue(1, 58, 20, 10_000) > 0.05      # exact test disagrees
    assert binomial_pvalue(6, 100, 20, 10_000) < 1e-6     # real 5% error rate: caught
