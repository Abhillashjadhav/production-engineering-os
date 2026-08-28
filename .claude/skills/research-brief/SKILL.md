---
name: research-brief
description: "Discovery-stage skill: turns an open product question into a structured research plan where every method is mapped to the decision it informs. Use when the user needs to plan research before acting — 'write a research plan for X', 'how should we figure out why Y happened', 'what research do we need before betting on Z', 'draft the research brief' — or when /pm routes such a request here. Do NOT use to synthesize research already run (interview-synthesizer / feedback-pattern-miner), to execute surveys or studies, for qual-vs-quant knowledge questions, or for web/market deep-research tasks."
argument-hint: "<the question + context: what you can access, and the decision hanging on the answer>"
---

# Research Brief

A question in, a decision-shaped research plan out. Methods exist to move decisions — any method that doesn't map to one gets cut.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — No orphan methods:** every proposed method maps to a named decision and states which answer would push the decision which way. A method with no mapping fails the gate.
- **G2 — No starved decisions:** every decision option has at least one method capable of ruling it in or out. An option no method can touch fails the gate.
- **G3 — No fabricated context:** the plan assumes only access, data, and users stated in the input (or explicitly flags each extra assumption as a prerequisite to confirm).

## Steps

1. **Extract the decision.** What will be done differently depending on the answer? If the input has a question but no decision, ask for the decision — research without a decision is a reading list. Write the decision options and the criteria ("we roll back if …").
2. **Decompose the question** into the 2–4 sub-questions the decision actually turns on (what changed, for whom, why, would fixing it work).
3. **Pick methods per sub-question,** cheapest-decisive first: existing analytics → targeted interviews/replays → surveys → experiments. For each: participants/data source, sample size with its basis (n=5 because pattern saturation; n=200 because ±7% at 95% — never a naked n), time/cost class, and the kill/confirm signal.
4. **Build the method→decision map.** One table, every method on a row, every row naming its decision and the push direction of each possible result. This map IS the deliverable's spine — everything else supports it.
5. **Sequence with exits.** Order by cost-of-information; add "stop early if" conditions (analytics alone proves a broken funnel step → skip the survey). State the total elapsed-time envelope.
6. **Gate pass.** Check every method for a mapping (G1), every decision option for coverage (G2), every assumed resource against the input (G3). Fix and re-run; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
DECISION: roll back / patch / keep the signup redesign
CRITERIA: roll back if the drop is structural to the new flow and patching exceeds
          rebuild cost; keep only if the drop is measurement or cohort noise

METHOD → DECISION MAP
| # | Method (source, n, basis) | Time | Informs | Result → push |
| 1 | Funnel analysis, new vs old flow (analytics) | days | all three | drop isolated to one step → patch; uniform → roll back; no real drop → keep |
| 2 | Interviews, 5 non-activated signups (email list; saturation basis) | 1 wk | roll back vs patch | confusion at step X → patch; value mismatch → roll back |
SEQUENCE: 1 → stop early if drop is measurement noise → 2 → …
PREREQS TO CONFIRM: <anything assumed beyond stated access, or "none">
GATE CHECK: G1 pass (n/n methods mapped) · G2 pass (all options covered) · G3 pass
```

## Hard rules

1. Every method maps to a decision or dies. "Good hygiene" research with no decision attached is cut, not kept.
2. Sample sizes carry their basis. Saturation, precision, or budget reality — stated; a bare "n=20" is not a plan.
3. Never assume research infrastructure the input didn't grant (user panels, budgets, data access). Missing access becomes a stated prerequisite, not a silent assumption.
4. The plan must say what happens on each result — a method whose every outcome leads to the same action is decoration and gets cut.

## Limitations

- The brief plans research; it does not run it or guarantee recruitment (5 non-activated users can be hard to book — the time envelope is an estimate, labeled as such).
- Method choice encodes standard practice, not statistical consultancy — power calculations beyond rough precision bounds need a proper analyst.
- Decision criteria come from the user's stated stakes; the skill sharpens them but can't supply risk tolerance the input doesn't contain.
- Sub-question decomposition is judgment; the map format makes it auditable, not infallible.
