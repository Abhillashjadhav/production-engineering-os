# Examples

- `pmos-contracts/` — synthetic canonical PMOS bundle/manifest examples and
  planted invalid V2 compiler inputs. See the
  [versioned authoring and migration guide](../docs/pmos-contract-authoring.md)
  before reusing their structure; sample values and approvals are non-production.

- `taskflow_mvp_spec.yaml` — the reference legacy PM OS specification. Validate it:

  ```bash
  pmpe validate examples/taskflow_mvp_spec.yaml   # structure + semantic validation only
  ```

The old V1 end-to-end behavior is available only through the explicit
`tests.legacy_v1` fixture namespace. It is not a shipped execution path.

Specs that exercise the failure paths (contradictions, activity-only NSM, malformed
input, forced escalations) live in `tests/fixtures/` — they are part of the test
suite's evidence, not user-facing examples.
