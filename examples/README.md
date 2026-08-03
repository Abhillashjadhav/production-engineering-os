# Examples

- `pmos-contracts/` — synthetic canonical PMOS bundle/manifest examples and
  planted invalid V2 compiler inputs. See the
  [versioned authoring and migration guide](../docs/pmos-contract-authoring.md)
  before reusing their structure; sample values and approvals are non-production.

- `taskflow_mvp_spec.yaml` — the reference PM OS specification (golden path). Run it:

  ```bash
  pmpe validate examples/taskflow_mvp_spec.yaml   # structure + semantic validation only
  pmpe run examples/taskflow_mvp_spec.yaml        # full lifecycle → runs/<run_id>/
  ```

A full run produces `runs/<run_id>/` containing `state.json` (workflow state),
`events.jsonl` (decision/telemetry log), `artifacts/` (plan, architecture, ADRs,
review, merge decision, deployment record, traceability report, final build report)
and `workspace/` — the generated TaskFlow product as its own git repository with
tests committed before implementation.

Specs that exercise the failure paths (contradictions, activity-only NSM, malformed
input, forced escalations) live in `tests/fixtures/` — they are part of the test
suite's evidence, not user-facing examples.
