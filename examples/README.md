# Examples

- `taskflow_mvp_spec.yaml` — the reference PM OS specification (golden path). Run it:

  ```bash
  pmpe validate examples/taskflow_mvp_spec.yaml   # structural validation
  ```

Semantic validation and the full pipeline (`pmpe run`) land in later PRs of the
atomic series; this example is their shared golden input.

Specs that exercise the failure paths (contradictions, activity-only NSM, malformed
input, forced escalations) live in `tests/fixtures/` — they are part of the test
suite's evidence, not user-facing examples.
