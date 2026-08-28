# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/latency-ux-tradeoff/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "The AI summary takes 12 seconds — how should the UX handle it?"
T2. "Design the loading experience for our agent flow, latency budget 8s p50 / 20s p95"
T3. "Should we stream this response or show a spinner?"
T4. "/pm users bail during generation — fix the waiting experience" (via orchestrator)
T5. "Sync or async delivery for a 45-second report generation?"

SHOULD NOT FIRE:
N1. "Make the model respond faster"              (latency engineering, not UX design)
N2. "Which model is cheapest at this latency?"   (model-complexity-router / economics)
N3. "What's a good p95 for chat?"                (knowledge question, no flow attached)
N4. "Design our app's loading spinner style"     (visual design, no latency tradeoff)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Flow: recruiter opens a candidate profile; an AI 'fit summary' generates on open.
Latency: 4s p50, 11s p95. Context: recruiters scan ~30 profiles/session, back-to-back.
Profile page renders core data (name, CV) in 300ms. We measured: at 3s of blocked
waiting, 40% of recruiters navigate away; interviewed recruiters say they'd read a
summary that 'appears while they scan'."

EXPECTED OUTPUT PROPERTIES:
1. THE THRESHOLD GATE: every recommendation is tied to a STATED user-tolerance
   threshold — from the input where given (3s/40% bail measurement, 'appears while
   they scan') or from a named heuristic labeled as such (e.g. "~1s keeps flow /
   ~10s loses attention — Nielsen response-time bands [heuristic, not measured on
   your users]"). A recommendation justified by 'feels fast enough' or nothing = gate failure.
2. Expected design shape for this fixture: never block the profile render (300ms core
   data ships immediately); summary loads progressively/streams into a card; at 4s p50
   most summaries land mid-scan — tied to the 'appears while they scan' evidence;
   p95 11s exceeds the 3s bail threshold → the design must handle it explicitly
   (skeleton + partial content, or notify-when-ready), not average it away.
3. p50 AND p95 both addressed. A design that only works at p50 = gate failure (the
   p95 user exists 1-in-20 times per profile — ~1.5x/session at 30 profiles, math shown).
4. Each recommendation names its mechanism (streaming, skeleton, optimistic UI,
   async+notify, precompute) AND its cost/tradeoff (precompute wastes tokens on
   unopened profiles — flagged, routed to unit-economics if material).
5. No invented user research: the 3s/40% figure is the input's; any other threshold
   is labeled heuristic.

PLANTED-FAILURE CASE:
A draft recommending "show a friendly spinner with rotating tips — users don't mind
short waits" — no threshold cited, contradicts the measured 3s/40% bail data — MUST
be caught by the threshold gate and rebuilt against the stated measurements.
