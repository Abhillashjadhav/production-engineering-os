---
name: judge-calibration-auditor
description: "Iterate-stage skill: analyzes human labels vs LLM-judge verdicts and turns every disagreement into a classified calibration signal with a stated correction — never auto-resolved toward the judge. Use when a judge and humans diverge — 'our judge disagrees with human reviewers', 'human labels vs judge verdicts, what's drifting', 'the judge scores everything 4', 'disagreement analysis' — or when /pm routes such a request here. Do NOT use to design the judge (llm-as-judge-designer), to build the eval (eval-engine), to produce the human labels themselves, or for judge-bias knowledge questions."
argument-hint: "<paired data: per case, the human label and the judge verdict, plus the judged output or its gist>"
---

# Judge Calibration Auditor

Disagreement is the signal, not the noise. Each divergence gets diagnosed and corrected — and the correction is never "trust the judge".

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Never auto-resolved:** no disagreement is settled by presuming the judge correct — and none by presuming the human correct without analysis. Every disagreement gets a classification and a stated, concrete correction (rewritten anchor text, added exemplar, anti-drift instruction, or an escalation question). "The judge's read is defensible, accept it" fails the gate.
- **G2 — Systematic vs. noise separated:** disagreements sharing direction and pattern (n≥2) are systematic and drive anchor rewrites; singletons stay provisional (collect more) unless they show a clear rule-import. Rewriting anchors on one data point fails, as does dismissing a repeated pattern as noise.
- **G3 — Honest arithmetic, untouched labels:** agreement stats shown as they are (7/12 is 58%, per-dimension), no invented aggregate quality score, and human labels never edited — a suspect human label becomes a question to the criterion owner, not a correction.

## Steps

1. **Tabulate:** per case — human label, judge verdict, direction and size of gap, the output's relevant character (one line). Compute agreement overall and per criterion.
2. **Cluster the disagreements** by direction + pattern. Two same-direction gaps on the same output pattern are one systematic finding; five scattered singletons are five provisional notes.
3. **Diagnose each cluster** against the known failure classes: **anchor defect** (the rubric never taught this boundary — fix: rewrite the anchor with this very case as the exemplar), **judge bias** (verbosity reward, position, self-preference — fix: targeted anti-bias instruction + counter-exemplar), **rule import** (judge grading an unlisted criterion — fix: anti-drift reminder + exemplar legitimizing what it wrongly penalized), **criterion ambiguity** (both readings defensible — fix: escalate to the owner with both readings; ambiguity needs a definition, not calibration).
4. **Write the corrections concretely:** the new anchor text, the exemplar with verdict + reason, the added instruction line, or the escalation question — paste-ready for the judge prompt. "Improve the prompt" is not a correction.
5. **State what re-runs:** after corrections, the same paired set re-judged; expected movement named per correction (D1/D2 should flip to agreement; D4 waits on the owner). Corrections that don't move their cases get revisited, not defended.
6. **Gate pass.** Every disagreement classified + corrected (G1), clusters vs singletons handled per G2, stats honest and labels untouched (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
CALIBRATION AUDIT: empathy judge (12 pairs · agreement 7/12 = 58% · gate dimension 11/12)
SYSTEMATIC
S1. Cases #4, #7 — human 2 / judge 4, both "solves everything, zero acknowledgment"
    Class: anchor defect. Correction (paste-ready): 2-anchor := "complete solution
    with no acknowledgment of the customer's situation — e.g. [case #4 text]".
    Expected after fix: both flip to agreement.
PROVISIONAL / SINGLETONS
S2. #9 — judge rewards hedged length. Class: verbosity bias (n=1, known class →
    act): add anti-verbosity line + long-but-hollow fail exemplar.
S3. #12 — judge imported "professionalism". Class: rule import: anti-drift reminder
    + warmth-positive exemplar (terse-but-warm, scored 4, reason attached).
ESCALATIONS
E1. #11 (gate) — "I'll personally make sure" — commitment or reassurance? Both
    readings defensible → criterion owner must define; not calibratable as written.
RE-RUN: corrected prompt over the same 12 pairs; movement expected on #4,#7,#9,#12.
GATE CHECK: G1 pass (5/5 classified+corrected, 0 auto-resolved) · G2 pass · G3 pass
```

## Hard rules

1. The judge is never the tiebreaker in its own audit. Efficiency arguments for accepting judge verdicts are the failure mode, not a finding.
2. Corrections are paste-ready text, each tied to the cases that prove it and the movement expected of them.
3. Anchors get rewritten from real disagreement cases — the case that exposed the boundary becomes the exemplar that teaches it.
4. Human labels are input, not output. Doubts about a label become an escalation question, never an edit.

## Limitations

- The audit is as good as the label set: 12 pairs finds patterns, not rates — confidence language must scale with n, and the audit says when n is too small to act.
- Human labels carry human inconsistency; systematic human-side patterns are surfaced as escalations, but adjudicating them belongs to the criterion owner.
- Corrections are hypotheses until the re-run confirms movement; the re-run is part of the loop, not optional.
- Bias diagnoses name known classes (verbosity, position, rule import); a genuinely novel drift pattern gets described honestly as unclassified.
