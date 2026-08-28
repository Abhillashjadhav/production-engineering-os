---
name: eval-engine
description: "Iterate-stage skill: turns a spec into the complete runnable verification layer — binary gates, anchored rubric, paste-ready judge prompt, and harness instructions — in one pass. Use when a feature needs its full eval built — 'create an eval for this spec', 'build the verification layer', 'spec to eval harness', 'turn this PRD into something we can run outputs through' — or when /pm routes such a request here. Do NOT use for the gates+rubric design artifact alone (prd-to-eval), for judge prompts over existing criteria (llm-as-judge-designer), for executing an eval over outputs, or for eval definitions."
argument-hint: "<the spec + any compliance-critical requirements + example outputs if you have them>"
---

# Eval Engine

Spec in, a runnable verification layer out: gates, rubric, judge prompt, harness — with the one law enforced throughout: disqualifiers gate, tradeables score, never mixed.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Never mixed:** every requirement lands as either a binary gate (disqualifier — fabrication, missing required elements, compliance misses) or a scored rubric dimension (tradeable — clarity, economy, tone). A disqualifier with a 1-5 score or a taste-call as a gate fails. Execution order stated in the deliverable: gates first, any failure = automatic fail, never averaged.
- **G2 — Everything operational:** every gate has a yes/no check procedure tagged `mechanical` or `judge`; every rubric dimension has concrete 1- and 5-anchors; the judge prompt embeds them and demands quoted evidence; the harness instructions say who runs what, in what order, and what triggers recalibration.
- **G3 — Spec-traced:** every gate and dimension cites its spec phrase. Missing-but-obvious requirements are proposed as spec additions, never silently added.

## Steps

1. **Harvest and sort.** Split compound requirements; run the ship-it test on each (*fails this, aces everything else — ship?* No → gate; tradeable → rubric). Compliance-critical items ("must not miss X") always gate, with a seeded golden case as their check.
2. **Write the gates (3–6):** name · binary check procedure · mechanical/judge tag · why-disqualifying. Vague disqualifiers get reformulated to checkable form ("no invented violations" → "every flagged rule exists verbatim in the policy doc").
3. **Write the rubric (3–6):** name · concrete 1-anchor · 5-anchor · spec phrase. Anchors describe real output character, not adjectives.
4. **Build the judge prompt:** paste-ready; embeds gates, anchors, and the required output shape (per-gate pass/fail with quoted evidence, per-dimension score with the sentence that earned it); forbids the judge from averaging gates or inventing criteria.
5. **Write the harness instructions:** case format · gates-first run order · human spot-check policy (every gate failure + N random passes) · recalibration trigger (human-vs-judge gap ≥2 points → route to judge-calibration-auditor, rewrite the anchor not the verdict) · where new failures enter (failure-to-eval-capture).
6. **Gate pass.** Re-run the sort check (G1), scan every artifact for operational completeness (G2), trace every row to spec (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
EVAL: expense-report auditor (spec: 6 requirements → 3 gates · 3 dimensions)
GATES (binary — any failure = automatic fail; never averaged)
G1. No invented violations — every flagged rule exists verbatim in policy doc
    [mechanical] — spec: "never invent a violation" — why: fabricated compliance flags are unshippable
G2. Rule citation present per flag [mechanical] — spec: "must cite the policy rule"
G3. Alcohol-on-client-dinner catch — seeded golden case must flag [mechanical] — spec: compliance-critical
RUBRIC (1-5, scored only when all gates pass)
R1. Plain-language clarity — 1: quotes policy verbatim with no translation · 5: one-sentence
    plain explanation a submitter acts on — spec: "explain in plain language"
R2/R3. …
JUDGE PROMPT: [paste-ready block embedding the above, structured verdict + quoted evidence]
HARNESS: cases as {input, expected-gate-results}; run gates → rubric; human spot-check:
all gate-fails + 5 random passes/batch; recalibrate when human-judge gap ≥2 (fix the
anchor, not the verdict); new production failures → failure-to-eval-capture.
GATE CHECK: G1 pass (0 mixed) · G2 pass (all operational) · G3 pass (all spec-traced)
```

## Hard rules

1. Gates and scores never mix — the root eval failure this skill exists to prevent. When sorting is genuinely arguable, sort by stakes and flag the judgment.
2. Every check must be runnable as written: a gate without a procedure or an anchor that fits any product gets rewritten, not shipped.
3. Nothing enters the eval that isn't in the spec; gaps in the spec are proposed back, never patched silently.
4. The judge is never the last word on its own drift — the harness always includes the human spot-check and the recalibration trigger.

## Limitations

- The layer is designed, not executed — running cases, wiring CI, and collecting judge outputs is downstream work the harness instructions specify.
- Judge-tagged gates inherit judge fallibility; calibration (judge-calibration-auditor) is part of the system, not optional polish.
- Anchors calibrate; they don't eliminate drift — the ≥2-gap rule catches what they miss.
- A spec that's wrong produces a faithful eval of the wrong thing; the spec-trace makes that auditable, not impossible.
