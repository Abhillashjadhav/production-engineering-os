---
name: production-engineer
description: "Production Engineering OS entry point: turns an APPROVED ProductDecisionContract into tested, reviewed, deployable software by driving `pmpe eng` through the run stage machine — every agent artifact admitted by deterministic validators, every step recorded in the evidence ledger. Use when a contract should become software or a run needs attention — 'start with this contract', 'status', 'resume the run', 'release report', 'review-only on the candidate', 'eval-only'. Do NOT use to decide what to build or change product intent (PM Agent OS's plane — scope/AC/requirement changes are ProductChangeRequests), to review PRs (/pr-review), or for repo maintenance."
argument-hint: "<mode: start|status|resume|report|review-only|eval-only> <contract path or run dir>"
---

# Production Engineer

PM Agent OS decides WHAT should be built; this skill turns that approved decision into verified software. The Python core (`pmpe eng`) is the only authority over state, validation, and gates — this skill orchestrates agents and relays evidence; it never adjudicates its own output.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Locked contract or no run:** every run starts with `pmpe eng start`, which refuses non-runnable contracts (not APPROVED, unnamed approver, unresolved product-critical questions) and locks a canonical digest. If the lock fails, the report is the blocker list — never a "provisional" run.
- **G2 — Admission-only artifacts:** every agent output enters the run exclusively through `pmpe eng submit` (or the engine action commands). An artifact the validators reject is reported with its rejection reasons and returned to the producing agent — the skill never edits an artifact to make it pass, and never writes run files by hand.
- **G3 — Evidence over claims:** status, report, and completion statements quote `pmpe eng status`, the evidence ledger, and command exit codes. A step with no ledger event did not happen; a gate whose command was not run is reported as NOT RUN, not as passed.

## Modes

**start `<contract.json>`** — `pmpe eng start --contract <path> --run-dir <runs/dir>`, then work the stage machine in order, spawning the stage agent and submitting its artifact at each step:
1. `assess` — current-state assessment of the workspace (engine records it).
2. `submit --agent v2-system-architect` — architecture pack bound to the contract digest; reversible decisions only, escalations for anything user-visible or irreversible (PD-04).
3. `submit --agent v2-implementation-planner` — plan covering every requirement, each task with behavioural test, rollback, and capability.
4. `submit --agent v2-engineer-router` — minimum specialist set, every unused profile justified (PD-05).
5. For each routed task: spawn the assigned specialist in its worktree, then `submit` its result (tests before implementation).
6. `submit --agent v2-integration-engineer`, then `freeze --repo <workspace>` — the immutable review target.
7. Review round (below), reconcile, fix/retest/refreeze/verify as findings require.
8. `draft-pr`, then the deployment ladder: local → staging automatically after gates; production only via `approve-production` + `deploy` (fixture mode; PD-08/PD-09 — draft PR only, no real cloud).

**status** — `pmpe eng status --run-dir <dir>`; report stage, pending tasks, findings, and gate state. Read-only.

**resume `<run dir>`** — `pmpe eng resume`; the engine re-verifies the locked contract (fail closed on mutation) and names the next expected actor. Continue exactly there — completed stages are never re-run.

**report** — release report from `pmpe eng status` + the evidence ledger: what was verified (with executed-test evidence), what is blocked and why, open ProductChangeRequests, deployment state. Production readiness is stated only from the recorded gates.

**review-only** — on a frozen candidate: `review-begin`/`submit`/`review-end` for all four reviewers (code, product-conformance, architecture-simplicity, eval-integrity) — read-only, fresh contexts, same digest, blind to each other (PD-06) — then `reconcile`. No fixer step; output is the findings/PCR report.

**eval-only** — `pmpe evals run --suite all` (+ `pmpe drift compare` against the baseline). Report pass rates, hard-gate failures, trajectory violations, and the drift verdict verbatim; a HOLD is a HOLD.

## Review round (used by start and review-only)

For each reviewer, in a fresh context: `review-begin --agent <r> --repo <ws>` → spawn the reviewer read-only on the frozen candidate → `submit` its findings → `review-end` (records the read-only proof; a modified tree fails the round). Then `reconcile --owner <named owner>`; undecided findings block (exit 3) until the owner decides — the skill relays the question, it does not decide.

## Hard rules

1. Product intent is never edited here: scope, acceptance-criteria, requirement, or metric changes found mid-run become ProductChangeRequests via reconciliation — the contract stays locked and a new version starts a new run (PD-03).
2. Reviewers never fix; the fixer touches only ACCEPTED finding IDs; the verifier of a fix is never its fixer (PD-07). All three are enforced by the engine — a rejection is relayed, not worked around.
3. Production deployment requires a named, recorded, digest-bound human approval (`approve-production`), and even then executes only in fixture mode — any claim of a real production deployment is false and must not be made (PD-09).
4. Never report a check as passed without running it in this session and seeing exit 0; paste the command and result into the report.
5. No self-prompting loops, schedulers, or daemons — every run step is initiated by an explicit user request in one of the six modes (PD-10).

## Limitations

- The engine enforces process, not correctness of agent judgment: a plausible-but-wrong architecture that satisfies the validators is caught (if at all) by the independent review round, not at admission.
- Live agent quality depends on the Claude Code runtime; CI exercises the same admission machinery with labeled synthetic fixtures, which proves the gates but not live generation quality.
- Deployment past staging is policy + fixture simulation only — there is deliberately no cloud adapter; a real production path is future work behind the same approval gate.
- Trajectory evals audit the ledger the engine wrote; they add independent value mainly for hand-authored or externally produced ledgers, and as a regression tripwire on the engine itself.
