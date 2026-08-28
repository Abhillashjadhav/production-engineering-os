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

Layers describe where evaluation happens: input, system, retrieval/tool,
tool trajectory, output, and outcome. Concerns describe what is protected:
invariants, capability, quality, privacy, safety, toxicity, and policy.

The run also records a change manifest for use case, deployment, immutable model
snapshot, prompt, configuration, toolset, evaluator, rubric, approved dataset,
and production cohort versions. Integrity digests are stored separately from
these human-readable versions.

Raw private inputs and outputs must not enter the monitoring contract. Store
redacted summaries, opaque identifiers, hashes, and approved evidence URIs.

## Diagnosis rules

Dependency analysis can identify a **likely starting failure**. It cannot prove
why that failure occurred. Cause confidence is bounded by evidence:

- dependency or timing correlation: `CANDIDATE`;
- controlled replay with relevant variables held fixed: `SUPPORTED`;
- human adjudication: `CONFIRMED`;
- missing, contradictory, or equally strong competing evidence: `UNCONFIRMED`.

The supported cause categories are product regression, model regression,
prompt/config/tool change, use-case drift, eval deterioration, approved-dataset
gap, and unconfirmed.

Eval review is recommended only after evidence indicates evaluator instability
or disagreement with correct product behaviour. Approved-case review is
recommended only after an adjudicated production case exposes missing or stale
coverage. A falling score alone changes neither asset.

## API and storage

- `POST /api/monitoring/evaluate` diagnoses an envelope without storing it.
- `POST /api/monitoring/runs` appends an envelope to immutable local history.
- `GET /api/monitoring/overview` returns product health, exact-case incidents,
  trends, two-axis coverage, and attribution calibration.

Canonical history is append-only JSONL with a rebuildable SQLite index. The
same run is idempotent only when its canonical bytes match; conflicting evidence
under the same product/environment/run identity is rejected.

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
