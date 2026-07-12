---
name: prd-to-eval
description: "Build-stage skill: turns a PRD or feature spec into a verification layer — binary quality gates for disqualifiers plus an anchored 1-5 rubric for tradeable qualities, with the two never mixed. Use when the user needs to define and test 'good' for a feature — 'turn this PRD into an eval', 'define good for our AI summarizer', 'build quality gates and a judge rubric', 'how do we test whether this works' — or when /pm routes a spec-bearing eval-design request here. Do NOT use to generate artifacts against frozen criteria (builder-validator), to execute an eval over outputs, for gate-vs-rubric knowledge questions, or for build/kill decisions (ai-feature-go-no-go)."
argument-hint: "<paste the PRD / spec to build the eval from>"
---

# PRD → Eval

Disqualifiers become binary gates; tradeable qualities become anchored scores. Mixing the two — averaging a gate, or scoring fabrication 3/5 — is the root failure of most evals, and the one thing this skill refuses to do.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Correct sorting:** every requirement lands on the right side of the line. Disqualifiers (fabrication, missing required fields, safety violations) are binary gates — partial credit on them is meaningless. Tradeable qualities (concision, tone, naturalness) are rubric dimensions. A scored disqualifier or a gated taste-call fails.
- **G2 — Gates binary-testable:** every gate states a yes/no check procedure and is marked `mechanical` (string/count/regex-checkable) or `judge` (needs an LLM/human applying the stated check). A gate whose check can't be written as a definite procedure is reformulated or demoted to the rubric.
- **G3 — Rubric anchored:** every dimension has concrete 1-anchor and 5-anchor descriptions (what a 1 actually looks like, what a 5 actually looks like). "Poor…excellent" scales fail. Every gate and dimension traces to a spec line — no invented requirements.

## Steps

1. **Harvest requirements** from the spec, keeping the source phrase for traceability. Split compound requirements ("accurate and concise" is two).
2. **Sort by the one question:** *if an output fails this and aces everything else, do we ship it?* No → gate. Depends/tradeable → rubric. When genuinely arguable (e.g. tone for a legal product), sort it as the spec's stakes imply and flag the judgment.
3. **Write the gates (3–6):** name · the binary check procedure · mechanical-or-judge · why it's disqualifying. Reformulate vague disqualifiers into checkable form ("no invented amounts" → "every amount in the summary appears verbatim in the source ticket").
4. **Write the rubric (3–7 dimensions):** name · 1-anchor · 5-anchor · which spec phrase it serves. Anchors are examples of output character, not adjectives.
5. **State the execution order:** gates first, in code or checklist; any gate failure = automatic fail, rubric unscored or advisory only. Gates never average into the score — write this rule into the deliverable itself.
6. **Gate pass.** Re-sort check (no scored disqualifiers, no gated taste-calls), every gate procedural, every dimension anchored, every row spec-traced. Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
EVAL for: AI ticket summarizer (spec: 6 requirements harvested)
GATES (binary — any failure = automatic fail; never averaged)
G1. No invented order numbers/amounts — check: every number in summary appears verbatim
    in ticket [mechanical] — why gate: fabrication in a support flow is unshippable
G2. Ticket status present — check: status field non-empty and one of the enum [mechanical]
G3. Legal-threat escalation — check: ticket mentions legal action → summary carries
    ESCALATE flag [judge, stated check] — why gate: safety/compliance
RUBRIC (1-5, scored only if all gates pass)
R1. Concision — 1: restates the ticket at similar length · 5: ≤3 sentences, no redundancy [spec: "concise"]
R2. Brand tone — 1: robotic or off-register · 5: indistinguishable from our best agent [spec: "tone"]
GATE CHECK: G1 pass (0 scored disqualifiers) · G2 pass (3/3 procedural) · G3 pass (2/2 anchored, all traced)
```

## Hard rules

1. A disqualifier never gets a score, and a taste-call never gets a gate. When in doubt, run the ship-it question from Step 2 — it has an answer.
2. Every gate ships with its check procedure. "Must be accurate" is a wish; "every number verbatim in source" is a gate.
3. Anchors are concrete descriptions of real output character. If the 1 and 5 anchors could describe any product, rewrite them.
4. Nothing enters the eval that isn't in the spec. Missing-but-obvious requirements (the spec forgot safety) are proposed to the user as spec additions, never silently added to the eval.

## Limitations

- The eval is a design artifact — running it (harness, judge calls, scoring pipelines) is downstream work this skill specifies but doesn't execute.
- Judge-marked gates depend on the judge honoring the stated check; calibrate against a few human-graded cases before trusting at scale.
- Anchors calibrate a judge but don't eliminate scoring drift; disagreement ≥2 points between human and judge means rewrite the anchor, not the verdict.
- Sorting borderline requirements is a stakes judgment — flagged in the output so the reader can re-sort with context the spec lacks.
