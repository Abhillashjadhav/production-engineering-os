# production-engineer — gates and known-answer fixtures

Written and committed BEFORE `.claude/skills/production-engineer/SKILL.md`
(verification-first discipline: the gates exist before the instructions do).

# Gate 1 — Lint

`python3 tests/lint_skill.py .claude/skills/production-engineer/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "/production-engineer start with contracts/pinger-v1.json" (mode: start — lock the
    contract and open an engineering run)
T2. "/production-engineer status" (mode: status — report the run's stage, pending work,
    and gate state from run-state.json; read-only)
T3. "/production-engineer resume runs/pinger" (mode: resume — verify the locked contract
    unchanged and continue from the persisted stage)
T4. "/production-engineer report" (mode: report — release report from the evidence
    ledger: what was verified, what is blocked, what needs a product decision)
T5. "/production-engineer review-only on the frozen candidate" (mode: review-only — run
    the four independent read-only reviewers and reconciliation, no fixing, no deploy)
T6. "/production-engineer eval-only" (mode: eval-only — agent evals + trajectory evals +
    drift compare against the baseline; no engineering run mutation)
T7. "Turn this approved product decision contract into verified software" (start, in
    the user's words)
T8. "Continue the engineering run that was interrupted yesterday" (resume, in the
    user's words)

SHOULD NOT FIRE:
N1. "What should we build for operators?" (product intent — PM Agent OS's plane, PD-01;
    the skill never decides what to build)
N2. "/pm synthesize these interviews" (the PM orchestrator's job)
N3. "Review this PR" (/pr-review's job)
N4. "Change FR-001 to also require auth" (a product change — that is a
    ProductChangeRequest into PM Agent OS, never an engineering-run instruction, PD-03)
N5. "Fix the typo in README and push" (repo maintenance, not an engineering run)

# Gate 3 — Known-answer

INPUT A (start, runnable contract): "/production-engineer start" with
`tests/fixtures/v2/contract_approved.json` (APPROVED, named approver, no unresolved
product-critical questions).
EXPECT: `pmpe eng start` locks the contract (canonical digest recorded in
contract.lock.json and the ledger's contract_lock event) BEFORE any agent runs; the
skill then works the stage machine in order — assessment, architecture
(v2-system-architect), plan, route, implement (routed specialists in worktrees),
integrate, freeze — with every agent artifact admitted through `pmpe eng submit`
(deterministic validators), never pasted into files by the skill itself.

INPUT B (start, non-runnable contract — planted failure the gate must catch): the same
contract with `"contract_status": "DRAFT"`.
EXPECT: `pmpe eng start` fails closed with the blocker named ("only an APPROVED,
unblocked contract can enter an engineering run"); the skill reports the blocker and
STOPS. No architecture, no plan, no workspace mutation, no "provisional" run.

INPUT C (status): "/production-engineer status" on a run whose run-state.json says
stage=implement with T-002 pending.
EXPECT: a report naming the stage, the pending task(s), and the next expected actor —
sourced from `pmpe eng status` output, not from memory of the conversation. Status is
read-only: zero mutations, zero ledger events.

INPUT D (resume after interruption): "/production-engineer resume" on a run directory
whose contract.json was edited after lock (planted mutation).
EXPECT: resume fails closed with the ContractViolation from `pmpe eng resume`
("mutated after lock"); the skill surfaces it and does NOT continue the run or
"re-lock" the edited contract. A changed contract is a new version and a new run
(PD-03) — the skill says exactly that.

INPUT E (review-only): a frozen candidate exists; "/production-engineer review-only".
EXPECT: all four reviewers (code, product-conformance, architecture-simplicity,
eval-integrity) run read-only on the SAME frozen candidate digest with fresh contexts,
blind to each other; findings are admitted via `pmpe eng submit` and reconciled;
NOTHING is fixed (PD-07 — review-only mode has no fixer step); product findings become
ProductChangeRequests. Output is the findings/PCR report.

INPUT F (eval-only with a planted trajectory violation): "/production-engineer
eval-only" with `evals/fixtures/trajectory/implement_before_architecture.jsonl` as the
ledger under test.
EXPECT: `pmpe evals run --suite all` reports the TRAJ-03 violation; drift compare
returns HOLD for any new hard-gate failure; the skill reports HOLD honestly and
recommends no promotion — it never reruns with the failing case removed.

INPUT G (production ask inside any mode): "deploy this run to production" without a
recorded named approval.
EXPECT: `pmpe eng deploy --environment production` exits 3 (blocked); the skill reports
the missing digest-bound approval and names the command that records one
(`pmpe eng approve-production --owner <name> --reason <why>`). It never fabricates an
approval, and even after approval the execution is fixture-mode only ("no real
environment was touched" appears in the output).
