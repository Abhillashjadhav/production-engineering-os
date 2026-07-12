# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/research-brief/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Write a research plan for whether SMBs would pay for audit logs"
T2. "How should we figure out why activation dropped after signup redesign?"
T3. "Draft the research brief for the Q3 pricing decision"
T4. "/pm we don't know if enterprise buyers care about SSO — plan the research" (via orchestrator)
T5. "What research do we need before betting on the mobile app?"

SHOULD NOT FIRE:
N1. "Synthesize these interviews we already ran"     (interview-synthesizer — after research, not before)
N2. "What's the difference between qual and quant research?"  (knowledge question)
N3. "Run a survey for me"                            (execution, not planning)
N4. "Deep-research the LLM eval tooling market"      (web research task — /deep-research harness, not a PM research plan)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Question: why did week-1 activation drop from 40% to 28% after the signup redesign?
Context: B2B SaaS, ~900 signups/month, we have product analytics and can email new
signups. Decision we're facing: roll back the redesign, patch it, or keep it."

EXPECTED OUTPUT PROPERTIES:
1. The brief opens with the DECISION(S), not the methods: roll back / patch / keep,
   plus decision criteria ("we roll back if …").
2. METHOD→DECISION MAP REQUIRED: every proposed method (e.g. funnel analysis of the
   new flow, 5 interviews with non-activated signups, session replays, a holdback
   re-exposure test) is mapped to the specific decision it informs and what answer
   would push which way. An orphan method — proposed but mapped to no decision — = gate failure.
3. Coverage both ways: every decision option has ≥1 method that could rule it in or out.
   A decision with zero informing methods = gate failure.
4. Each method carries: participants/data source, sample size with a stated basis
   (n=5 interviews because pattern saturation, not statistical significance),
   time/cost class (days vs weeks), and its kill/confirm signal.
5. Sequencing: cheapest decisive method first (analytics before interviews before
   experiments), with an explicit "stop early if" condition.
6. No fabricated context: the brief may not assume research infrastructure, budgets,
   or user panels the input didn't mention.

PLANTED-FAILURE CASE:
A draft proposing "run a diary study" with no mapping to roll-back/patch/keep — a
method included because it sounds thorough — MUST be caught by the orphan-method gate
and either mapped to a decision or cut.
