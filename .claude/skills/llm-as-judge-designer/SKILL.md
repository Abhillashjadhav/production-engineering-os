---
name: llm-as-judge-designer
description: "Iterate-stage skill: turns existing eval criteria into an LLM judge prompt with anchors and few-shot calibration cases — every rubric point carrying both a pass and a fail exemplar. Use when criteria exist and the judge needs building — 'write the judge prompt for these criteria', 'turn this rubric into an LLM judge', 'judge prompt plus calibration cases' — or when /pm routes such a request here. Do NOT use to build the whole eval from a spec (eval-engine), to audit an existing judge against human labels (judge-calibration-auditor), to execute scoring over outputs, or for judge-reliability knowledge questions."
argument-hint: "<the eval criteria (gates + rubric dimensions) + the domain the outputs come from>"
---

# LLM-as-Judge Designer

Criteria in, a calibrated judge out. The calibration is the exemplars: a judge that has never seen a failure will never find one.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Pass AND fail exemplar per criterion:** every criterion — gates and rubric dimensions alike — ships with at least one concrete pass exemplar and one concrete fail exemplar, written as short realistic outputs, each with its verdict and a one-line reason. Rubric fail exemplars must include a mid-grade failure (a 2–3), not just a strawman 1 — judges drift in the middle. Only-pass, only-fail, or adjective anchors ("1 = not empathetic") fail the gate.
- **G2 — Anti-drift instructions present:** the prompt forbids grading anything beyond the listed criteria, forbids scoring gates, requires quoted evidence per verdict, and resolves score ties downward with both candidate sentences cited. Calibration cases appear in mixed pass/fail order with an order-independence instruction.
- **G3 — Domain-native exemplars:** exemplars come from the criteria's actual domain and read realistic. Imported or cartoonish examples fail — a judge calibrated on strawmen grades strawmen.

## Steps

1. **Take the criteria as given.** This skill doesn't redesign them — a criterion that can't be exemplified (nobody can write what a failure looks like) is returned to the author as unjudgeable, which is a finding, not a workaround.
2. **Write the exemplar set:** per criterion, one realistic pass and one realistic fail (+ the mid-grade fail for rubric dimensions), each with verdict + one-line reason. The reason is what teaches the judge the boundary — "a 2: solves the problem but opens with policy language" draws a line; "bad empathy" doesn't.
3. **Assemble the prompt:** role framing · criteria verbatim (gates marked pass/fail-only) · calibration cases in mixed order · required output shape (per-criterion verdict/score + quoted evidence from the graded output) · the anti-drift block from G2.
4. **Dry-run mentally against the exemplars themselves:** the assembled prompt must reproduce every exemplar's own verdict. An exemplar the prompt's rules can't reproduce means the rules and the exemplars disagree — fix before shipping.
5. **State the handoff:** the prompt is v1; after ~20 real judgments, run human labels through judge-calibration-auditor; anchor rewrites (not verdict overrides) are the expected maintenance.
6. **Gate pass.** Count exemplars per criterion (G1), check the anti-drift block and ordering (G2), read every exemplar for domain realism (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
JUDGE: support-reply evaluator (3 criteria: 1 gate, 2 rubric)
CALIBRATION SET
C2 empathy (1-5):
  PASS (5): "That's three weeks of back-and-forth — I'd be frustrated too. Here's
  what I've done: …" — why: names the situation before solving.
  FAIL (2, mid-grade): "As per our policy, refunds process in 5-7 days. Your case
  has been resolved." — why: complete solution, zero acknowledgment; NOT a 1 (it
  isn't hostile), which is exactly why it's the calibrating case.
[…all criteria, mixed order in the prompt…]
JUDGE PROMPT
[paste-ready block: role · criteria verbatim · calibration cases · output shape
{criterion: verdict/score, evidence: "<quoted sentence>"} · anti-drift: grade only
listed criteria; gates never scored; tie → cite both sentences, take the lower;
verdicts must not depend on case order]
HANDOFF: after ~20 judgments, human-label comparison via judge-calibration-auditor.
GATE CHECK: G1 pass (n/n criteria, pass+fail each, mid-grade fails present) · G2 pass · G3 pass
```

## Hard rules

1. No criterion without both exemplars. The fail exemplar is the more valuable half — write it first.
2. Exemplars are outputs, not descriptions of outputs. "A reply that lacks empathy" teaches nothing; the actual policy-language reply does.
3. Never invent domain facts inside exemplars that would themselves fail the gates being judged (an exemplar support reply must not contain a fabricated refund commitment — unless it's the fail exemplar for exactly that gate, labeled as such).
4. The judge is never final: the handoff to calibration is part of the deliverable, and the prompt itself must not claim authority the calibration loop hasn't earned.

## Limitations

- Exemplar quality bounds judge quality; this skill writes plausible domain exemplars, but real production examples (golden-dataset-builder) beat synthetic ones and should replace them over time.
- Few-shot calibration reduces drift; it doesn't eliminate position, verbosity, or self-preference biases — the calibration audit is where those surface.
- One judge prompt per criteria set; materially changed criteria mean a new judge, not a patched one.
- Token cost scales with calibration cases; very large rubrics may need split judges, flagged when the set exceeds ~7 criteria.
