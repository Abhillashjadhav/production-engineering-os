# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/llm-as-judge-designer/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Write the judge prompt for these eval criteria"
T2. "Turn this rubric into an LLM judge with calibration examples"
T3. "Design the judge for our summary-quality eval"
T4. "/pm we have criteria, we need the judge" (via orchestrator)
T5. "Judge prompt + few-shot calibration cases for this scoring guide"

SHOULD NOT FIRE:
N1. "Build the whole eval from this spec"          (eval-engine — criteria don't exist yet)
N2. "Our judge disagrees with human labels — audit it"  (judge-calibration-auditor)
N3. "Score these 50 outputs"                        (execution)
N4. "Are LLM judges reliable?"                      (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT (criteria for a support-reply evaluator):
"C1 (gate): reply contains no commitments we can't honor (refunds, timelines, legal).
C2 (rubric 1-5): empathy — acknowledges the customer's situation before solving.
C3 (rubric 1-5): resolution completeness — answers all questions asked, not just the first."

EXPECTED OUTPUT PROPERTIES:
1. THE PASS+FAIL EXEMPLAR GATE: every criterion — gate and rubric alike — ships with
   at least one concrete PASS exemplar and one concrete FAIL exemplar, written as
   short realistic outputs (not descriptions of outputs). A criterion with only a
   pass example, only a fail example, or adjective-anchors = gate failure.
   Rubric criteria additionally need the fail exemplar to show a MID failure (a 2-3),
   not just a strawman 1 — judges drift in the middle, not at the extremes.
2. Judge prompt structure: role framing · the criteria verbatim · the exemplars as
   few-shot calibration cases with their verdicts and one-line reasons · required
   output shape (per-criterion verdict/score + the quoted evidence from the graded
   output) · explicit anti-drift instructions (grade only listed criteria; gates are
   pass/fail, never scored; when torn between two scores, cite both sentences and
   pick the lower).
3. Exemplars derive from the criteria's domain (support replies); no imported
   examples from other domains; realistic, not cartoonish.
4. Ordering effects handled: instruction that verdicts must not depend on case order,
   and calibration cases presented in mixed pass/fail order (not all-pass then all-fail).
5. A stated handoff: after N real judgments, compare vs human labels
   (judge-calibration-auditor); the prompt is v1, not truth.

PLANTED-FAILURE CASE:
A draft where C2 (empathy) ships with anchors "1 = not empathetic, 5 = very
empathetic" and a single glowing pass example — no fail exemplar, adjective anchors —
MUST be caught by the exemplar gate and rebuilt with a realistic mid-grade failure
(e.g. a reply that solves the problem perfectly but opens with policy language —
a 2 on empathy, and WHY in one line).
