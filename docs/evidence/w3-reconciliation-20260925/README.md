# W3 — proof reconciliation on the repaired source (2026-09-25)

Source under test: the W2 head `80cd230ca37f3d75e3aa2d1dd0733d8e464b45e0` (#227). It contains:
- the R4 process line `ccabeecc`
- W1a/W1b (#222, #223)
- the checker and contract-file line (#221, merged in #226)
- W2 source-only admission (#227)
- the fixes from today's review: #225, #229, per-gate negative-control scoping, the protected-inventory binding, and checker round 3 (interpreter bound to the launch record)

Earlier versions of this evidence ran on `cecf9e9`, `1b680ff` and `933fdc7`. It was refreshed on `80cd230`. That head adds the later Codex-review repairs to source-only admission (startup-record prefix precedence, code-bound implementation identity), the CI prefix ordering, checker rounds 14–18, and the ported #233 and #234 fixes. Criteria, gate statuses and reasons, record counts and the scanner result are unchanged; only the source-bound digests differ.

This PR's head also carries #227 `f6df6a2`, `feb49dc`, `9692a9e` and `8f61afa`, which add checker rounds 19 (pinned candidate trees and the measure's value domain), 20 (the exact recorded runtime string), 21 (exact JSONL serialization) and 22 (exact adapter JSON serialization). They change only `docs/evidence/r3-repair-20260924/check_replay_complete.py`, its tests, its RED/GREEN logs and `BAR.md`, and no file under `src/`, `scripts/` or `tests/`, so the replay and scanner evidence from `80cd230` stands. The checker run in `replay-checker.txt` was refreshed on this head.

Historical inputs are unchanged: the PM-agent-OS packet at `33a35962` (`reviews/task-tracker-v1`, 218-artifact freeze) and the historical PEOS engine at `c1ab2def189f`. This unit adds evidence only; no source or frozen artifact changes.

## Four separate verdicts

| Dimension | Verdict | Evidence in this directory |
|---|---|---|
| Source correctness (settled repairs) | **REPAIRED, pending CI and review on the stack** | The architecture scanner, unchanged, reports `unapproved_edges: []` (`architecture-scanner.json`). The release-gate suites fail 108 of 131 on `main` and pass 131 on this head (`release-gates-main-vs-head.txt`). Malformed-binding and setup-crash RED/GREEN evidence is in #222/#223. |
| Replay proof (historical task store) | **REPRODUCED, bounded** | **14/14** historical criteria PASS. 56 process records, 117 digest boundaries, 0 fresh model calls. G1/G2/G5 PASS; G3 NOT_EVALUATED (`APPROVAL_PACKET_NOT_BOUND`); G4 NOT_EVALUATED (`FRESH_MODEL_SESSION_NOT_ATTESTED`); state HALTED (`verdicts.json`, `replay-summary.json`). The hardened historical checker passes all 38 tests: 1 aggregate historical test (3 historical case subtests) and 37 tamper tests (`replay-checker.txt`). This replays retained behaviour; it does not authenticate the historical execution. |
| Fresh approved delivery | **NOT ESTABLISHED** | There is no owner-approved v2 contract or receipt and no outer freeze, and no model was called. G4 has no PASS path until owner decision D2; the G2 claim waits on D3. |
| Merge readiness | **NOT READY** | Stacked PRs are open and unmerged. The lower PRs carry the known `ARCHITECTURE_BOUNDARY_DRIFT` until #227 is merged into them (proposed top-down merge). A named human makes every merge decision. |

## Changes from the earlier R4 replay (`docs/evidence/r4-repair-20260924/resume-replay-summary.json`)

These are identical: state, cause, all five gate statuses, process records (56), digest boundaries (117) and fresh model calls (0). Only the source-bound digests differ: contract, plan and gate-evidence event. The source manifest binds the engine files, which changed through the repairs, so this difference is expected. Historical evidence is not rewritten.

## Reproduce

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$(mktemp -d)"
PYTHONPATH=src python scripts/r3_task_store_migration.py \
  --packet <PM-agent-OS@33a35962>/reviews/task-tracker-v1 \
  --historical-engine <production-engineering-os@c1ab2def189f> --output <new dir> --replay
# Verify the new directory itself: ledger chain, ledger-bound gate evidence and source
# manifest, verdicts, and the summary including its status and approval fields.
PYTHONPATH=src python -B docs/evidence/w3-reconciliation-20260925/verify-replay.py <new dir>
# The verifier's own regressions over the retained archive (forged approval, swapped manifest):
python -B docs/evidence/w3-reconciliation-20260925/test_verify_replay.py -v
# Separately, the hardened checker's regression suite over the historical retained cases
# (it reads docs/evidence/integration-review-20260924, not <new dir>):
R4_REPLAY_PACKET=<packet> R4_REPLAY_SOURCE=<historical engine> \
  python -B docs/evidence/r4-repair-20260924/test_replay_checker.py -v
```

The migration command relaunches itself source-only if started without those variables. `verify-replay.py` also accepts the retained archive once it is extracted (`tar xzf retained-replay.tar.gz`, then pass `w3-replay5`).

Architecture scanner (invocation, environment and exit status in `architecture-scanner.txt`):

```bash
cp docs/evidence/w3-reconciliation-20260925/architecture-scanner.py <checkout>/
cd <checkout> && PYTHONPATH=src:. python -B architecture-scanner.py   # exit 0, prints architecture-scanner.json
```

Release-gate comparison (per-case outcomes in `release-gates-*.junit.xml`):

```bash
T="tests/unit/test_release_gate_compiler.py tests/unit/test_release_gate_admission_boundaries.py tests/integration/test_release_gate_runtime.py"
PYTHONPATH=<main checkout>/src:. python -m pytest -p no:cacheprovider -q $T --junitxml=release-gates-main.junit.xml
PYTHONPATH=src:. python -m pytest -p no:cacheprovider -q $T --junitxml=release-gates-head.junit.xml
```

## Limits

- The same trusted-operator boundary as before: in-process code could still tamper.
- The bytecode-injection and evidence-forgery adversarial rechecks recorded as UNVERIFIED in R4 were not rerun.
- No sandbox proof: the historical host fallback is disclosed and is not isolation.
- No new product claim. The AI task planner is not generated or approved (see #218 / #219).
