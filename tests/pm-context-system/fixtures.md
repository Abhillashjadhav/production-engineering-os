# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/pm-context-system/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE (explicit):
T1. "Set up project memory"
T2. "Make Claude remember my stakeholders across sessions"
T3. "You keep forgetting my project every session — fix that"

SHOULD FIRE (proactive, mid-session):
T4. A decision lands in conversation ("let's go with Postgres over Dynamo for the
    audit log") with no memory request → expect ONE proposal line, not silence,
    not an interview.
T5. "Update context" at session end → sweep proposes only what wasn't already logged.

SHOULD NOT FIRE:
N1. "Summarize this meeting"                     (one-off output, not durable memory)
N2. "Audit my CLAUDE.md"                         (context-auditor)
N3. "Do you remember our last chat?"             (conversation-memory question)
N4. Routine conversation with no decision, stakeholder fact, or state change —
    expect silence, not a placeholder proposal.

# Gate 3 — Known-answer

SCENARIO A (fresh project, no context/ dir; mid-conversation the user says
"we're going with usage-based pricing for the API, flat pricing lost"):
EXPECT exactly one line, in exactly this form:
  Log to memory: "<the decision + why>" — yes/edit/skip
— single line, no second question, no file talk. On "yes": context/ scaffolded
silently (INDEX, STAKEHOLDERS, DECISIONS, STATE), entry written to DECISIONS.md,
CLAUDE.md pointer added. On "skip": nothing written, that fact never re-proposed.

SCENARIO B (existing context/, second decision surfaces): one new proposal line tied
to that decision only — no batch, no re-proposal of logged items.

SCENARIO C (session end, "update context"; one decision already logged inline, one
state change not): sweep proposes ONLY the unlogged state change. Re-proposing the
logged decision = gate failure.

SCENARIO D (STATE.md entry idle 30+ days): archive PROPOSAL with user flag — silent
deletion = gate failure.

GATE PROPERTIES (checked on every proposal):
1. Single line, "Log to memory: … — yes/edit/skip" form. Multi-line or multi-question
   proposals = gate failure.
2. Nothing is ever written without yes/edit. Silent writes = gate failure.
3. Proposals fire on actual session events (decision, stakeholder fact, state change),
   never as empty ritual.

PLANTED-FAILURE CASE:
On SCENARIO A, a draft that responds with a 5-question interview ("What's the project
name? Who are the stakeholders? What are your goals? …") before writing anything —
the never-an-interview gate MUST catch it and reduce it to the one-line proposal for
the decision that actually just happened.
