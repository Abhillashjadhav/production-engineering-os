# Production eval monitoring V2

This observability layer sits beside the existing baseline/candidate comparison.
It does not change production, evals, or approved cases automatically.

## What the dashboard answers

For every incident, an operator can see:

1. the exact failed case and production segment;
2. the current result, expected result, and difference;
3. the first failed check in the declared dependency path;
4. later failures that are probably symptoms;
5. what changed since the last approved good run;
6. the evidence supporting a possible cause;
7. the component, owner, parameter, and action to inspect first; and
8. whether an eval or approved-case review is justified.

## Plain-language labels

- **Current result**: what happened now.
- **Expected result**: the approved comparison value or behaviour.
- **Difference**: how far the current result moved from expected.
- **Degraded check**: a check that still passes but moved beyond its allowed
  tolerance; it is not labelled as a failed check.
- **Localized cases**: unique cases with a localized starting failure or a
  degraded check. This is not presented as the total number of failed cases.
- **Comparison run**: the approved good run supplying the expectation.
- **Likely starting failure**: the earliest observed failure in the declared
  dependency path. This is localization, not proof of cause.
- **Downstream symptom**: a later failure that an upstream failure may explain.
- **Unconfirmed cause**: the available evidence cannot safely select one cause.

## Contract

A product adapter emits a strict `RunEnvelope` V0.2. Each observation contains:

- an opaque case ID, label, use case, segment, and optional input fingerprint;
- separate evaluation **layer** and **concern** fields;
- current and expected numeric values plus redacted summaries;
- component, stage, parameter, owner, and logical fix location;
- dependency edges and tamper-evident evidence references;
- optional causal signals with an explicit evidence level; and
- a bounded remediation hint owned by the product adapter.

When a numeric threshold is present, `PASS` and `FAIL` must agree with that
threshold and with whether higher or lower values are better; contradictory
envelopes are rejected. Dashboard case counts use the full product, environment,
use-case, case, segment, and input-fingerprint identity rather than `case_id`
alone. Each product declares a freshness SLA (26 hours by default); once its
latest observation exceeds that window, product and coverage health are blocked
as **Data stale** and old incidents are not presented as current. Observations
more than five minutes in the future are rejected.

Layers describe where evaluation happens: input, system, retrieval/tool,
tool trajectory, output, and outcome. Concerns describe what is protected:
invariants, capability, quality, privacy, safety, toxicity, and policy.

The run also records a change manifest for use case, deployment, immutable model
snapshot, prompt, configuration, toolset, evaluator, rubric, approved dataset,
and production cohort versions. Integrity digests are stored separately from
these human-readable versions.

Raw private inputs and outputs must not enter the monitoring contract. Store
redacted summaries, opaque identifiers, hashes, and approved evidence URIs.

The dashboard shows an expected value, difference, and comparison changes only
when the referenced earlier run is healthy and contains the same passing case
and check with exactly that expected value. Missing or mismatched comparison
evidence is labelled **Comparison unavailable** instead of being inferred from
the current run's self-reported expectation.

All submitted numbers must be finite. If arithmetic on two valid extreme values
would overflow, the difference is shown as unavailable instead of breaking
ingestion or poisoning stored history.

## Diagnosis rules

Dependency analysis can identify a **likely starting failure**. It cannot prove
why that failure occurred. Cause confidence is bounded by evidence:

- dependency or timing correlation: `CANDIDATE`;
- controlled replay with relevant variables held fixed: `SUPPORTED`;
- human adjudication: `CONFIRMED`;
- missing, contradictory, or equally strong competing evidence: `UNCONFIRMED`.

Blocked or unevaluated evidence remains unresolved through the full dependency
path, including passing intermediate checks, so a later failure cannot be shown
as the starting point. Passing checks that regress beyond tolerance receive a
separate `DEGRADED_CHECK` diagnosis and exact-case incident only when the exact
earlier healthy comparison verifies the expected value. A comparison with a
possible but unverified degradation cannot certify a later baseline; missing
comparison ancestry therefore fails closed as unavailable.

A controlled replay must classify every change dimension as either intentionally
varied or held constant, with no overlap or omission. Its asserted cause must
match the varied dimensions; otherwise the contract rejects it before diagnosis.

The supported cause categories are product regression, model regression,
prompt/config/tool change, use-case drift, eval deterioration, approved-dataset
gap, and unconfirmed.

Eval review is recommended only after evidence indicates evaluator instability
or disagreement with correct product behaviour. Approved-case review is
recommended only after an adjudicated production case exposes missing or stale
coverage. A falling score alone changes neither asset.

## API and storage

- `POST /api/monitoring/evaluate` diagnoses an envelope without storing it,
  resolving its exact stored comparison when available.
- `POST /api/monitoring/runs` appends an envelope to immutable local history.
  It requires `Authorization: Bearer <token>` matching the server-side
  `PM_EVALS_INGEST_TOKEN`; writes fail closed when no credential is configured,
  and the response diagnosis uses the exact stored comparison.
- `GET /api/monitoring/overview` returns product health, exact-case incidents,
  trends, two-axis coverage, and attribution calibration.

Canonical history is append-only JSONL with a rebuildable SQLite index. The
same run is idempotent only when its canonical bytes match; conflicting evidence
under the same product/environment/run identity is rejected. A filesystem lock
serializes the duplicate check, log append, and index commit across application
workers. Startup truncates only an unterminated final record left by an
interrupted append; corruption in any completed record still fails closed. If
indexing an append fails, the new log record is durably rolled back. If rollback
also fails, the next operation reconciles the log and index before proceeding.
Overview reads are bounded to the most recent 30 runs per product/environment
plus the latest run's referenced comparison, while the canonical history
remains complete. When producer observation times tie, the server's append
order determines recency; opaque run IDs never decide which result is current.

## First run

```bash
python backend/scripts/run_monitoring_demo.py
```

The empty-store dashboard uses a clearly labelled planted scenario. One exact
Dream Job case fails after a connector change. A controlled replay supports the
connector as the cause while five later failures remain downstream symptoms.
LinkedIn Research OS stays healthy.

This proves the data flow, localization, and UI behaviour. It does not prove the
below-2% production false-attribution guardrail; that requires adjudicated live
incidents.

## Before live data

1. Add a Dream Job adapter that maps existing run artifacts into V0.2 without
   private content.
2. Approve an opt-in, redacted LinkedIn Research OS export with the same contract.
3. Add controlled-replay evidence only when relevant variables are held fixed.
4. Keep planted-fault and adjudicated-production calibration visibly separate.
