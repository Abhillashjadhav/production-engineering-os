# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/prompt-optimizer-loop/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Improve this prompt — it keeps returning vague summaries"
T2. "Tune my extraction prompt against these criteria"
T3. "Optimize this system prompt, one change at a time"
T4. "/pm my support-bot prompt hallucinates policies — fix the prompt" (via orchestrator)
T5. "This prompt works 60% of the time; make it reliable"

SHOULD NOT FIRE:
N1. "Write me a prompt for summarizing calls"    (authoring from scratch — no baseline to mutate)
N2. "Why do LLMs hallucinate?"                   (knowledge question)
N3. "Freeze criteria and build the artifact"      (builder-validator)
N4. "Which model should run this prompt?"         (model-complexity-router)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Prompt (baseline): 'Summarize this customer call.'
Checklist (scoring, 1 pt each): (1) names the customer's issue, (2) states resolution
status, (3) lists action items with owners, (4) ≤120 words, (5) no invented details.
Test case: [a fixture call transcript]. Baseline score: 2/5 (misses 2, 3; violates 4)."

EXPECTED OUTPUT PROPERTIES:
1. ROUND DISCIPLINE: each round applies EXACTLY ONE mutation (add a constraint, add an
   example, restructure one instruction — one of these, never a rewrite-everything).
   The mutation is named and diffable. Two changes in one round = gate failure.
2. SCORE LOG REQUIRED: every round logs — round #, mutation applied, score before,
   score after, keep/revert decision. A round without a logged score = gate failure.
3. REVERT ON NON-IMPROVEMENT: score drops or ties → the mutation is reverted (logged
   as reverted) and the next round mutates from the last-kept version. Building on a
   non-improving mutation = gate failure.
4. Scores come from re-running the checklist against the test case — checklist items
   are the only rubric; no "feels better" scoring.
5. Stop conditions honored: full score, plateau (2 consecutive non-improvements), or
   round cap (5) — with the final prompt, final score, and the kept-mutation history.

PLANTED-FAILURE CASE:
Round 2 draft: "restructured the instructions AND added an example — score improved
2→4, keeping both." Two mutations in one round: even with an improved score, the
gate must catch it — attribution is impossible (which change earned the +2?). Correct
behavior: revert, re-apply as two rounds. A log showing a multi-mutation round kept
= harness failure.
