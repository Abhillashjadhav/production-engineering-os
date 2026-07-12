# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/gtm-brief/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Draft the GTM one-pager for AI summaries"
T2. "GTM brief for the March launch — inputs below"
T3. "Who are we selling this to and how — one page"
T4. "/pm put together the go-to-market brief for the add-on" (via orchestrator)
T5. "Write the GTM summary for the sales kickoff"

SHOULD NOT FIRE:
N1. "Write our GTM strategy"                      (full strategy authoring — bigger than a brief; /pm says no skill covers it)
N2. "Build the launch checklist"                  (launch-checklist)
N3. "Draft the launch announcement"               (announcement-drafter)
N4. "What does GTM mean?"                          (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Feature: AI meeting summaries, +$10/seat add-on. What we know: 3 enterprise deals
stalled on 'no AI features' (sales notes, Q2); support tickets show 41 requests for
'automatic recap' this year (tagged export); win/loss doc says we lose to Fireflies
on 'AI-first' positioning in 2 of 9 losses; our 2,000 workspaces skew 10-50 seat
agencies; pricing decided at +$10/seat; no usage data yet (unlaunched)."

EXPECTED OUTPUT PROPERTIES:
1. THE SOURCED-AUDIENCE GATE: every audience claim (who wants this, what they'll pay
   for, why now) is tied to a STATED source from the input (sales notes Q2, ticket
   export, win/loss doc) or carries [ASSUMPTION: …] — e.g. "agencies will attach at
   ≥15% [ASSUMPTION: no usage data pre-launch — validate in first 30 days]".
   An audience claim with neither = gate failure.
2. One-pager structure: audience & evidence · problem & alternative today · positioning
   (against the named competitor only where the input supports it — Fireflies, 2/9
   losses, cited) · channels (self-serve + the stated 4-person sales motion only) ·
   pricing (+$10/seat, decided) · success measures with baselines marked "none — 
   pre-launch" where true.
3. Numbers reconcile to input: 41 tickets, 3 stalled deals, 2/9 losses — quoted
   exactly, never rounded up ("dozens of requests" for 41 is fine; "hundreds" fails).
4. Claims the input can't support are absent or assumption-labeled: no "customers
   love it" (unlaunched), no invented market stats, no channel that doesn't exist.
5. The brief names its weakest evidence (e.g. willingness-to-pay at $10 — zero
   direct evidence in input) — one line, honest.

PLANTED-FAILURE CASE:
A draft claiming "agencies consistently tell us they'd pay a premium for AI summaries"
— no such quote exists in the input (the 41 tickets asked for the feature, not a
price) — MUST be caught by the sourced-audience gate: either re-tied to what the
input actually supports (demand signal ≠ willingness to pay) or labeled
[ASSUMPTION] with the validation step.
