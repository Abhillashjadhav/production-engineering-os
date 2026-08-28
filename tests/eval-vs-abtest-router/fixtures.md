# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/eval-vs-abtest-router/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Should we eval this or A/B test it?"
T2. "How do we know if the new summarizer is better — offline eval or experiment?"
T3. "Marketing wants an A/B test on the AI drafts — is that the right tool?"
T4. "/pm we changed the prompt, how do we measure if it worked?" (via orchestrator)
T5. "Route this question: does shorter output increase feature adoption?"

SHOULD NOT FIRE:
N1. "Build the eval"                                (eval-engine — after routing says eval)
N2. "Design the A/B test"                           (experiment design — after routing says test)
N3. "Should we build this feature?"                 (ai-feature-go-no-go)
N4. "What's the difference between evals and A/B tests?"  (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT (three questions to route):
Q1. "Is the new summarizer prompt producing more accurate summaries than the old one?"
Q2. "Does the AI-drafts feature increase reply rate for sales reps?"
Q3. "Users say summaries feel generic — should we make them punchier?"

EXPECTED OUTPUT PROPERTIES:
1. THE CLASSIFICATION GATE: every routing verdict states which kind of question it
   is — OUTPUT-QUALITY (a property of the artifact, judgeable offline against
   criteria) or USER-BEHAVIOR (a property of humans reacting, observable only in
   the field) — BEFORE naming the tool. A routing with no stated classification
   = gate failure.
2. Expected routings:
   - Q1 → OUTPUT-QUALITY → EVAL (golden set + judge; an A/B test would measure
     user tolerance of errors, not accuracy — the mismatch stated).
   - Q2 → USER-BEHAVIOR → A/B TEST (reply rate lives in the field; no offline
     judge can produce it — and the eval prerequisite stated: don't experiment
     with a variant that fails quality gates; eval FIRST as entry criterion).
   - Q3 → COMPOUND → SPLIT: 'punchier' is output-quality (defineable, evaluable
     against anchors) and 'do users prefer it' is user-behavior (A/B) — the skill
     must split it, route each half, and sequence them (eval-gate the punchier
     variant, then test preference).
3. Each routing carries: what the chosen tool answers, what the rejected tool
   would actually measure if misused here (not generic cons), sample/timeline
   reality (400 users ≠ significance in a week — labeled estimate arithmetic if
   volume given, honest 'depends on traffic' if not).
4. The eval-first sequencing rule where both apply: quality gates before behavior
   experiments; shipping a gate-failing variant to an A/B test is banned and said.
5. No invented traffic numbers, MDE math from data not provided, or fake
   significance thresholds presented as calculated.

PLANTED-FAILURE CASE (the misrouted case the gate must catch):
A draft routing Q1 to an A/B test 'because real users are the ultimate judge of
accuracy' — user-behavior tooling pointed at an output-quality question (users
can't label accuracy at read time; the test would measure preference/tolerance,
not correctness) — MUST be caught by the classification gate and re-routed to
EVAL with the mismatch explained.
