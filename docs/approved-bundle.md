# Running an approved bundle (`pmpe barebones run-bundle`)

This is the supported way to run a contract whose release gates carry typed process bindings: negative controls, digest boundaries, generation provenance and execution disclosure. `pmpe barebones run` supplies none of their inputs.

```bash
pmpe barebones run-bundle BUNDLE_DIR \
  --freeze-digest sha256:<digest of BUNDLE_DIR/approval-freeze.json, retained elsewhere> \
  --root repository=/path/to/source/root \
  --run-id <id> --workspace <new dir> --repository-root <evidence root> \
  --expected-approver "<name in contract approved_by>" \
  --provider-command "<local ModelProvider command>"
```

The command relaunches itself in a source-only interpreter (`-B` plus a fresh, empty private cache prefix), as required by the owner decision of 2026-09-25 (#217). It then verifies the whole bundle and calls `run_to_release_ready` once. Every refusal happens before any provider call or workspace creation.

## `bundle.json`

| Field | Meaning |
|---|---|
| `schema_version` | `"1"` |
| `approval` | Approval-packet key → bundle-relative file. Keys must equal the freeze's `artifacts`; each file must match its frozen digest. `contract`, `receipt` and `source_manifest` are required. The engine additionally requires `draft`, `plan`, `publisher_input` and `mutant/<id>`. |
| `approval_freeze` | Outer freeze file. Its raw sha256 must equal `--freeze-digest`. |
| `bindings` | Template: `version`, `files`, `actions`, `context`, optional `measures`. Targets are `module:function` in an explicit template file; measures (evaluators) must be frozen `tests/` files. |
| `execution_profile` | The bound execution profile. Its optional `build_budget` sets the engine's `BudgetCaps`. |
| `source_paths` | Name → `{"root": NAME, "path": relative}`. `bundle` is the bundle directory; other roots come from `--root`. |
| `negative_controls` | Mutant id → bundle-relative directory holding the exact snapshot. |
| `generation` | `mode` and `provider_attestation` (`kind`, `statement`), passed through unchanged. The fresh-generation gate (G4) keeps its current behaviour until owner decision D2. |
| `real_sandbox_leg` | `status` and `reason` disclosure. |

Unknown fields, symlinks, absolute or `..` paths, missing files and digest mismatches are refused.

## Limits

- The expected freeze digest is an operator anchor, not a signature.
- The candidate sandbox is the engine default (bubblewrap). The example host fallback in `examples/barebones/contract-file.py` is not part of this path.
- The command adds no product policy.
