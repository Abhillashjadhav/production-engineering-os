# Customer-support workflow MVP

This vertical proves the platform boundary: customer-support rules are dynamic,
while the decision contract, workflow compiler, execution kernel, evidence chain,
and reports are fixed reusable components.

Generate deterministic synthetic inputs:

```bash
pmpe support-demo generate --seed 110 --output /tmp/pmpe-support
```

Compile, execute, and report the first case without exposing the hidden oracle:

```bash
pmpe support-demo run \
  --cases /tmp/pmpe-support/visible/cases.json \
  --output /tmp/pmpe-support/result
```

Pass `--case-id` to choose another generated case. The result contains
`workflow-report.json` and `workflow-report.md`, with input, decision-contract,
plan, execution, and report digests.

Evaluation is an explicit separate mode allowed to read hidden truth:

```bash
pmpe support-demo evaluate \
  --cases /tmp/pmpe-support/visible/cases.json \
  --oracles /tmp/pmpe-support/eval-only/oracles.json \
  --output /tmp/pmpe-support/evaluation.json
```

No command calls a model, help-desk system, or external action API. Human-bound
and contradictory cases stop at `NEEDS_HUMAN_DECISION`.
