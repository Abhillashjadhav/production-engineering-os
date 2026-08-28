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

`pmpe barebones compare` verifies two complete ledgers, requires an externally supplied
`--expected-approver`, recompiles each recorded contract from the trusted
`--compiler-root`, and requires sealed `RELEASE_READY` candidates. It then compares the
final Coder responses only when their contract, plan, purpose, and request digests match.
It hashes the behavior-bearing file map separately from adapter-declared provider, model,
prompt, and CLI versions. Neither approval authority nor compiled-plan truth is accepted
solely because the ledger says so.

- Identical output is not behavior drift, even if a prompt version changed.
- Changed output with a changed provider/model/prompt/CLI version is detected and
  attributed to the changed configuration fields.
- Changed output without any recorded configuration change is
  `UNATTRIBUTED_BEHAVIOR_DRIFT`.
- Different request digests are not comparable and fail closed.

Provider metadata is adapter-declared provenance, not an independent attestation. A
promotion claim should bind it to the provider command/configuration and the complete
run evidence.

The comparison also reports plan repeatability and candidate-digest variation. Different
contracts or plans return `NOT_COMPARABLE`; their separate runs still provide transfer
evidence, but are not mislabeled as behavior drift.

## Real evidence matrix

On an authenticated Linux host, run:

```bash
python examples/barebones/run_real_behavior_drift_eval.py
```

The script fails closed unless Codex reports ChatGPT authentication, Bubblewrap isolation
works, `/proc` is mounted, and tracked source is clean. It removes paid-API credential
variables from every child environment and executes seven runs: three E1 repeats, one
planted prompt-version change, and three repeats of a digest-approved synthetic
multi-criterion readiness contract. It packages every candidate, ledger, log, comparison,
summary, and checksum into one `.tgz`. A failed run is retained in the same report rather
than discarded. The planted run passes only when its sealed `product.py` contains the exact
requested top-level profile constant; a prompt-version change plus unrelated output drift is
rejected. The launcher also loads PMPE from the source checkout instead of a stale installed
copy. This second fixture tests contract/criterion transfer, not external product authorship
or transfer to another product type.

The complete seven-run archive produced on 2026-08-27, together with its outer checksum
and independent replay results, is
[published here](evidence/real-behavior-drift-20260827/README.md).

## Why E5 allows candidate variation

Real model providers are nondeterministic. Requiring byte-identical candidates would
make E5 either impossible or encourage weakening the check after the first real run.
The stable contract is instead:

1. the same admitted contract and template compile to the same build-plan digest;
2. every run has a valid tamper-evident chain;
3. each distinct candidate is visible through its own manifest digest;
4. deterministic verification decides whether that candidate reaches
   `RELEASE_READY`.
