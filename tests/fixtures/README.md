# Test fixtures

Two kinds of failure-path specs feed the suite:

1. **Mutations of the golden spec** — defined once in `tests/conftest.py`
   (`mutate_contradictory`, `mutate_activity_nsm`, `mutate_production_target`,
   `mutate_vague_ac`, `mutate_unknown_requirement_ac`, `mutate_missing_entity`) and
   applied via the `make_spec_file` fixture. Keeping them as code diffs against
   `examples/taskflow_mvp_spec.yaml` means each fixture shows exactly the planted
   failure and nothing else.

2. **Standalone malformed inputs** (cannot be expressed as a mutation of a valid spec):
   - `malformed_spec.yaml` — missing required fields, wrong types, bad enums
   - `not_a_mapping.yaml` — parses but is not an object
   - `broken_syntax.yaml` — does not parse at all
   - `minimal_valid_spec.json` — smallest valid spec, exercises the JSON input path
