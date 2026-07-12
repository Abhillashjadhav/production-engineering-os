# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/feedback-pattern-miner/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Rank these 40 support tickets by theme"
T2. "Here's our app-store review export — what are people complaining about most?"
T3. "Mine this NPS verbatim dump for patterns"
T4. "/pm what should we fix first based on this feedback?" (via orchestrator, feedback list attached)
T5. "Cluster this churn-survey feedback"

SHOULD NOT FIRE:
N1. "Synthesize these three interview transcripts"   (interview-synthesizer — conversations, not items)
N2. "How should I collect user feedback?"            (process question, no data)
N3. "Reply to this angry customer"                   (single item, support task)
N4. "What's a good NPS score for SaaS?"              (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT (10 feedback items):
F1. "Sync to Google Calendar breaks at least once a week."
F2. "Love the product but the mobile app crashes when I open settings."
F3. "Why is there STILL no dark mode?"
F4. "Calendar sync dropped my events again. Third time this month."
F5. "App crashed twice during onboarding on my Pixel."
F6. "Dark mode please, my eyes hurt at night."
F7. "The sync with Outlook silently fails — worst kind of bug."
F8. "Pricing page is confusing, couldn't tell what tier I need."
F9. "Crashes on Android every time I rotate the screen."
F10. "chicken chicken chicken"

EXPECTED OUTPUT PROPERTIES:
1. Themes ranked by count, each listing its member item IDs. Expected clustering:
   sync reliability {F1,F4,F7}=3 · mobile crashes {F2,F5,F9}=3 · dark mode {F3,F6}=2 ·
   pricing clarity {F8}=1 · unclassifiable {F10}=1.
2. RECONCILIATION LINE REQUIRED: theme counts sum to input total —
   3+3+2+1+1 = 10/10 items accounted for. Sum ≠ 10 = gate failure.
3. Each item assigned to exactly ONE primary theme (no double counting; overlap noted
   as secondary tags that do NOT enter the counts).
4. F10 lands in "unclassified" — counted, never dropped, never force-fitted into a theme.
5. No invented items: every cited item ID exists in the input; every quoted fragment is verbatim.

PLANTED-FAILURE CASE:
A draft that clusters F10 into "mobile crashes" to avoid an unclassified bucket, or reports
9/10 items (silently dropping F10), MUST be caught by the reconciliation gate before output.
