---
name: competitor-teardown
description: "Discovery-stage skill: turns material about a competitor's product — pricing pages, docs, changelogs, screenshots, customer reports — into a structured teardown where every claim is marked observed or inferred. Use when the user names a competitor product and asks for a teardown, competitive analysis, or comparison — 'tear down X', 'how does our Y compare to theirs', 'what is X doing with their pricing' — or when /pm routes such a request here. Do NOT use to write positioning or battlecards (Strategy stage), to scrape or collect the competitor data itself, for company-culture questions, or when no competitor material or product is identified — with nothing to observe it asks for material rather than inventing findings."
argument-hint: "<competitor product + whatever material you have: pricing page, docs, changelog, customer quotes>"
---

# Competitor Teardown

Material in, teardown out — with a bright line between what was seen and what is being guessed.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Every claim tagged:** each factual claim carries exactly one of `[OBSERVED: <source>]` or `[INFERRED: <basis>]`. An untagged claim fails the gate.
- **G2 — No invented facts:** every OBSERVED tag traces to material in the input (or material the skill actually fetched and quoted this session). Unknowns are written as "not determinable from input" — never filled with plausible numbers, features, or absences.
- **G3 — Inferences grounded and unchained:** every INFERRED tag states its basis from observed material; an inference may not be the sole basis for a further inference presented as a finding.

## Steps

1. **Inventory the material.** List what was provided (pricing page, changelog, N customer reports, screenshots) — this inventory is the universe OBSERVED tags may cite. No material and no fetchable source? Stop and ask for material.
2. **Extract observations.** Pull concrete facts: prices, tiers, features named, release dates, quoted customer language. Single-source reports (one churned customer, one review) keep their provenance visible — "one customer reports X" is the observation; "X is true of the product" is not.
3. **Draw inferences — separately.** Cadence → investment level, pricing structure → target segment, missing tier features → upsell strategy. Each with its stated basis. Mark confidence when the basis is thin.
4. **Structure the teardown:** positioning & pricing · product surface · momentum/cadence · weaknesses & complaints · what we still don't know. The unknowns section is mandatory — an empty one means the teardown is overclaiming.
5. **Gate pass.** Scan every sentence for untagged claims, verify each OBSERVED against the inventory, check each INFERRED for basis and chaining. Fix and re-run; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
TEARDOWN: <product> (material: <inventory>)
POSITIONING & PRICING
- Pro is $12/user/mo, unlimited calendars [OBSERVED: pricing page]
- Enterprise price not determinable from input
- Targets mid-market teams, not solo users [INFERRED: per-seat pricing + SSO gating]
...
WHAT WE STILL DON'T KNOW
- <unknown> — how to find out: <source>
GATE CHECK: G1 pass (n/n claims tagged) · G2 pass · G3 pass
```

## Hard rules

1. Never state a fact about the competitor that isn't in the inventoried material. Plausible ≠ observed — especially absence claims ("they have no API") which require observed evidence of absence, not failure to mention.
2. Never launder a single customer's complaint into a product-wide truth. Provenance ("one churned customer reports…") travels with the claim.
3. Never invent pricing. A missing price is "not determinable from input", full stop.
4. The "what we still don't know" section may never be empty — if it seems empty, the teardown is overclaiming somewhere; find it.

## Limitations

- The teardown is a snapshot of the provided material at its date; pricing pages and changelogs drift — re-verify before quoting in anything external.
- OBSERVED means observed in the input, not independently verified — a doctored screenshot passes G2; source-checking the user's material is the user's job.
- Inference quality depends on material breadth: a pricing page alone supports pricing inferences, not roadmap conclusions.
- This skill analyzes; it does not collect. Fetching competitor pages at scale, or anything against a site's terms, is out of scope.
