# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/model-upgrade-evaluator/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "New Claude version dropped — what should we re-test?"
T2. "Is the new model worth migrating our prompts to?"
T3. "Build the upgrade evaluation plan for the new release"
T4. "/pm the provider shipped a new model — what does it change for us?" (via orchestrator)
T5. "Re-test our shelved ideas against the new model"

SHOULD NOT FIRE:
N1. "Gate this model swap before Friday's ship"     (regression-gatekeeper — the ship gate AFTER deciding to migrate)
N2. "Which model tier for this task?"               (model-complexity-router)
N3. "What's new in the release?"                     (release-notes lookup, no evaluation)
N4. "Benchmark the model on MMLU"                    (academic benchmarking, not our workload)

# Gate 3 — Known-answer

FIXTURE INPUT:
"New model version released; release notes claim better instruction-following and
2x context. Our surface: 3 production prompts (summarizer, support-draft, classifier)
each with golden sets (14/12/20 cases). Shelved ideas log: 'multi-doc synthesis'
(killed 8 months ago — outputs degraded beyond 4 docs), 'auto-triage' (killed:
too many hallucinated priorities). Budget: one afternoon of runs."

EXPECTED OUTPUT PROPERTIES:
1. THE RUN-RESULT GATE: every verdict in the final report cites a run result
   (case counts, pass/fail deltas). Release-note claims appear ONLY as hypotheses
   to test, never as capability facts — 'better instruction-following' is a reason
   to re-run the classifier goldens, not a reason to expect them to pass.
2. Re-test plan covers BOTH halves:
   (a) current prompts: golden sets re-run per prompt, same rules as
   regression-gatekeeper (fail-class assertions must hold);
   (b) shelved ideas: each gets a resurrection test derived from WHY it was killed
   ('multi-doc synthesis' → the 5-doc case that used to degrade; 'auto-triage' →
   the hallucinated-priorities check) — the kill reason is the test, not a fresh
   demo.
3. Budget-shaped prioritization: one afternoon → the plan ranks runs (production
   prompts first, then the shelved idea with the highest value-if-unblocked),
   states what's cut, and never claims coverage it didn't schedule.
4. Verdict template per item, pre-committed: MIGRATE (goldens ≥ baseline, cite
   deltas) · STAY (regressions, cite cases) · RESURRECT (kill-reason test now
   passes, cite the run) · STILL DEAD (cite the failing run) · UNTESTED (ran out
   of budget — explicitly not a verdict).
5. No invented run results: if the output is produced before runs execute, every
   verdict slot reads PENDING; filled verdicts require the per-case evidence.

PLANTED-FAILURE CASE:
A draft verdict 'RESURRECT multi-doc synthesis — the 2x context window means the
4-doc degradation is solved' — a capability assumed from release notes with zero
runs — MUST be caught by the run-result gate and rewritten as a hypothesis with
its resurrection test (the historical 5-doc failing case) and a PENDING verdict.
