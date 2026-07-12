# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/build-buy-partner/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Should we build our own billing system or buy Stripe Billing?"
T2. "Build vs buy vs partner for document e-signatures in our product"
T3. "We need SOC 2 log pipelines — build, buy, or partner?"
T4. "/pm we need calendar-sync infrastructure — make the build/buy call" (via orchestrator)
T5. "Evaluate options for adding video calls: in-house vs Twilio vs partnering with a video vendor"

SHOULD NOT FIRE:
N1. "Which billing vendor is best?"                 (vendor selection AFTER a buy decision)
N2. "Go/no-go on the AI copilot"                    (ai-feature-go-no-go)
N3. "Negotiate our Stripe contract"                 (procurement, not the decision)
N4. "What does 'build vs buy' mean?"                (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Capability needed: e-signature inside our proposal tool (B2B SaaS for agencies,
12 engineers, e-sign is adjacent to core value but customers ask for it in 30% of
lost-deal notes per sales. Compliance matters (ESIGN/eIDAS). Vendor APIs exist
(~$0.50/envelope at our volume ≈ 2,000 envelopes/mo). No existing partnership motion."

EXPECTED OUTPUT PROPERTIES:
1. THE SAME-AXES GATE: all THREE options (build / buy / partner) scored on the SAME
   named axes BEFORE any recommendation appears. Required axes at minimum: time to
   capability, total cost class (build+maintain vs per-unit), differentiation value
   (is this core?), risk (compliance/vendor lock-in/partner dependency), and
   reversibility. A recommendation appearing before the full matrix, or an option
   scored on fewer axes than the others, = gate failure.
2. Scores are comparative labels (strong/weak/moderate or H/M/L) with a one-line basis
   each — no invented dollar figures beyond input numbers; $0.50 × 2,000/mo = $1,000/mo
   buy-side run-rate is the only hard number available and must be used, tagged to input.
3. Expected verdict shape for this fixture: BUY favored (adjacent-not-core, compliance
   burden, 12-eng team, cheap per-envelope) — but the gate checks process, not the
   verdict; a well-argued alternative passes if the matrix is complete and honest.
4. The recommendation must cite which axis differentials decided it (e.g. "buy wins on
   time-to-capability and compliance risk; build's only win is unit cost at scale we
   don't have").
5. Kill-the-recommendation line: what fact would flip it (e.g. e-sign becomes core
   differentiation, or volume grows to where per-envelope cost crosses build cost —
   with the crossover shown as a labeled estimate, not a fake precise number).

PLANTED-FAILURE CASE:
A draft that opens with "Recommendation: Buy — DocuSign or similar" and then scores
only build-vs-buy (partner never scored, matrix after the verdict) MUST be caught by
the same-axes gate: all three options, same axes, matrix before recommendation.
