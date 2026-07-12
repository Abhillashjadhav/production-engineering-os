# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/ai-feature-go-no-go/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Should we build AI auto-replies? Give me a go/no-go"
T2. "Build or kill: LLM-powered search over our docs"
T3. "Is this AI feature worth shipping? Here's the context: ..."
T4. "/pm go/no-go on adding an AI copilot to the dashboard" (via orchestrator)
T5. "Make the call on this AI feature — we keep debating it"

SHOULD NOT FIRE:
N1. "Map the assumptions behind the AI copilot"     (assumption-mapper — mapping, not deciding)
N2. "Should we build feature X?" (non-AI feature)   (general prioritization, not this skill's rubric)
N3. "Which LLM should power our copilot?"           (vendor/model selection, not go/no-go)
N4. "Go/no-go on the product launch date"           (launch decision, not an AI feature decision)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Go/no-go: AI-generated responses to customer support tickets, sent automatically
without agent review. Context: 8-person fintech startup, support handles account and
payments questions, error tolerance near zero (regulated), current CSAT 4.6/5,
ticket volume 400/mo, 1.5 support FTEs. LLM cost immaterial at this volume."

EXPECTED OUTPUT PROPERTIES:
1. A single decision: GO / NO-GO (a conditional GO must state the exact condition —
   not "it depends" hedging).
2. THE PIVOT CRITERION GATE: the decision names the SINGLE disqualifying or qualifying
   criterion it turns on — for this fixture the expected pivot is error tolerance:
   unreviewed generative output in a regulated, payments-adjacent flow with near-zero
   error tolerance = the disqualifier. A decision listing five co-equal reasons with
   no named pivot = gate failure.
3. Supporting factors are ranked BELOW the pivot and explicitly marked non-decisive
   (CSAT risk, volume too low to need automation: 400/mo ÷ 1.5 FTE is not a
   capacity crisis — arithmetic from input only).
4. The output must state what change would reverse the decision (e.g. human-in-the-loop
   review converts NO-GO to a scoped GO — a different feature, and the output says so).
5. No fabricated context: no invented compliance rulings, competitor moves, or user
   demand. The decision argues from provided context only.

PLANTED-FAILURE CASE:
A draft returning "GO — with careful monitoring, phased rollout, and a feedback loop"
(hedged GO that never names the criterion that would disqualify it) MUST be caught by
the pivot-criterion gate: no single named criterion → rewrite or failure report.
