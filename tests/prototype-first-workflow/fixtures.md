# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/prototype-first-workflow/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Plan the smallest prototype for AI-suggested replies"
T2. "How do we prototype this before committing a quarter to it?"
T3. "Design the spike for the recommendation engine idea"
T4. "/pm what's the fastest way to test if this feature works before building it?" (via orchestrator)
T5. "Give me a prototype plan for voice-note transcription in the app"

SHOULD NOT FIRE:
N1. "Build the prototype"                        (execution — this plans it)
N2. "Go/no-go on the recommendation engine"      (ai-feature-go-no-go — decision, not test design)
N3. "Map the assumptions behind this idea"       (assumption-mapper — upstream input to this skill)
N4. "What is a concierge test?"                  (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Feature idea: AI-suggested replies in our recruiting CRM — recruiters get 3 draft
responses per candidate email. Team believes it saves 30+ min/day per recruiter.
Risk we're arguing about: recruiters won't trust AI drafts with senior candidates.
We have 5 design-partner agencies."

EXPECTED OUTPUT PROPERTIES:
1. THE DISPROVE GATE: the plan names what the prototype MUST DISPROVE — the kill
   hypothesis, stated as a falsifiable claim with a threshold: e.g. "recruiters
   edit-or-discard >80% of drafts for senior-candidate emails" or "median time saved
   < 10 min/day". A plan that only lists what the prototype will demonstrate
   ("show that drafts are useful") = gate failure.
2. Smallest-testable check: the plan must be the MINIMUM build that can kill the
   hypothesis — for this fixture, expect something like a Wizard-of-Oz or
   template+LLM sidecar for 2 of the 5 partner agencies, NOT "build the feature
   behind a flag". Every plan component must be justified by the kill test; scope
   that serves the demo but not the test is cut.
3. Pass/kill thresholds pre-committed: numbers set BEFORE the run, with their basis
   (the team's own 30-min claim becomes the bar it must clear).
4. Measurement is defined: what's logged (edit distance, discard rate, time-on-task),
   over what window, with how many users — from input context (5 agencies) only.
5. An explicit "if killed / if survived" next step each — a prototype without a
   consequence is theater.

PLANTED-FAILURE CASE:
A draft plan whose success section reads "the prototype will demonstrate draft
quality and validate the time-savings story" with no falsifiable kill condition —
the disprove gate MUST catch it and force the kill hypothesis + threshold before
the plan can ship.
