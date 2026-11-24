# Live demo script (about 12 minutes)

Plain-language script: what to **do** (▶) and what to **say** (💬).

## Before the presentation (at home, 15 minutes before)

▶ Start Docker Desktop, then in a PowerShell window inside the project folder:

```powershell
docker compose up -d
```

▶ Open three browser tabs:
1. Grafana: <http://localhost:3000> (dashboard "P1 - Canary rollout")
2. MLflow: <http://localhost:5000> → Models → `readmission`
3. Controller status: <http://localhost:8090/rollout/status>

▶ Check everything is up: <http://localhost:8000/health> should show both variants with a model version.
Wait 1-2 minutes so Grafana shows traffic (blue line at ~150 req/s).

If anything is broken: `docker compose down` then `docker compose up -d` and wait 2 minutes.

---

## 1. The story (1 min)

💬 "A hospital uses model **v1**, a logistic regression, to predict which diabetic patients will
come back within 30 days. Our team trained **v2**, a gradient boosting model. Offline it is better:
AUC 0.676 against 0.663 on validation. But it is heavier, about 10 times more CPU per prediction.
Swapping it in at once is risky: if it is broken, every patient is affected. So we do a **canary**:
we give v2 to 1% of patients, then 5, 25 and 100%, and check at every step that nothing is wrong."

## 2. The architecture (1.5 min)

▶ Show the diagram in the README (or the report).

💬 "Everything runs in Docker Compose on this laptop. The **simulator** replays real test patients
as users. The **router** sends each patient to A or B, sticky: the same patient always goes to the
same model, by a hash of the patient id. Both variants run the **same image** and load their model
from the **MLflow registry**: A loads the alias `@champion`, B loads `@challenger`. Every service
exposes metrics with a `variant` label; **Prometheus** stores them and **Grafana** shows A and B side
by side. The **controller** is a Python loop that changes the traffic weight and reads Prometheus."

▶ MLflow tab: show version 1 `@champion`, version 2 `@challenger`, the AUC metrics, and the tags
`offline_psi_vs_champion` and `offline_latency_overhead_ms`.

## 3. A healthy rollout (start it now, it runs in the background ~7 min)

▶ In PowerShell:

```powershell
.\scripts\scenario.ps1 healthy
```

💬 "At each step the controller checks four guardrails every 5 seconds:
- **error rate**: is v2 failing more often than v1? A one-sided two-proportion z-test.
- **p99 latency**: are the slowest 1% of v2's requests too slow compared with v1?
- **PSI of the scores**: does v2 predict a very different distribution of risk than v1?
- **invalid scores**: any NaN or out-of-range probability?
If one of them fails twice in a row, the controller puts the weight back to 0. That is the rollback."

▶ Grafana: point at "Traffic on v2" (1%), "Rollout state" (ROLLING OUT), the orange v2 lines.

💬 "Notice v2's latency is higher than v1's, about 30 ms against 6 ms. That is expected: v2 is the
heavier model. The latency guardrail allows the extra cost we measured offline, and catches anything
beyond it."

(While it runs, go to section 4 and come back at the end to show "PASSED" and 100%.)

## 4. Breaking v2 on purpose (5 min)

💬 "Now the important part: a canary is only useful if it catches problems. We inject three failures
in v2 with environment flags."

▶ When the healthy rollout is finished (or press Ctrl+C and run
`Invoke-RestMethod -Method Post http://localhost:8090/rollout/abort`), run:

```powershell
.\scripts\scenario.ps1 errors
```

💬 "v2 now fails 5% of requests. Watch the error-rate panel." It is rolled back after **about 60
requests on v2, in under a minute**, at 1% traffic. "Only 1% of patients were exposed, for less than
a minute."

```powershell
.\scripts\scenario.ps1 latency
```

💬 "v2 now takes 50 ms longer. p99 latency goes to ~90 ms against a limit of ~52 ms."
Rolled back at 1% after ~300 requests (~3.5 min). Use this time to answer questions.

For the **silent schema bug** (6 min), show the screenshot `report/figures/grafana_schema.png` and
the timeline `report/figures/rollout_schema.png` instead of running it live:

💬 "This is the dangerous one. Upstream, a column was renamed: `number_inpatient` became
`num_inpatient`. The service does not crash: the missing column is filled with a default value, so
every request still returns HTTP 200. Errors and latency look perfect. But that column is the
strongest predictor, so v2's risk scores drop: the mean risk falls from 11% to 9%, and patients who
were often hospitalised now look low-risk. Only the **PSI** of the score distribution caught it,
at 5% traffic: 0.19 against a threshold of 0.15."

## 5. The three report questions (2 min)

💬 Q1: "At 1% traffic, a 5% error rate is detected after about **47 requests** by the power formula
and **~65 requests** with our real rule, which matches the live run: under a minute."

💬 Q2: "Repeated checks create false alarms. With naive settings, a **healthy** v2 was rolled back
in almost every simulated rollout, and it happened to us 5 times while tuning. Each fix is in the
report: minimum samples, an exact test for rare errors, PSI only from 5% traffic, alpha corrected
for ~85 checks, and two breaches in a row. With the shipped rule: essentially no false rollbacks."

💬 Q3: "The canary cannot tell us whether v2 is **better**. It only proves v2 is **safe**: no errors,
acceptable latency, sane scores. 'Better' means fewer readmissions, which we only learn 30 days later,
and the difference is tiny, so it would need an A/B test with tens of thousands of patients."

## 6. Closing (30 s)

💬 "To summarise: v2 went to 100% safely when healthy, and each of the three failures was caught by
the right guardrail at 1 or 5% traffic. The registry aliases never moved during a rollback: v1 stays
the champion until a human promotes v2."
