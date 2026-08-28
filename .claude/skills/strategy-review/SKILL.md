---
name: strategy-review
description: "Strategy-stage skill: pressure-tests a strategy document — every weakness it raises must cite the specific line it attacks. Use when the user provides their own strategy doc, positioning memo, or plan and asks for it to be stress-tested — 'pressure-test this strategy', 'tear it apart before the board does', 'red-team this memo', 'what's weak in this one-pager' — or when /pm routes such a request here. Do NOT use to author a strategy from scratch (there must be a doc to attack), to review PRs (/pr-review), to analyze a competitor's strategy (competitor-teardown), or for knowledge questions about strategy frameworks."
argument-hint: "<paste the strategy doc / memo to pressure-test>"
---

# Strategy Review

A strategy doc in, a line-cited attack out. Criticism that can't point at a line is opinion, not review.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Line citation:** every weakness cites the specific line number(s) it attacks and quotes the attacked text. Criticism about something the doc never says is either converted to an explicitly labeled `GAP` (what's missing and why it matters) or cut — it may never masquerade as a line attack.
- **G2 — Repair path:** every weakness carries severity (fatal / serious / minor), the concrete failure mode it creates, and the question the author must answer to fix it. A complaint without a repair question fails.
- **G3 — Survivors named:** the review states which claims withstand attack and why. All-demolition output fails — it means the review graded harshness, not the strategy.

## Steps

1. **Number the doc.** Assign line/claim numbers (L1, L2, …) and echo them so the user can follow citations. No doc provided? Stop and ask — this skill attacks text, it doesn't write it.
2. **Attack each claim on four axes:**
   - **Evidence** — which numbers or assertions have no stated basis? (a "30% conversion" with no source is a target)
   - **Consistency** — which lines contradict each other? Cite both lines in the pair.
   - **Falsifiability** — which claims would every competitor also make ("easiest to use")? What observable fact would prove them?
   - **Mechanism** — where does the doc claim an effect (network effects, lock-in, viral growth) without the causal machinery that produces it?
3. **Hunt gaps.** What must be true for the strategy to work that the doc never addresses (channel, pricing consequence, competitor response)? Label these `GAP` — no fake line citations.
4. **Grade severity honestly.** Fatal = strategy fails if unanswered; serious = material risk, repairable; minor = weakens the doc, not the strategy. Don't inflate minors to look rigorous.
5. **Name survivors.** The strongest line(s) and what makes them defensible.
6. **Gate pass.** Check every weakness for a line citation or GAP label (G1), a severity + failure mode + repair question (G2), and that survivors are present (G3). Fix and re-run; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
STRATEGY REVIEW (doc: N lines)
FATAL
1. L3 "30% of Calendly's SMB churn" — naked conversion assumption
   Failure mode: the revenue model inherits an unsourced number
   Repair question: what observed migration behavior supports 30%?
SERIOUS
2. L2 vs L5 — single-player wedge, multiplayer defense: contradiction
   ...
GAPS (no line to cite — missing entirely)
- GTM: the doc never says how the migration tool reaches churners
SURVIVES ATTACK
- L6 (explicit non-goal) — falsifiable, sequenced, resourcing-honest
GATE CHECK: G1 pass (n/n cited or GAP-labeled) · G2 pass · G3 pass
```

## Hard rules

1. No free-floating criticism. Every weakness points at quoted text by line number, or is explicitly labeled GAP. This is the gate the skill exists for.
2. Never invent context to strengthen an attack — no "competitors are already doing X" or market facts from memory. Attacks stand on the doc's own text and logic; external claims the user didn't provide are flagged as questions, not asserted.
3. Contradictions cite both lines. One-sided contradiction claims fail the gate.
4. Severity inflation is a review defect: if nothing is fatal, say the strategy has no fatal flaw found — don't promote a serious to justify the exercise.

## Limitations

- The review attacks internal logic, evidence discipline, and stated mechanisms; it cannot validate market facts the doc asserts — it can only flag them as unsourced.
- Gap-hunting is bounded by what the reviewer knows to look for; an empty GAP section means none found, not none exist.
- Severity grades are structured judgments; the failure-mode line lets the reader re-grade.
- A strategy can pass every gate here and still lose — this reviews the document, not the market.
