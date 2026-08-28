---
name: context-auditor
description: "Build-stage skill: scans a context file — CLAUDE.md, system prompt, assembled agent context — and reports findings tagged with one of the four context failure modes (poisoning, distraction, confusion, clash) plus the offending line. Use when an agent misbehaves and the context is suspect — 'audit my CLAUDE.md', 'scan this system prompt for context problems', 'agent gets worse as the file grows', 'run the four-failure-mode diagnostic' — or when /pm routes such a request here. Do NOT use to create memory/context files (pm-context-system), for token-budget questions with no content to audit, for knowledge questions about the failure modes, or for output-quality prompt tuning (prompt-optimizer-loop)."
argument-hint: "<paste the context file / CLAUDE.md / system prompt to audit>"
---

# Context Auditor

Four failure modes, line-level findings, no vibes. A finding without a mode tag and a line number is a feeling, not a diagnostic.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Tagged and located:** every finding carries exactly one mode tag from the four — `POISONING` · `DISTRACTION` · `CONFUSION` · `CLASH` — plus the offending line number(s). Untagged findings, lineless findings, or invented fifth modes fail the gate.
- **G2 — Flag, don't adjudicate:** conflicts of fact (two founding years, two prices) are flagged for the user to resolve. Declaring the "true" value from world knowledge is fabrication and fails the gate — the auditor sees the file, not the world.
- **G3 — Fix per finding:** every finding ships a concrete, line-referenced fix: cut / rewrite (with the rewrite) / resolve-with-user (with the question).

## The four modes

| Mode | What it is | Downstream behavior |
|---|---|---|
| POISONING | a false or contradicted fact sits in context | the model repeats it confidently |
| DISTRACTION | bulk content dwarfs the instructions | instructions get lost; model over-indexes on the bulk |
| CONFUSION | superfluous/irrelevant detail | degraded, meandering answers |
| CLASH | two instructions or facts conflict | nondeterministic behavior — the model picks one, varies by run |

## Steps

1. **Number the file.** Line numbers are the audit's coordinate system; echo enough structure that citations land.
2. **Sweep for CLASH first** — instruction-vs-instruction (formal vs casual), fact-vs-fact (price vs price). Cite both lines of every pair.
3. **Sweep for POISONING:** facts contradicted within the file, or marked stale by dates/context ("Note from March"). Flag which line is suspect and why; never pick the winner from outside knowledge.
4. **Sweep for DISTRACTION and CONFUSION:** measure bulk (a 400-line changelog against 8 lines of instructions is distraction by arithmetic); flag detail no task needs (confusion) — with the line ranges.
5. **Grade and prescribe.** Severity (critical = will corrupt output on common paths; warning = degrades quality) + downstream behavior + the fix. Order findings by severity.
6. **Gate pass.** Every finding tagged + lined (G1), no adjudicated facts (G2), every finding has its fix (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
CONTEXT AUDIT (file: 9 lines + 400-line paste)
CRITICAL
1. [CLASH] L2 vs L7 — "formal English" vs "casual, match user's tone"
   Behavior: tone varies by run. Fix: keep one; suggest L7, cut L2.
2. [POISONING] L3 vs L9 — founded "2019 Berlin" vs "2021 Munich spinoff"
   Behavior: repeats whichever it read last. Fix: resolve with user — which is true? (I can't know from the file.)
WARNING
3. [CLASH] L4 vs L5 — $12 vs $9 promo — Fix: resolve: is the promo live? Keep one price with a date.
4. [DISTRACTION] L8 — 400-line changelog vs 8 instruction lines — Fix: cut; link or summarize to ≤10 lines.
GATE CHECK: G1 pass (n/n tagged+lined) · G2 pass (0 adjudicated) · G3 pass (n/n fixes)
```

## Hard rules

1. Only the four modes exist. A real problem that fits none of them is reported outside the findings list as "out of taxonomy" — never force-tagged, never invented as a new mode.
2. Every finding cites its line(s). "The file is generally inconsistent" is banned output; find the lines or drop the claim.
3. Never resolve factual conflicts from world knowledge. The audit flags L3-vs-L9; the user knows which company they founded.
4. Bulk judgments show their arithmetic (400 lines vs 8) — "feels long" is not a finding.

## Limitations

- The audit is static analysis of one file; it can't see runtime behavior, retrieval-injected content, or the conversation that surrounds the context in production.
- Distraction/confusion thresholds are judgment guided by arithmetic, not hard limits — the line counts are shown so the reader can disagree.
- A file can pass clean and still underperform for non-context reasons (model choice, task design — other skills' territory).
- Facts consistent within the file but false in the world are invisible to this audit; it catches internal contradiction and staleness signals only.
