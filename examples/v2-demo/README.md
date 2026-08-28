# V2 synthetic demonstration

Everything in this demo is **synthetic and labeled as such**: the contract is a
demonstration fixture, the workspace is generated with deliberately planted
defects, and the agent artifacts are deterministic fixtures standing in for
live Claude agents (PD-11: CI proves the admission/gate machinery, not live
generation quality). Nothing here deploys to a real environment (PD-09).

## What it does

`pmpe demo --base-dir <dir>` (or `pmpe.demo.synthetic.run_demo`) builds a
synthetic workspace, then drives one complete engineering run against
`contract.json`:

1. **Plant** four failures:
   - a code defect — `parse_config()` calls `eval()` on operator input,
   - a conformance failure — FR-002 has no executed test (marker-free: proven
     by running the suite, not by reading annotations),
   - a complexity defect — an `AbstractProviderFactory` no requirement asked for,
   - a planted trajectory violation + a planted drift regression (pre-built
     eval fixtures under `evals/fixtures/`).
2. **Detect** them with the real machinery: the deterministic security scanner
   (SEC_EVAL), executed traceability (FR-002 = NOT_PROVEN), the review round
   (four read-only reviewers on the same frozen candidate), trajectory evals
   (TRAJ violation on the planted ledger), and drift compare (HOLD on the new
   hard-gate failure).
3. **Reconcile**: three engineering findings ACCEPTED by a named owner; one
   product-boundary finding becomes a ProductChangeRequest instead of a code
   change (PD-07).
4. **Fix** only the ACCEPTED findings (real edits, real commit), **retest**
   (the workspace suite re-runs and passes), **re-freeze**, and **verify**
   each fix with a verifier who is never the fixer.
5. **Record** the draft-PR reference, authorize **local** and **staging**
   deployments, and show **production honestly blocked** — no named,
   digest-bound human approval exists, so the ladder refuses (exit-3 semantics),
   and even an approved production deploy would run in fixture mode only.

The run's own evidence ledger is then audited by `evaluate_trajectory` and must
come back clean. The demo report (`demo-report.json` in the base dir) carries
`"synthetic": true` and quotes the evidence for every claim above.

## Run it

```bash
pmpe demo --base-dir /tmp/pmpe-demo
cat /tmp/pmpe-demo/demo-report.json
```

The e2e test `tests/e2e/test_v2_demo.py` runs exactly this and asserts every
planted failure was caught, fixed (where accepted), and honestly reported.
