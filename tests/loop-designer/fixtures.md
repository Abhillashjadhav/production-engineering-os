# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/loop-designer/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Turn 'summarize new GitHub issues every morning' into an autonomous loop"
T2. "Design a guarded loop for the weekly metrics digest"
T3. "I keep doing this chore by hand — make it a scheduled agent loop"
T4. "/pm automate the daily support-queue triage safely" (via orchestrator)
T5. "Build me the loop spec for nightly changelog drafting"

SHOULD NOT FIRE:
N1. "Design guardrails for this workflow"          (guardrail-designer — workflow, not a recurring loop)
N2. "Set up a cron job to run this script"          (plain scheduling, no agent loop anatomy)
N3. "Run the loop now"                              (execution)
N4. "What's an autonomous loop?"                    (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT (chore):
"Every Monday I collect last week's support tickets, cluster the complaints, and
post a themes summary to #product. Takes an hour. Automate it."

EXPECTED OUTPUT PROPERTIES:
1. FIVE-PART ANATOMY, all present and named: Discover (pull last week's tickets —
   source + window stated) · Plan (cluster by theme — method stated) · Execute
   (draft the summary post) · Verify (checks BEFORE posting) · Stop (post + report,
   or halt conditions). A loop missing any part = gate failure.
2. THE SEPARATION GATE: the executor never verifies its own work. The Verify step
   is structurally separate from Execute — a different agent/pass with its own
   instructions (or a mechanical check suite), and the loop spec says HOW it's
   separate ('verifier receives the draft + raw ticket IDs, not the executor's
   reasoning'). 'The agent double-checks its summary' = gate failure.
3. VERIFICATION-FIRST STEP 0 PRESENT: before the loop is assembled, Step 0 defines
   what a correct run produces (checkable conditions: every theme cites ≥2 ticket
   IDs; counts reconcile to ticket total; zero invented ticket quotes) — the
   verifier checks THESE, written before the executor prompt exists.
4. ALL FIVE GUARDRAILS present, each named-failure + trigger (guardrail-designer's
   rule applies inside loops too):
   - scope ceiling (processes ≤N tickets; more → halt + human)
   - output gate (verify fails → NO post; report failure instead)
   - loop kill switch (2 consecutive failed runs → loop disables itself + alerts)
   - cost/step budget (token/step ceiling per run, stated as instruction + runner cap)
   - no-silent-drift (source schema/volume anomaly (±3x usual) → halt, don't improvise)
5. Runner artifact: a ready-to-paste scheduled prompt (Routine/cron) whose body
   contains the anatomy + guardrails; schedule stated from the chore (Monday).
6. Honest limits: what the loop can't be trusted with (novel complaint types get
   flagged-not-classified; the human reads the summary before acting on it in week 1-4).

PLANTED-FAILURE CASE:
A draft whose Verify step reads 'after drafting, the agent reviews its own summary
for accuracy and posts if satisfied' — self-verification — MUST be caught by the
separation gate and rebuilt as an independent verifier pass with the Step 0
conditions as its checklist.
