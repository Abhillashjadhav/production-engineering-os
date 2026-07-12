---
name: eval-vs-abtest-router
description: "Iterate-stage skill: routes a product question to offline eval or A/B test — by first classifying it as output-quality (a property of the artifact, judgeable against criteria) or user-behavior (a property of humans, observable only in the field). Use when the measurement tool is in question — 'eval this or A/B test it?', 'how do we know the new prompt is better', 'is an A/B test the right tool here', 'how do we measure if it worked' — or when /pm routes such a request here. Do NOT use to build the eval (eval-engine), to design the experiment itself, for build/kill decisions (ai-feature-go-no-go), or for eval-vs-experiment definitions."
argument-hint: "<the question(s) to route + any traffic/volume numbers you have>"
---

# Eval vs A/B Test Router

Two tools, two kinds of questions. Evals judge artifacts; experiments observe humans. Route by what the question is *about* — pointing the wrong tool at a question measures something, just not the answer.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Classification before tool:** every routing states the question's kind first — `OUTPUT-QUALITY` (artifact property, judgeable offline against criteria) or `USER-BEHAVIOR` (human reaction, field-only) — then the tool. A tool verdict with no classification fails. Compound questions are split, each half classified and routed, with sequencing.
- **G2 — The misuse statement:** every routing says what the rejected tool would actually measure if used here ("an A/B test on accuracy measures error tolerance, not correctness") — not generic cons. The mismatch is the router's evidence.
- **G3 — Field-honest arithmetic:** sample/timeline claims use provided volume numbers with the math shown, or say "depends on traffic" — no invented MDEs, significance thresholds, or user counts. Where both tools apply, the eval-first rule is stated: variants that fail quality gates don't enter experiments.

## Steps

1. **Extract the actual question(s).** "Is it better?" hides several questions; write each one out. Compound asks ("punchier, and will users like it?") get split now.
2. **Classify each:** does answering require judging the artifact against a definition of good (output-quality), or observing what humans do differently (user-behavior)? The test: could a competent judge with the criteria answer it from outputs alone? Yes → output-quality. Needs live users reacting → behavior.
3. **Route and evidence:** output-quality → eval (golden set + judge; point to eval-engine); user-behavior → A/B test (metric, unit, and the eval-first entry criterion). For each, write the misuse statement for the rejected tool — the concrete wrong thing it would measure here.
4. **Sequence compound questions:** quality first, behavior second — the punchier variant passes its gates before any user sees it; the preference test then measures preference, not tolerance of regressions.
5. **Reality-check the field half:** with provided volume, show the rough arithmetic (400 users × expected effect → weeks, labeled estimate); without it, say what number is needed. Never fake statistical precision.
6. **Gate pass.** Every routing classified-then-routed (G1), misuse statements concrete (G2), arithmetic provided-or-honest and sequencing present (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
ROUTING: 3 questions
Q1 "new prompt more accurate?" — OUTPUT-QUALITY → EVAL
   Misuse: an A/B test here measures whether users notice/tolerate errors, not
   whether summaries are correct — users don't label accuracy at read time.
   Next: golden set + judge (eval-engine); regression-gatekeeper before ship.
Q2 "do AI drafts raise reply rate?" — USER-BEHAVIOR → A/B TEST
   Misuse: no offline judge produces a reply rate. Entry criterion: the drafts
   variant passes its quality gates first (eval-first rule).
   Field math: [with stated traffic: rough weeks-to-signal, labeled estimate · else: "needs traffic number"]
Q3 "summaries feel generic — punchier?" — COMPOUND → SPLIT
   Q3a punchier-is-better-writing — OUTPUT-QUALITY → EVAL (anchor 'punchy' first)
   Q3b users-prefer-punchier — USER-BEHAVIOR → A/B, after Q3a gates pass.
GATE CHECK: G1 pass (3/3 classified first) · G2 pass · G3 pass
```

## Hard rules

1. No tool verdict without the classification stated first. The classification IS the routing; the tool is its consequence.
2. Misuse statements are specific to this question — what the wrong tool would actually return, and why that's not the answer.
3. Gate-failing variants never enter experiments. An A/B test is not a quality check with users as unpaid judges.
4. Statistical claims are computed from provided numbers or absent. "You'll have significance in two weeks" without traffic data is fiction.

## Limitations

- The router decides the tool; designing the eval (eval-engine) or the experiment (metrics, assignment, guardrail metrics) is downstream work it points to.
- Some behavior questions have quality proxies (judge-scored engagement-likeness) — proxies are labeled proxies and never substitute for the field answer on high-stakes calls.
- The output-quality/user-behavior line blurs for perceived-quality questions (tone, trust); the router splits these compounds rather than forcing one side.
- Field arithmetic here is order-of-magnitude planning, not experiment-design statistics.
