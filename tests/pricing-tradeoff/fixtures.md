# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/pricing-tradeoff/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Should we price the AI add-on per seat or usage-based?"
T2. "Structure the pricing options for our new teams tier"
T3. "We're debating freemium vs free trial — lay out the tradeoffs"
T4. "/pm how should we price the API product?" (via orchestrator)
T5. "Walk me through the pricing tradeoffs of bundling vs unbundling the add-on"

SHOULD NOT FIRE:
N1. "What should we charge — give me a number"      (the skill structures options with mechanisms; it refuses to conjure a price point from nothing)
N2. "Is this niche big enough at $99/practice?"     (opportunity-sizer)
N3. "Reality-check the roadmap against margins"     (roadmap-reality-check)
N4. "What is value-based pricing?"                  (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Pricing question: our AI meeting-summary add-on. Base product $30/seat/mo, gross
margin 80%. Add-on LLM cost ~$4/seat/mo at median usage, but heavy users (top 10%)
cost ~$15/seat/mo. Sales wants 'included free to drive upgrades'; finance wants
+$10/seat. Mid-market B2B, ~15,000 paid seats."

EXPECTED OUTPUT PROPERTIES:
1. THE MARGIN-MECHANISM GATE: every option carries a stated margin mechanism — how
   the money works: what the price covers, what absorbs the cost, and the margin
   consequence derived from input numbers. A NAKED PRICE POINT (an option with a
   number but no mechanism) = gate failure.
2. Required option set (at minimum three structures, not three numbers):
   - included-in-base (sales' ask): mechanism must show base GM 80% → ~67% at median
     [$4 on $30] and the tail risk (top-10% users at $15 ≈ half the seat price),
     and name what would have to be true (upgrade lift covering margin give-up).
   - flat add-on (+$10, finance's ask): mechanism: $10 − $4 median = ~$6 margin/seat,
     negative-margin tail (−$5 on heavy users), adoption friction named.
   - usage-based / tiered cap: mechanism: cost scales with the cost driver; heavy
     tail priced instead of absorbed; complexity cost named.
3. Every dollar figure traces to input or is [ESTIMATE]-labeled with derivation.
   No invented benchmarks ("industry standard is 20% attach").
4. Each option carries: margin mechanism, who it selects for/against, and its
   failure mode. Tradeoffs stated symmetrically — no strawman option.
5. If a recommendation is given, it names the deciding tradeoff AND the data needed
   to confirm (e.g. actual usage distribution beyond the top-10% figure).

PLANTED-FAILURE CASE:
A draft option "Charge $12/seat — feels right for mid-market and undercuts nothing"
(a naked price point: number, vibes, no mechanism) MUST be caught by the
margin-mechanism gate and either gain its mechanism from input math or be cut.
