# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/model-complexity-router/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE (direct ask → full scored breakdown):
T1. "Which model should I use to refactor my auth module?"
T2. "Am I overpaying by running Opus for these copy tweaks?"
T3. "Is fixing this CSS alignment an Opus task or can Haiku do it?"
T4. "Route this data-cleanup task to the right model"

SHOULD FIRE (task handoff, no model question → one compact line, task not delayed):
T5. "Fix the typo in the README and push it"
T6. "Design the migration plan from monolith to services"

SHOULD NOT FIRE:
N1. "Which LLM is best, Claude or GPT?"          (vendor comparison, no concrete task)
N2. "Explain how transformers work"               (knowledge question)
N3. "What's Opus pricing?"                        (pricing lookup only)
N4. "Any update on that CSS fix?"                 (same task, already scored — once per task, not per message)

# Gate 3 — Known-answer (pre-labeled classifications)

Rubric: 4 axes, 0–2 each — scope, reasoning depth, error cost, context load. Total 0–8.
Map: 0–2 Haiku · 3–5 Sonnet · 6–8 Opus. Floor rule: error-cost = 2 → never Haiku
(floor at Sonnet), applied as a FLOOR on the mapped tier, never as a second addition
to the score.

F1. "Fix a typo in README" .............................. Haiku  (scope 0, reasoning 0, error 0, context 0 → 0)
F2. "Add pagination to an existing REST endpoint" ........ Sonnet (≈1+1+1+1 → 4)
F3. "Design monolith→services migration plan" ............ Opus   (2+2+1+2 → 7)
F4. "Rewrite pricing-page copy going live to customers" .. Sonnet (scope 0, reasoning 1, error 2, context 0 → 3 → Sonnet; floor coincides, applied once)
F5. "Rename a variable across one 200-line script" ....... Haiku  (0+0+0+0 → 0)

GATE CHECK REQUIRED IN OUTPUT: every recommendation shows the four axis scores it
derived from (a tier with no visible scores = gate failure), and the floor rule is
applied at most once, only at the mapping step.

PLANTED-FAILURE CASE (the double-count defect from the original build):
Scoring F4 as "0+1+2+0 = 3, plus error-cost bump → 4... and floor to Sonnet because
error cost is 2" — counting error cost in the total AND adding a bump/tier-raise on
top. The gate must catch any path where error-cost influences the outcome twice:
correct behavior is error cost in the sum once, floor applied only if the mapped tier
came out Haiku. An output showing a score inflated beyond the four axis values, or a
tier raised above the map+floor result, = harness failure.
