---
name: guardrail-designer
description: "Iterate-stage skill: designs error, hallucination, and edge-case guardrails for a workflow — every guardrail naming the specific failure it prevents and the trigger condition that fires it. Use when a workflow needs hardening — 'design guardrails for this workflow', 'what can go wrong here and what stops it', 'harden this before we scale', 'where are we exposed' — or when /pm routes such a request here. Do NOT use for autonomous-loop design (loop-designer), for offline eval construction (eval-engine), for production drift monitoring (drift-monitor-designer), or for guardrail definitions."
argument-hint: "<the workflow steps + volumes + any incidents that already happened>"
---

# Guardrail Designer

A guardrail is a named failure plus the condition that fires the defense. "Add validation" is a wish; "block any balance in the draft that isn't in this ticket's record" is a guardrail.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Named failure + trigger, every guardrail:** each guardrail states the specific failure it prevents (an incident or a labeled class risk) and its trigger condition — the observable check that fires it. Failure-less ("add validation") or trigger-less ("prevent hallucinations") guardrails fail.
- **G2 — Placed and costed:** every guardrail sits at a named point in the flow (pre-draft / post-draft / pre-send / post-send) with its action on trigger (block / flag / route / degrade) and its cost (latency, false-positive friction, build effort) stated.
- **G3 — Layered honestly:** mechanical checks run before human review; the human layer is treated as a failure surface with its own guardrail (fatigue, volume), never as the universal catch-all. Known incidents drive the top of the list; invented incidents and imported compliance requirements fail.

## Steps

1. **Walk the flow as an attacker of its own outputs.** Per step: what enters, what the model does with it, what leaves, and how each can be wrong (wrong data in, wrong synthesis, wrong claim out, wrong human action).
2. **Rank the failure list:** actual incidents first (they're proven reachable), then class risks the flow's shape makes likely (invented commitments in any customer-facing generation), each labeled `incident` or `class risk`.
3. **Design the trigger per failure.** The trigger is a checkable condition, mechanical wherever possible: set membership (entities in draft ∈ ticket's record), version match (cited policy ∈ current corpus), pattern screen (commitment-shaped phrases → tier up). A failure with no checkable trigger gets an honest "detectable only by sampling" note, not a fake trigger.
4. **Place, act, cost.** Position each guardrail in the flow; define the action (block, flag, route to senior queue, degrade to template); state what it costs — a guardrail whose false-positive rate would swamp the queue is redesigned now, not discovered in week two.
5. **Guard the guards.** The human review layer gets engineered like everything else: risk-tiered queues (money/legal drafts can't be one-click sent), volume ceilings, and sampling audits of approved drafts — "the agent will catch it" is the failure mode, not the defense.
6. **State residual risk and wire the loop:** what these guardrails don't catch, and the standing instruction that novel escapes go through failure-to-eval-capture and return as permanent cases. **Gate pass:** every guardrail named+triggered (G1), placed+costed (G2), layering honest (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
GUARDRAILS: AI support-reply workflow (400/mo · 2 known incidents)
1. Cross-record leak [incident] — TRIGGER: any account number/balance/name in draft
   ∉ this ticket's customer record → BLOCK + flag retrieval — placement: post-draft
   [mechanical] — cost: ~0 latency, low FP
2. Stale policy citation [incident] — TRIGGER: cited policy id/date ∉ current corpus
   → BLOCK with current-policy suggestion — post-draft [mechanical] — cost: corpus
   index upkeep
3. Invented commitments [class risk] — TRIGGER: commitment-shaped phrases (refund,
   deadline, guarantee) → ROUTE to senior queue, no one-click send — pre-send
   [pattern + human] — cost: senior-queue load, est. from phrase frequency [labeled]
4. Reviewer fatigue [class risk, stated 30+/day] — TRIGGER: money/legal-tier draft →
   cannot be sent unedited without explicit confirm; 5% sampling audit of approved
   drafts — pre-send/post-send — cost: friction on high-risk sends
RESIDUAL: novel failure shapes pass mechanical checks → escapes route to
failure-to-eval-capture and return as regression cases.
GATE CHECK: G1 pass (4/4 named+triggered) · G2 pass · G3 pass
```

## Hard rules

1. No guardrail without its named failure and checkable trigger. Vague protection language gets decomposed or cut.
2. Incidents outrank hypotheticals, and every failure carries its `incident`/`class risk` label — never dress a guess as history.
3. The human layer is a component with failure modes, not a warranty. Any design whose last line is "a person reviews everything" must also guard that person.
4. Every guardrail's cost is stated. A free guardrail claim means the cost wasn't found yet.

## Limitations

- Guardrails reduce reachable failures; they don't make the model correct — quality is the eval layer's job (eval-engine), and the two are complements.
- Trigger designs are specifications; implementing the checks (regexes, set lookups, queue routing) is engineering work this skill scopes but doesn't build.
- False-positive costs are estimates until measured; the design flags which triggers need a measurement week before hard enforcement.
- Coverage is bounded by the walked flow — steps the input didn't describe get no guardrails, and the output says which steps those are.
