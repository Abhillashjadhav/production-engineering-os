# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/judge-calibration-auditor/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Our judge disagrees with human reviewers — audit it"
T2. "Human labels vs judge verdicts attached — what's drifting?"
T3. "Calibrate the judge against these 30 human-graded cases"
T4. "/pm the judge scores everything 4 — figure out why" (via orchestrator, data attached)
T5. "Disagreement analysis on the eval judge"

SHOULD NOT FIRE:
N1. "Write the judge prompt for these criteria"    (llm-as-judge-designer — no judge yet)
N2. "Build the eval from this spec"                (eval-engine)
N3. "Label these outputs for me"                   (that's the human's half — the skill audits, it doesn't replace the human labels)
N4. "Are LLM judges biased?"                        (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT (12 paired verdicts, empathy dimension 1-5 + one gate):
Cases where human == judge: 7 of 12.
Disagreements:
D1. #4: human 2, judge 4 — reply solves everything, opens with policy language
D2. #7: human 2, judge 4 — same pattern: complete solution, no acknowledgment
D3. #9: human 3, judge 5 — long reply, heavy hedging, judge cites its thoroughness
D4. #11: human PASS, judge FAIL on the no-commitments gate — reply says "I'll
    personally make sure this gets prioritized" (human read: reassurance; judge
    read: commitment)
D5. #12: human 4, judge 2 — terse but warm reply ("Ugh, that's on us. Fixed —
    check now.") — judge cites "unprofessional tone"

EXPECTED OUTPUT PROPERTIES:
1. THE NEVER-AUTO-RESOLVE GATE: no disagreement is resolved by assuming the judge is
   right — AND none by assuming the human is right without analysis. Each
   disagreement is classified with a stated correction:
   - D1+D2 (systematic, same direction, same pattern): anchor defect — the empathy
     anchors don't penalize solution-without-acknowledgment → correction: rewrite the
     2-anchor with exactly this exemplar (fix the anchor, not the verdicts).
   - D3 (judge rewards verbosity): known judge bias → correction: anti-verbosity
     instruction + a long-but-hollow fail exemplar.
   - D4 (gate ambiguity): the criterion is ambiguous, not the judge — "personally
     make sure" IS commitment-shaped → correction: escalate to criterion owner with
     both readings; a gate this ambiguous needs a definition, not a calibration.
   - D5 (register mismatch): human values warmth over formality; judge imported an
     unstated professionalism criterion → correction: anti-drift reminder (grade
     only listed criteria) + warmth-positive exemplar.
2. Systematic-vs-noise separation: D1/D2 pattern (n=2, same direction) called
   systematic; single disagreements labeled provisional (n=1 — collect more before
   rewriting anchors on their basis alone, EXCEPT clear rule-imports like D5).
3. Agreement stats shown honestly: 7/12 (58%) with per-dimension breakdown; no
   invented aggregate quality score.
4. Every correction is concrete (the rewritten anchor text / the added exemplar /
   the escalation question) — "improve the judge prompt" = gate failure.
5. Human labels are never edited by the audit. If a human label looks wrong, that
   goes to the criterion owner as a question, never a silent correction.

PLANTED-FAILURE CASE:
A draft resolving D1 as "the judge's 4 is defensible — the reply does solve the
problem; recommend accepting judge verdicts for efficiency" — auto-resolving toward
the judge and burying the systematic pattern — MUST be caught by the
never-auto-resolve gate and reclassified as the anchor defect it is.
