# Likely questions and short answers

## Concepts

**What is a canary release?**
Sending a new version to a small share of users first (1%), checking it is healthy, then increasing
the share step by step (5, 25, 100%). If something breaks, only a few users are affected and we
roll back.

**Canary vs A/B test?**
A canary answers "is v2 **safe**?" (no errors, acceptable latency, sane outputs) quickly, with a
small share of traffic. An A/B test answers "is v2 **better** on a business metric?" with a planned
sample size, a fixed duration and a random 50/50 split.

**Why can't the canary tell you whether v2 is better?** (report question 3)
1. The business outcome (readmission within 30 days) is only known a month later; the canary lasts
   minutes.
2. The effect is tiny (AUC 0.676 vs 0.663) and the canary sees a few hundred v2 requests: far too
   few to measure a difference in readmissions.
3. The canary's traffic share changes during the rollout and is not a balanced randomised design.
4. Its guardrails are one-sided "not worse" checks, not "better" tests.
Offline AUC is our evidence that v2 is better; an A/B test (project P2) is how to prove it in
production.

**Why sticky routing by user?**
So one patient always gets the same model (consistent experience, and their requests are not split
between two models). Raising the weight from 1% to 5% keeps the users already on v2 on v2 and adds
new ones.

**What does a rollback do exactly?**
Sets the router weight for v2 to 0. Nothing else: the MLflow aliases do not change (v1 stays
`@champion`, v2 stays `@challenger`), and the version gets a tag `canary_result=rolled_back: ...`.

## The guardrails

**Explain the z-test.**
We compare the share of failed requests on v2 and v1. Under "v2 is not worse", the difference
divided by its standard error follows a normal distribution. If z is very large (p < 0.001), v2
fails more often than chance explains. One-sided: we only care if v2 is *worse*.

**Why did you add an exact binomial test?**
Errors are rare (0.2%) and at 1% traffic v2 has only ~60 requests at first. The z-test relies on a
normal approximation which breaks down there: one unlucky error in 58 requests looked "significant"
and rolled back a healthy v2. The exact binomial test computes the real probability (1 error in 58
at 0.2% happens ~11% of the time: not evidence). We still compute the z-test; the exact test must
agree.

**Why alpha = 0.001 and not 0.05?**
The controller checks every 5 seconds, about 60 times per rollout. With 0.05 per check, false
alarms add up. 0.05 / 60 ≈ 0.001 (Bonferroni idea). A real 5% error rate is so far from 0.2% that
it is still caught after ~65 requests.

**What is PSI?**
Population Stability Index: compares two histograms (here v2's predicted risk vs v1's) bin by bin:
sum of (share_B − share_A) × ln(share_B / share_A). 0 = identical; below 0.1 small; above 0.2 large.

**Why does PSI only start at 5% traffic?**
At 1% traffic v2 sees only ~100 patients. Their risk distribution differs from the general
population just by chance, so a *healthy* v2 often has PSI 0.2-0.5: we simulated it, PSI cannot
separate healthy from buggy there (67% false alarms). At 5% (~500 patients) healthy stays below
0.14 (p99) and the bug is above 0.15 in 95% of cases.

**Why is the PSI threshold 0.15?**
From the calibration simulation (`analysis/psi_calibration.py`): just above the 99th percentile of
a healthy v2 at 5% traffic and 500 requests, and below most schema-bug values.

**Why is the latency limit not just 1.1 × v1?**
v2 is heavier by design (gradient boosting with ~90 trees vs one logistic regression): about 30 ms
vs 6 ms at p99. The literal rule "≤ 1.1 × v1" would roll back every healthy v2. The extra cost was
accepted when v2 was approved, so we measured it offline (27 ms, stored as a tag on the model
version) and the limit is 1.1 × (v1's live p99 + 1.5 × 27 ms) ≈ 52 ms. The 1.5 factor is headroom
because the offline benchmark runs on an idle CPU; under real load v2's p99 reached ~40 ms. Trade-off:
a regression smaller than ~15 ms would not be caught.

**Why does p99 need 300 requests?**
The p99 of 100 requests is basically the single slowest one: very noisy. It caused a false rollback
of a healthy v2. With 300 requests it rests on the ~3 slowest.

**Why 2 consecutive breaches?**
One noisy check should not roll back. A real failure keeps breaching; noise rarely does twice in a row.

## The data and models

**Why split by patient?**
A patient can have several hospital stays. If the same patient were in train and test, the model
could memorise them and the test score would be too optimistic.

**Why remove deceased / hospice patients?**
They cannot be readmitted: keeping them would teach the model nonsense.

**Why is AUC only ~0.66-0.68?**
Readmission is hard to predict from administrative data; published results on this dataset are in
the same range. For this project the model quality matters less than the rollout.

**What is the silent schema bug?**
An upstream change renamed `number_inpatient` (number of past inpatient visits, the strongest
predictor) to `num_inpatient`. The service fills the missing column with the median (0), so it
still answers HTTP 200 but under-estimates risk for frequent patients. Test AUC falls from 0.663 to
0.623 and the mean predicted risk from 11.2% to 8.9%.

## The engineering

**Why one image for all services?**
Same code, same library versions everywhere; each service just runs a different command. Both
variants are literally the same container with different environment variables.

**Why 8 worker processes per variant?**
Python runs one prediction at a time per process. At 100% traffic (150 req/s) v2 needs ~1.5 CPU
cores; with 4 workers its p99 rose under load and a healthy v2 was rolled back at 100%. That was a
real capacity finding.

**Why a custom encoder instead of sklearn's OneHotEncoder?**
On a single row, ColumnTransformer + OneHotEncoder cost ~30 ms of Python overhead. Our encoder does
dictionary lookups: v1 went from 54 ms to 1 ms per prediction.

**How do metrics work with 8 processes?**
`prometheus_client` multiprocess mode: each worker writes its counters to a shared folder and the
`/metrics` endpoint adds them up when Prometheus scrapes.

**What would you do next in a real hospital?**
An A/B test (or a shadow deployment) to measure the effect on readmissions; alerting to a human on
rollback; promotion of `@challenger` to `@champion` only after review; and monitoring of the input
features themselves (the schema bug would also show as a feature drift on `number_inpatient`).
