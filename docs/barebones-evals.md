# Bare-bones eval semantics

Issue: #146

The frozen core keeps plumbing integrity, deterministic planning, generated behavior,
and behavior drift as separate claims.

| Eval | What it proves | What it does not prove |
|---|---|---|
| E1 | One admitted contract can reach `RELEASE_READY` through the engine | A scripted provider is not real-model product evidence |
| E2 | An unsatisfied criterion halts with the exact subject | Breadth across product types |
| E3 | A stale or mismatched response digest is rejected as `MODEL_RESPONSE_UNBOUND` | Model behavior drift |
| E4 | Contradictory acceptance truth is rejected before build | Runtime repair quality |
| E5 | Repeated compilation preserves the plan digest and each run produces a valid evidence chain | Byte-identical model output or candidate files |

## Behavior drift

`pmpe.evals.barebones_drift` compares two recorded responses only when they have the
same purpose and request digest. It hashes the behavior-bearing output (`files` for
Coder responses or `summary` for advisory responses) separately from adapter-declared
provider, model, and prompt versions.

- Identical output is not behavior drift, even if a prompt version changed.
- Changed output with a changed provider/model/prompt version is detected and
  attributed to the changed configuration fields.
- Changed output without any recorded configuration change is
  `UNATTRIBUTED_BEHAVIOR_DRIFT`.
- Different request digests are not comparable and fail closed.

Provider metadata is adapter-declared provenance, not an independent attestation. A
promotion claim should bind it to the provider command/configuration and the complete
run evidence.

## Why E5 allows candidate variation

Real model providers are nondeterministic. Requiring byte-identical candidates would
make E5 either impossible or encourage weakening the check after the first real run.
The stable contract is instead:

1. the same admitted contract and template compile to the same build-plan digest;
2. every run has a valid tamper-evident chain;
3. each distinct candidate is visible through its own manifest digest;
4. deterministic verification decides whether that candidate reaches
   `RELEASE_READY`.
