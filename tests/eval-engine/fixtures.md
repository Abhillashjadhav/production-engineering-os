# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/eval-engine/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Create an eval for this spec: [spec]"
T2. "Build the full verification layer for our AI ticket summarizer"
T3. "Spec to eval harness — gates, rubric, judge prompt, the works"
T4. "/pm we're shipping the classifier — build its eval end to end" (via orchestrator)
T5. "Turn this PRD into something we can actually run outputs through"

SHOULD NOT FIRE:
N1. "Turn this PRD into gates and a rubric" is prd-to-eval's phrasing — BOUNDARY:
    prd-to-eval designs the gates/rubric artifact; eval-engine produces the full
    runnable layer (gates + rubric + judge prompt + harness instructions). A bare
    gates-and-rubric ask stays with prd-to-eval; "eval I can run" comes here.
N2. "Write the judge prompt for these existing criteria"   (llm-as-judge-designer)
N3. "Run this eval on 50 outputs"                          (execution)
N4. "What's an eval?"                                       (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT (spec):
"AI expense-report auditor: flags policy violations in submitted expense reports.
Requirements: must never invent a violation that isn't in the policy doc; must cite
the policy rule for each flag; must not miss alcohol-on-client-dinner violations
(compliance-critical); should explain flags in plain language; should keep review
time short; tone should be neutral, not accusatory."

EXPECTED OUTPUT PROPERTIES (four artifacts, one pass):
1. GATES (binary, disqualifying): invented violations (fabrication — check: every
   flagged rule exists verbatim in policy doc [mechanical]); missing rule citation
   [mechanical]; missed alcohol-violation on a seeded case [mechanical against
   golden case]. Each gate: check procedure + mechanical/judge tag + why-disqualifying.
2. RUBRIC (scored 1-5, anchored): plain-language clarity, review-time economy,
   neutral tone — each with concrete 1-anchor and 5-anchor.
3. THE NEVER-MIX GATE: no disqualifier appears as a score, no tradeable as a gate.
   "Accuracy 1-5" or "tone must be neutral [gate]" = gate failure. Execution order
   stated: gates first, any failure = automatic fail, gates never averaged.
4. JUDGE PROMPT: paste-ready, returns structured verdict (gates pass/fail + rubric
   scores + evidence quotes), embeds the anchors, instructs the judge to quote the
   output text it graded.
5. HARNESS INSTRUCTIONS: how to run it — case format, gates-first order, where human
   spot-checks land (every gate-fail + N random passes), what triggers recalibration
   (human-judge gap ≥2 → judge-calibration-auditor).
6. Everything traces to the spec; nothing invented (no latency requirements the spec
   didn't state).

PLANTED-FAILURE CASE:
A draft whose rubric includes "Violation accuracy: 1-5 — how accurate are the flags?"
(the compliance-critical disqualifier as a tradeable score) MUST be caught by the
never-mix gate and re-sorted into the mechanical fabrication/citation gates.
