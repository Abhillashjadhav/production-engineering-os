# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/opportunity-sizer/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Size the market for AI meeting-notes tools"
T2. "TAM/SAM/SOM for a compliance copilot for EU fintechs — here's what we know: ..."
T3. "How big is the opportunity if we launch in Brazil?"
T4. "/pm is this niche big enough to bother with?" (via orchestrator)
T5. "Build the market-size slide inputs for the board deck"

SHOULD NOT FIRE:
N1. "What does TAM stand for?"                      (knowledge question)
N2. "Map the assumptions behind this idea"          (assumption-mapper)
N3. "What's Salesforce's current market cap?"       (single fact lookup, not a sizing)
N4. "Forecast our Q3 revenue"                       (internal forecasting, not market sizing)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Size the opportunity for a scheduling add-on sold to US dental practices.
What we know: ~130,000 dental practices in the US (ADA 2024 figure I looked up).
Our pilot pricing is $99/practice/month. We can only serve practices using
cloud practice-management software — we don't know that share."

EXPECTED OUTPUT PROPERTIES:
1. NO NAKED FIGURES anywhere: every number carries either [SOURCE: <named source, as
   provided or fetched>] or [ESTIMATE: <derivation/assumption>]. One naked number = gate failure.
2. Provided facts tagged to their source: 130,000 practices → [SOURCE: ADA 2024, per user].
   $99/mo → [SOURCE: user's pilot pricing].
3. The unknown cloud-software share must surface as an explicit labeled assumption
   (e.g. [ESTIMATE: assumed 40–60% — no data provided; sensitivity shown]) — NOT a
   silently chosen single value.
4. Arithmetic must reconcile and nest: SOM ⊆ SAM ⊆ TAM. TAM math from the fixture:
   130,000 × $99 × 12 ≈ $154M/yr — shown as derivation, tagged, and rounded honestly.
5. Ranges over false precision: unknowns propagate to ranges in SAM/SOM, and the output
   states which single assumption moves the answer most.
6. The skill must NOT invent third-party market reports ("per Gartner, the market is
   $2.3B") that were not provided and not actually retrieved.

PLANTED-FAILURE CASE:
A draft containing "the US dental software market is $5B" with no source tag — plausible,
uncited, unprovided — MUST be caught by the no-naked-figures gate and either sourced
for real, converted to a labeled derivation, or cut.
