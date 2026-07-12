---
name: failure-to-eval-capture
description: "Iterate-stage skill: converts a production failure into a scrubbed, permanent eval case — PII removed with the failure's trigger structure demonstrably preserved, wired into regression testing. Use when a bad output escaped to production — 'capture this failure as an eval case', 'turn this incident into a permanent regression test', 'encode this so it never ships again' — or when /pm routes such a request here. Do NOT use for batch curation of reviewed outputs (golden-dataset-builder), for root-causing why the model failed, for PII scrubbing with no eval encoding, or for regression-testing definitions."
argument-hint: "<the failure: the input (or its structure), the bad output, and what made it wrong>"
---

# Failure-to-Eval Capture

Every production failure becomes a permanent test — scrubbed of the people it happened to, but still carrying the trap it fell into. Scrub the identity, keep the mechanism.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Scrubbed:** all PII and identifying detail (names, emails, orgs, distinctive figures) replaced with stable placeholders; a scrub table shows placeholder classes, never relisting the original values; the unscrubbed failure never appears in the eval artifact.
- **G2 — Pattern demonstrably preserved:** the case states the failure mechanism and shows that the scrubbed input retains its trigger structure — an explicit preservation argument ("mechanism: entity-invention from org-name context; scrubbed input keeps org-as-topic + attendee-owned action item"). Over-scrubbing that deletes the trigger fails this half as hard as leaking PII fails the other.
- **G3 — Mechanically assertable:** the expected-behavior assertion is checkable without a judge wherever possible (every attendee in output ∈ input attendee list); the case carries id, failure class, provenance (date/ticket, never customer identity), and its regression wiring.

## Steps

1. **Name the mechanism first.** What made the output wrong — not "bad summary" but "invented an entity from an org name mentioned as topic, then reassigned an action item to it". The scrub is designed around protecting this mechanism; naming it first is what makes G2 checkable.
2. **Scrub against the mechanism.** Replace identities with stable placeholders (Person-A, Company-X, Bank-Y, [amount], [date]) while preserving every element the mechanism needs: entity roles, structural relationships, the tempting trap. Produce the scrub table by class.
3. **Prove preservation.** Write the argument: mechanism → trigger elements → each present in the scrubbed input. If any trigger element had to be scrubbed away (the PII *was* the trigger), say so and design the closest placeholder-based equivalent, labeled as a reconstruction.
4. **Encode the case:** id · scrubbed input · expected-behavior assertion (mechanical where possible; judge-checked with a stated check otherwise) · failure-class label · provenance.
5. **Wire it in:** the case joins the golden set (as a fail-class case with the incident as its human verdict + reason) and regression-gatekeeper's pre-ship run. Optionally add ONE same-mechanism variant, explicitly labeled `SYNTHETIC-VARIANT` — never disguised as the incident.
6. **Gate pass.** Scrub table complete + no original values (G1), preservation argument holds against the named mechanism (G2), assertion runnable + wiring stated (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
EVAL CASE F-4521 (from production incident, scrubbed)
MECHANISM: entity-invention — an org named as topic, no person from that org present,
model invents an attendee from the org name and reassigns an owned action item.
SCRUB TABLE: person names → Person-A/B · email → person-a@company-x.example ·
org → Bank-Y · amounts → [amount]
SCRUBBED INPUT: "Person-A and Person-B discussed the Bank-Y integration. Person-B
agreed to draft the API contract by [date]. Person-A raised the budget overrun of [amount]."
PRESERVATION: trigger structure intact — Bank-Y appears as topic with no Bank-Y
person present; action item owned by Person-B. A model with the defect would still
invent a Bank-Y attendee.
ASSERTION [mechanical]: every attendee/owner in output ∈ {Person-A, Person-B};
action-item owner == Person-B.
WIRING: golden set (fail class: entity-invention) + regression-gatekeeper pre-ship run.
VARIANT (SYNTHETIC-VARIANT, same mechanism): topic org = Vendor-Z, same assertion.
GATE CHECK: G1 pass (0 original values) · G2 pass (argument shown) · G3 pass
```

## Hard rules

1. Both scrub failures are failures: leaked PII and a deleted trigger. The gate has two halves and the preservation argument is mandatory evidence for the second.
2. The scrub table lists classes and placeholders — it never becomes a lookup table back to the original values.
3. Assertions are mechanical wherever the failure allows; a judge-checked assertion carries its stated check. "Output should be better" is not an assertion.
4. Synthetic variants are labeled, singular, and same-mechanism. The incident's evidentiary weight belongs to the incident alone.

## Limitations

- Scrubbing here is pattern-based diligence, not a compliance certification — regulated data (health, minors, financial identifiers) should also pass the org's official process, and the skill says so when it detects those classes.
- One case tests one mechanism; a failure with multiple mechanisms becomes multiple cases, not one blurry one.
- Preservation arguments are design-time reasoning; the true test is the regression run reproducing the failure on the defective model version when available.
- Capture prevents recurrence; it does not root-cause. Why the model had the defect is engineering work this case only evidences.
