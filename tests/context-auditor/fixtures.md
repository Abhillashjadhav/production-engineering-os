# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/context-auditor/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Audit my CLAUDE.md — the agent keeps ignoring half of it"
T2. "Scan this system prompt for context problems"
T3. "Why does my agent behave worse as the context file grows? Here's the file"
T4. "/pm check our assembled context for failure modes" (via orchestrator, file attached)
T5. "Run the four-failure-mode diagnostic on this prompt file"

SHOULD NOT FIRE:
N1. "Set up project memory files"                (pm-context-system — creating, not auditing)
N2. "Why is my context window filling up?"       (token economics, not content failure modes)
N3. "What is context poisoning?"                  (knowledge question)
N4. "Improve this prompt's output quality"        (prompt-optimizer-loop)

# Gate 3 — Known-answer

FIXTURE INPUT (context file, numbered lines):
L1. You are the support agent for Acme Scheduler.
L2. Always answer in formal English.
L3. Acme Scheduler was founded in 2019 in Berlin.
L4. Our Pro tier costs $12/user/month.
L5. Note from March: Pro tier is $9/user/month during the promo.
L6. Keep answers under 100 words.
L7. Be casual and friendly — match the user's tone.
L8. The complete 2024 changelog follows (400 lines): [pasted changelog]
L9. Acme was founded in 2021 as a Munich spinoff of CalCo.

EXPECTED OUTPUT PROPERTIES:
1. EVERY finding carries exactly one mode tag from {POISONING, DISTRACTION, CONFUSION,
   CLASH} plus the offending line number(s). An untagged finding, a finding with no
   line, or a mode outside the four = gate failure.
2. Expected findings (the audit must surface at least these):
   - CLASH: L2 vs L7 (formal vs casual — direct instruction conflict)
   - CLASH: L4 vs L5 (two prices; L5 possibly stale promo — flagged for the user to
     resolve, not silently chosen)
   - POISONING: L3 vs L9 (contradictory founding facts — one is false and will be
     repeated downstream; flagged, not adjudicated from outside knowledge)
   - DISTRACTION: L8 (400-line changelog dwarfing the instructions)
3. Severity per finding (critical/warning) with the downstream behavior it produces.
4. The audit ADJUDICATES NOTHING it can't see: it must not declare which founding
   year is true or which price is current — it flags the conflict and asks.
5. Fix per finding: cut, rewrite, or resolve-with-user — concrete, line-referenced.

PLANTED-FAILURE CASE:
A draft finding "the file's tone is generally inconsistent" — no mode tag, no line
numbers — MUST be caught by the tag gate and either converted to the concrete
CLASH finding (L2 vs L7) or cut. Similarly a draft that "fixes" L9 by asserting the
true founding year from world knowledge = fabrication, caught by property 4.
