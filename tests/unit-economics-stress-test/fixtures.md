# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/unit-economics-stress-test/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Stress-test the token economics of AI email drafts"
T2. "What does this feature cost per user at 1k, 50k, 1M users?"
T3. "Will the copilot's inference cost eat our margin at scale?"
T4. "/pm run the unit economics on the summarizer before we commit" (via orchestrator)
T5. "Per-user cost model for the AI add-on, three scale points"

SHOULD FIRE-AND-ASK (missing assumptions): "What will AI replies cost us?" with no
token counts or prices → the skill asks for (or proposes labeled) assumptions first;
it never silently invents them.

SHOULD NOT FIRE:
N1. "Is the roadmap economically justified?"      (roadmap-reality-check — portfolio level)
N2. "How should we price the add-on?"             (pricing-tradeoff)
N3. "What does Claude cost per MTok?"             (pricing lookup, no feature model)
N4. "Reduce our AWS bill"                          (infra cost, not per-user feature economics)

# Gate 3 — Known-answer (arithmetic must reproduce exactly from these inputs)

FIXTURE INPUT (all assumptions stated):
"Feature: AI email drafts. Per draft: 2,000 input tokens (1,200 of them a shared
system prompt) + 500 output tokens. Usage: 8 drafts/user/workday, 22 workdays/month.
Prices (our contract): $3/MTok input, $15/MTok output; cached input billed at 10%
of input price, available for the shared prompt at any scale. Scale points: 1,000 /
50,000 / 1,000,000 users."

EXPECTED OUTPUT PROPERTIES:
1. EVERY number derived from the stated assumptions with the derivation shown.
   Base per-draft: input 2,000×$3/1M = $0.006 · output 500×$15/1M = $0.0075
   → $0.0135/draft. Per user/month: 8×22 = 176 drafts → 176×$0.0135 = $2.376.
2. Three scale points, straight multiplication shown:
   1k → $2,376/mo · 50k → $118,800/mo · 1M → $2,376,000/mo.
3. Stated levers only: the cache assumption (given) may be applied as a variant —
   cached: uncached input 800×$3/1M = $0.0024 + cached 1,200×$0.30/1M = $0.00036
   + output $0.0075 = $0.01026/draft → $1.8058/user/mo (~$1.81) → 1M users ≈
   $1,805,760/mo. Rounding shown, not hidden.
4. NO UNSTATED LEVERS: no bulk discounts, model downgrades, or usage decay that the
   input didn't grant. Sensitivity: the output names which assumption dominates
   (usage rate: 8/day is the multiplier to validate) and shows one labeled what-if
   ONLY as [ESTIMATE] with its arithmetic.
5. A margin hook: cost/user/mo is put next to any price given (none here → output
   states "no price provided — cost side only").

PLANTED-FAILURE CASE:
A draft stating "at 1M users, volume discounts bring this to ~$1.6M/mo" — a number
not derivable from any stated assumption — MUST be caught by the reproducibility
gate: every figure re-derives from the fixture inputs or it's cut/relabeled
[ESTIMATE: assumption stated]. An underivable number surviving = harness failure.
