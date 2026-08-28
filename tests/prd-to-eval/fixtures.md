# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/prd-to-eval/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Turn this PRD into an eval"
T2. "Define 'good' for our AI ticket summarizer — here's the spec"
T3. "Build quality gates and a judge rubric for this feature"
T4. "/pm how do we test whether this AI feature works? Spec attached" (via orchestrator)
T5. "Write the eval criteria for the summary generator"

SHOULD NOT FIRE:
N1. "Freeze criteria and generate the artifact"   (builder-validator — build-time, not eval design)
N2. "Run the eval on these 50 outputs"            (execution, not design)
N3. "What's the difference between a gate and a rubric?"  (knowledge question)
N4. "Go/no-go on building the summarizer"          (ai-feature-go-no-go)

# Gate 3 — Known-answer

FIXTURE INPUT (spec):
"AI support-ticket summarizer. Requirements: summaries must never invent order numbers
or amounts; must include ticket status; should be concise; should read naturally;
must escalate-flag tickets mentioning legal threats; tone should match our brand."

EXPECTED OUTPUT PROPERTIES:
1. GATES-VS-RUBRIC DISTINCTION ENFORCED:
   - Disqualifiers → binary GATES: invented order numbers/amounts (fabrication),
     missing ticket status (required field), missed legal-threat escalation (safety).
   - Tradeable qualities → SCORED RUBRIC: concision, naturalness, brand tone.
   - "Concise" appearing as a gate, or "never invents amounts" appearing as a 1-5
     score = gate failure (a 3/5 on fabrication is meaningless).
2. EVERY GATE BINARY-TESTABLE: stated as a check with a definite yes/no procedure
   ("every order number in the summary appears verbatim in the ticket" — mechanically
   checkable) and marked mechanical vs needs-judge. A gate that needs a taste call
   ("summary is not misleading") must be reformulated or moved to the rubric.
3. EVERY RUBRIC DIMENSION ANCHORED: 1-5 scale with concrete "what a 1 looks like" /
   "what a 5 looks like" anchors (not "poor…excellent"). Unanchored dimensions = gate failure.
4. Gates run first; any gate failure = automatic fail regardless of rubric scores —
   stated in the output. Gates are never averaged into the score.
5. Each gate/dimension traces to a spec line; no invented requirements.

PLANTED-FAILURE CASE:
A draft with "Accuracy: 1-5 — how accurate are the facts?" (fabrication as a scored
tradeable, and unanchored) MUST be caught twice by the gate: fabrication moves to a
binary gate, and any remaining scored dimension gets real anchors. A rubric row
scoring a disqualifier surviving to output = harness failure.
