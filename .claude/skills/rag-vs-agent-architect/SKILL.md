---
name: rag-vs-agent-architect
description: "Build-stage skill: matches a problem to an AI architecture — RAG, tool-calling, agent, or hybrid — and states the failure mode of every rejected option, not just the benefits of the chosen one. Use when the user is choosing an AI architecture — 'RAG or agent for this', 'do we need an agent or is retrieval enough', 'design the AI architecture for X' — or when /pm routes such a request here. Do NOT use for component selection inside a chosen architecture (vector DBs, frameworks), for feature go/no-go calls (ai-feature-go-no-go), for build/buy decisions (build-buy-partner), or for definitions of RAG or agents."
argument-hint: "<the problem: what's asked, where answers/actions live, stakes, volume, latency budget>"
---

# RAG vs Agent Architect

Architecture follows problem shape. The recommendation isn't credible until it says how each rejected option would fail *here* — and how the chosen one fails too.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Rejected failure modes stated:** every rejected architecture gets its failure mode for THIS problem — what breaks, wastes, or risks given the stated shape. Generic cons ("agents are complex") and benefits-only recommendations fail the gate.
- **G2 — Chosen option's failure mode + mitigation:** the recommended architecture carries its own dominant failure mode and the concrete mitigation. An architecture presented as failure-free fails.
- **G3 — Shape-derived, input-only:** the recommendation cites the problem properties it turns on, quoted from the input (actions or answer-only, corpus dynamics, stakes, volume, latency). No invented constraints, budgets, or compliance rules.

## The shape rubric

| Property | Pulls toward |
|---|---|
| Answer-only, no actions | RAG |
| Known, enumerable operations (lookup, file, update) | tool-calling |
| Open-ended multi-step work, plan varies per request | agent |
| Distinct sub-problems with different shapes | hybrid (composed, not defaulted) |
| Static/versioned corpus | RAG index |
| Live/system-of-record data | tools over retrieval |
| High stakes per answer | fewer moving parts + human/citation checks |
| Tight latency budget | fewer hops — agents pay per step |

## Steps

1. **Extract the shape:** what's asked, where truth lives (documents vs live systems), whether anything must be *done*, error stakes, volume, latency budget. Missing load-bearing properties → ask; don't assume.
2. **Map shape → candidates** with the rubric. Most problems resolve to the simplest architecture that covers the shape — capability beyond the shape is cost and failure surface, not headroom.
3. **Write the rejection ledger.** For each non-chosen architecture: the specific failure mode here ("agent loops can take actions; this problem forbids actions" beats "overkill"). This ledger is the deliverable's spine.
4. **Confess the chosen option's failure mode** and mitigate it concretely (RAG → stale index → reindex on quarterly policy updates; retrieval miss → cite-or-escalate rule, never free-generation fallback).
5. **Set the revisit trigger:** the property change that flips the call ("the moment the assistant must file the request, answer-only is gone — re-run"). Architecture calls expire when the shape changes; say when.
6. **Gate pass.** Every rejected option has its local failure mode (G1), the chosen one has its own + mitigation (G2), every cited property traces to input (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
ARCHITECTURE CALL: HR policy Q&A in Slack
SHAPE (from input): answer-only, no actions · 40 PDFs, quarterly updates · survivable
errors with HR review · 200 q/wk · <10s
RECOMMENDED: RAG — single-hop retrieval over an indexed, slowly-changing corpus matches
every stated property.
REJECTED
- agent: multi-step planning adds latency, cost, and failure surface to a single-hop
  lookup — and agents can act, which this problem forbids.
- tool-calling: no live systems to call; policies live in documents, not APIs.
- hybrid: composition buys nothing at one shape and 200 q/wk; pure complexity add.
CHOSEN OPTION'S FAILURE MODE: stale index after quarterly policy updates → reindex on
update webhook; retrieval miss → answer must cite the policy passage or escalate to HR.
REVISIT WHEN: the assistant must FILE anything (carry-over requests) — answer-only dies.
GATE CHECK: G1 pass (3/3 rejections localized) · G2 pass · G3 pass
```

## Hard rules

1. No recommendation without the rejection ledger. If you can't say how the alternatives fail here, you haven't understood the problem shape.
2. The chosen architecture confesses its failure mode. "It just works" is marketing, not architecture.
3. Simplest-that-covers-the-shape wins ties. The burden of proof is on the more capable architecture, not the simpler one.
4. Never invent problem properties. Constraints the input didn't state are questions, not assumptions.

## Limitations

- The call is design-time reasoning from stated shape; a spike or prototype (prototype-first-workflow) validates it against reality.
- The rubric covers the common four; novel shapes (multi-agent, fine-tuning-first) are flagged as out of rubric rather than force-fitted.
- Cost comparisons are structural (hops, steps) not priced — unit-economics-stress-test owns the numbers.
- Shape properties drift; the revisit trigger names the known flip, not every possible one.
