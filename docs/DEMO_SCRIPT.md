# Live demo script (about 15 minutes)

Plain-language script: what to **do** (▶) and what to **say** (💬).
Run every command in a PowerShell window **opened in the project folder**.

> Use `.\scripts\scenario.cmd`, not `scenario.ps1` directly: on a default Windows setup PowerShell
> refuses to run `.ps1` files ("running scripts is disabled on this system"); the `.cmd` launcher
> works whatever the setting.

## The day before (15 minutes, at home)

▶ Start Docker Desktop, then:

```powershell
docker compose up -d
```

▶ With the charger plugged in, run one full rehearsal so you know it works on this laptop (~8 minutes):

```powershell
.\scripts\scenario.cmd healthy
```

It must end with `RESULT: PASSED`. If not, see "If something goes wrong" at the end.

## Just before the presentation

▶ **Plug in the charger** and set Windows to **Balanced** or **Best performance** (Settings →
System → Power). In Power saver the CPU is throttled and v2's p99 at 100% traffic gets close to
its limit (46 ms against 52 ms in our test), so a healthy rollout could be rolled back.

▶ Start Docker Desktop and run `docker compose up -d` (it is fast when nothing changed).

▶ Open four browser tabs:
1. Grafana: <http://localhost:3000> (dashboard "P1 - Canary rollout")
2. MLflow: <http://localhost:5000> → Models → `readmission`
3. Router health: <http://localhost:8000/health>: must show both variants with a model version
4. Controller status: <http://localhost:8090/rollout/status>

▶ Wait until Grafana shows traffic (blue line at ~150 req/s).

---

## 1. The story (1 min)

💬 "A hospital uses model **v1**, a logistic regression, to predict which diabetic patients will
come back within 30 days. Our team trained **v2**, a gradient boosting model. Offline it is better:
AUC 0.676 against 0.663 on validation. But it is heavier, about 10 times more CPU per prediction.
Swapping it in at once is risky: if it is broken, every patient is affected. So we do a **canary**:
we give v2 to 1% of patients, then 5, 25 and 100%, and check at every step that nothing is wrong."

## 2. The architecture (1.5 min)

▶ Show the architecture slide (or the diagram in the README).

💬 "Everything runs in Docker Compose on this laptop. The **simulator** replays real test patients
as users. The **router** sends each patient to A or B, sticky: the same patient always goes to the
same model, by a hash of the patient id. Both variants run the **same image** and load their model
from the **MLflow registry**: A loads the alias `@champion`, B loads `@challenger`. Every
application metric has a `variant` label; **Prometheus** stores them and **Grafana** shows A and B
side by side. The **controller** is a Python loop that changes the traffic weight and reads
Prometheus."

▶ MLflow tab: show version 1 `@champion`, version 2 `@challenger`, the `val_auc` tags, and on
version 2 the tags `offline_psi_vs_champion` and `offline_latency_overhead_ms`.

## 3. Start a healthy rollout (it runs ~7.5 min on its own)

▶ In PowerShell:

```powershell
.\scripts\scenario.cmd healthy
```

💬 "At each step the controller checks four guardrails every 5 seconds:
- **error rate**: is v2 failing more often than v1? A one-sided two-proportion z-test.
- **p99 latency**: are the slowest 1% of v2's requests too slow?
- **PSI of the scores**: does v2 predict a very different distribution of risk than v1?
- **invalid scores**: any NaN or out-of-range probability?
If one of them fails twice in a row, the controller puts the weight back to 0. That is the rollback."

▶ Grafana: point at "Traffic on v2" (1%), "Rollout state" (ROLLING OUT), the orange v2 lines.

💬 "Notice v2's latency is higher than v1's, about 30 ms against 6 ms. That is expected: v2 is the
heavier model. The latency guardrail allows the extra cost we measured offline, and catches anything
beyond it."

## 4. While it runs: the three report questions (3-4 min, on the slides)

💬 Q1: "At 1% traffic, a 5% error rate is detected after about **47 requests** by the power formula
and **~65 requests** with our real rule, which matches our live run: 65 requests, 46 seconds."

💬 Q2: "Repeated checks create false alarms. With the literal rules, a **healthy** v2 was rolled
back in every simulated rollout, and it happened to us 5 times in our first 6 healthy runs. Each fix
is in the report: an allowance for v2's known latency, minimum samples, an exact test for rare
errors, PSI only from 5% traffic, alpha corrected for ~85 checks, and two breaches in a row. With
the shipped rule: about 1% false rollbacks."

💬 Q3: "The canary cannot tell us whether v2 is **better**. It only proves v2 is **safe**: no extra
errors, acceptable latency, sane scores. 'Better' means fewer readmissions, which we only learn
30 days later, and the difference is tiny: even half a point less readmission would need about
62,000 patients per group in an A/B test."

▶ Back to Grafana: the rollout ends with **PASSED** and v2 at **100%**.

## 5. Breaking v2 on purpose (5 min)

💬 "Now the important part: a canary is only useful if it catches problems. We inject failures
in v2 with environment flags."

```powershell
.\scripts\scenario.cmd errors
```

💬 "v2 now fails 5% of requests. Watch the error-rate panel." It is rolled back after **about 65
requests on v2, in under a minute**, at 1% traffic. "Only 1% of patients were exposed, for less
than a minute."

```powershell
.\scripts\scenario.cmd latency
```

💬 "v2 now takes 50 ms longer. Its p99 goes to ~90 ms against a limit of ~52 ms." Rolled back at
1% after ~300 requests (~3.5 min). Use this time to take questions.

For the **silent schema bug** (6 min), show the slide (Grafana screenshot) instead of running it:

💬 "This is the dangerous one. Upstream, a column was renamed: `number_inpatient` became
`num_inpatient`. The service does not crash: the missing column is filled with a default value, so
every request still returns HTTP 200, and the error and latency guardrails stay quiet. But that
column is the strongest predictor, so v2's risk scores drop: offline, the mean risk falls from 11%
to 9%, and patients who were often hospitalised now look low-risk. Only the **PSI** of the score
distribution caught it, at 5% traffic: 0.19 against a threshold of 0.15."

## 6. Closing (30 s)

💬 "To summarise: v2 went to 100% safely when healthy, and each of the three failures was caught by
the right guardrail at 1 or 5% traffic. The registry aliases never moved during a rollback: v1 stays
the champion until a human promotes v2."

---

## If something goes wrong

* A scenario says a rollout is still running: it aborts it by itself; or run
  `Invoke-RestMethod -Method Post http://localhost:8090/rollout/abort`.
* `/health` fails or Grafana is empty: `docker compose up -d`, wait 1-2 minutes.
* Still broken: `docker compose down` then `docker compose up -d` (keeps the models and metrics).
* Never run `docker compose down -v` before the presentation: it deletes the registry and forces
  a retraining.
