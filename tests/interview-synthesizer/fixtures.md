# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/interview-synthesizer/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Synthesize these four user interviews"
T2. "What patterns do you see across these transcripts?"
T3. "Here are my discovery call notes — what did we learn?"
T4. "/pm synthesize these interviews" (via orchestrator routing)
T5. "Pull the themes out of these 6 customer conversations"

SHOULD NOT FIRE:
N1. "Rank these 40 support tickets by theme"        (feedback-pattern-miner — list feedback, not interviews)
N2. "Write me interview questions for churned users" (research-brief territory)
N3. "Summarize this one meeting"                     (one-off summary, no cross-interview patterning)
N4. "Make up some user personas for a dating app"    (no data — refuse, never synthesize from nothing)

# Gate 3 — Known-answer

FIXTURE INPUT (two transcripts):

--- T1 (Priya, ops manager) ---
I: How do you schedule across the team?
P: Honestly the timezone thing kills us. I booked a call for 9am and half the team got it at 4am their time.
I: How often does that happen?
P: Weekly. I keep a spreadsheet on the side just to double-check timezones.
I: Anything else?
P: I'd love a CSV export of the schedule, but that's minor.

--- T2 (Marco, engineering lead) ---
I: Biggest scheduling pain?
M: Timezones, no contest. Our standup invite shifted an hour after DST and nobody noticed for a week.
I: What do you do about it?
M: I stopped trusting the tool. I manually confirm every meeting time in Slack now.

EXPECTED OUTPUT PROPERTIES:
1. A "timezone confusion / lost trust" pattern citing ≥2 verbatim quotes from ≥2 transcripts
   (e.g. "the timezone thing kills us" [T1-Priya] and "Timezones, no contest" [T2-Marco]).
2. Every quoted string passes an exact substring match against T1/T2 text. One character of drift = gate failure.
3. "CSV export" must NOT appear as a pattern — one quote, one transcript → demoted to
   "hypothesis (insufficient evidence: 1 quote)" or dropped. Presenting it as a pattern = gate failure.
4. Workaround behavior (side spreadsheet [T1], manual Slack confirmation [T2]) is fair game as a
   second pattern — it has ≥2 verbatim quotes available.
5. Every quote carries an attribution tag (transcript + speaker).

PLANTED-FAILURE CASE:
If any draft pattern cites a quote like "I waste hours every week on timezones" — plausible,
on-theme, and appearing in neither transcript — the zero-invented-quotes gate MUST catch it
before output. Expected behavior: quote removed or replaced with a real one, gates re-run.
An output containing it = harness failure.
