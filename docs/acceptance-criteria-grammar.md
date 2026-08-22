# Acceptance-criteria grammar for the bare-bones core

Issue: #140

The compiler accepts a criterion only when it can produce an executable assertion
without guessing product truth, or when the contract binds a human-authored test.

## Criterion forms

Every acceptance criterion has a stable ID and at least one requirement reference.
It selects exactly one form.

### Structured Given/When/Then

```json
{
  "id": "AC-001",
  "requirement_refs": ["FR-001"],
  "given": [{"path": "service.running", "operator": "eq", "value": true}],
  "when": {"action": "health", "arguments": {}},
  "then": [{"path": "result.status", "operator": "eq", "value": "ok"}]
}
```

`given` and `then` contain data assertions. `when.action` names a template action
registered by the one composable product template; it is not arbitrary source code.

### Measurable outcome

```json
{
  "id": "AC-002",
  "requirement_refs": ["NFR-001"],
  "measure": "request.latency_ms.p95",
  "operator": "lte",
  "value": 250,
  "sample": {"minimum": 100}
}
```

### Human-authored executable test

```json
{
  "id": "AC-003",
  "requirement_refs": ["SEC-001"],
  "human_test": {
    "path": "tests/security/test_config_parser.py",
    "node_id": "test_operator_input_is_never_executed",
    "command": ["pytest", "-q", "tests/security/test_config_parser.py::test_operator_input_is_never_executed"]
  }
}
```

The path is repository-relative, must remain under `tests/`, and the command must
target that exact path and node. The compiler records the file digest. Missing or
changed files invalidate the plan.

### Explicitly satisfied by the template

```json
{
  "id": "AC-004",
  "requirement_refs": ["FR-HEALTH"],
  "satisfied_by_template": {
    "template_version": "barebones-1",
    "test_id": "template::health"
  }
}
```

This is the only allowed baseline-PASS exception. The referenced test must exist in
the pinned template and its digest is recorded before scaffolding.

## Operators

The v1 operator set is deliberately closed:

`eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `contains`, `not_contains`, `matches`,
`is_true`, `is_false`, `is_null`, `not_null`.

No criterion contains Python, shell, JavaScript, SQL, a prompt, or an unregistered
callable. Extending the operator or action registry requires a failing real contract.

## Compile-time gates

Before entering `BUILDING`, the compiler proves:

1. every requirement ID has at least one implementation task;
2. every requirement ID has at least one criterion;
3. every criterion references an existing requirement;
4. every criterion selects exactly one accepted form;
5. every structured action and operator is registered;
6. every human test exists and is digest-bound;
7. every template-satisfied test exists in the pinned template;
8. no compiler decision requires an LLM interpretation.

Any failure returns `CONTRACT_INVALID` with the exact requirement or criterion ID.

## Baseline gate

The untouched template runs every compiled or human-authored test.

- An implementation-required criterion must fail as an assertion.
- Import, collection, syntax, fixture, timeout, and environment errors are invalid RED.
- A passing test is invalid unless it is explicitly and correctly
  `satisfied_by_template`.
- The compiler stores the baseline result and test digest in the evidence chain.

## Hand-validation result

The repository canonical PMOS fixture contains one requirement (`FR-001`) and one
criterion (`AC-001`). Its prose is recognizably Given/When/Then, but the current
contract does not identify a registered action or typed output paths. It therefore
does **not** satisfy this grammar without conversion. This is the intended fail-closed
result: the existing free-text field is not sufficient to generate executable evidence
without guessing.

The v2 demo's safe-config criterion also requires the human-test escape hatch because
"no part of the input is ever executed" cannot be compiled into a finite property
assertion from prose alone.

These findings confirm that PMOS must emit the structured form or bind a human test
before E1 can honestly start.
