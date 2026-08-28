# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/assumption-mapper/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Map the assumptions behind this feature idea"
T2. "What are we betting on if we build an AI onboarding coach?"
T3. "What could kill this idea? Here's the pitch: ..."
T4. "/pm we want to build usage-based pricing — what needs to be true?" (via orchestrator)
T5. "Riskiest assumption first — break down this concept"

SHOULD NOT FIRE:
N1. "Write the PRD for the onboarding coach"        (Build stage — not shipped, /pm refuses)
N2. "Size the market for onboarding tools"          (opportunity-sizer)
N3. "What is a riskiest-assumption test?"           (knowledge question)
N4. "List the assumptions in this legal contract"   (document analysis, not product-idea risk mapping)

# Gate 3 — Known-answer

FIXTURE INPUT (idea):
"Add an AI meeting-summary bot to our B2B calendar app. Enterprise admins will pay a
$10/seat add-on because managers waste hours writing recaps, and our on-prem customers
will trust us with meeting audio."

EXPECTED OUTPUT PROPERTIES:
1. Every assumption carries ALL of: risk rank, impact-if-wrong (H/M/L) with one-line
   basis, confidence (H/M/L) with one-line basis, tag `testable` or `untestable`, and —
   for every testable one — a concrete proposed test (method + what evidence would
   confirm/kill it). A testable assumption with no proposed test = gate failure.
2. Must surface at minimum: desirability ("managers actually want automated recaps
   enough to pay"), willingness-to-pay ("$10/seat add-on acceptable to admins"),
   trust/privacy ("on-prem customers will share meeting audio"), and feasibility
   ("summary quality good enough without human cleanup").
3. Untestable-as-stated assumptions must include WHY untestable now + a sharper
   reformulation that would be testable, or an explicit "monitor, cannot pre-test" call.
4. Ranked riskiest-first: rank must follow impact × uncertainty, not listing order.
5. No fabricated evidence: the skill maps assumptions; it must NOT claim "users have
   said X" or cite data not in the input.

PLANTED-FAILURE CASE:
A draft tagging "on-prem customers will trust us with meeting audio" as `untestable`
without a reformulation (e.g. design-partner interviews with security teams, a signed
LOI contingent on audio handling) MUST be caught by the tag-completeness gate.
