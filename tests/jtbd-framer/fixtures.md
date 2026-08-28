# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/jtbd-framer/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Frame this feature idea as jobs-to-be-done"
T2. "What job is a shared team calendar actually hired for?"
T3. "Turn 'add AI meeting summaries' into JTBD statements"
T4. "/pm what are users really trying to get done with export-to-PDF?" (via orchestrator)
T5. "Rewrite these feature requests as jobs"

SHOULD NOT FIRE:
N1. "What is jobs-to-be-done theory?"               (knowledge question)
N2. "Write the PRD for meeting summaries"           (Build stage — not shipped)
N3. "Synthesize these interviews"                   (interview-synthesizer; it may FEED this skill)
N4. "Prioritize these 10 features"                  (prioritization, not job framing)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Feature idea: an AI-powered auto-scheduler button that finds a free slot and books
the meeting in one click. Context: sales reps at 50-person agencies, booking demos
with external prospects."

EXPECTED OUTPUT PROPERTIES:
1. 2–4 job statements in the form:
   "When [situation], I want to [motivation], so I can [expected outcome]."
2. ZERO solution language inside any statement — banned inside the brackets:
   the feature name and its mechanics (auto-scheduler, button, AI, one click), any
   product/brand names, technology nouns (algorithm, app, dashboard, integration),
   and UI verbs (click, tap, toggle, open). E.g. expected shape:
   "When a prospect agrees to a demo on a call, I want to lock the time before their
   interest cools, so I can keep the deal moving."
3. Each statement tagged functional / emotional / social — at least one non-functional
   dimension must be surfaced (e.g. not looking disorganized in front of a prospect = social).
4. Traceability: each statement maps back to the input context (rep, demo, prospect) —
   no invented personas (no "enterprise admins" that appear from nowhere).
5. A "hiring criteria" line per job (what the rep fires: back-and-forth emails, the
   assistant, manual calendar tetris) — competition framed as alternatives, not features.

MECHANICAL CHECK (the gate's self-audit):
Scan every bracketed segment against the banned-language classes above. One hit = rewrite
that statement and re-scan.

PLANTED-FAILURE CASE:
A draft statement "When I click the auto-scheduler, I want the AI to find a slot, so I
can book in one click" (all three brackets solution-contaminated) MUST be caught by the
zero-solution-language scan and rewritten around the underlying job.
