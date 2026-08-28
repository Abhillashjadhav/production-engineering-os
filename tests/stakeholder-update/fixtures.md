# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/stakeholder-update/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Write the launch status update for the exec team"
T2. "Turn this project state into an update for the board"
T3. "Weekly stakeholder update from these notes"
T4. "/pm update sales on where the launch stands" (via orchestrator, state attached)
T5. "Status email to the customer advisory board — here's where we are"

SHOULD NOT FIRE:
N1. "Write the launch announcement"               (announcement-drafter — public comms)
N2. "Log this decision to project memory"         (pm-context-system)
N3. "How often should I update stakeholders?"     (knowledge question)
N4. "Summarize this meeting"                       (one-off summary, no audience calibration)

# Gate 3 — Known-answer

FIXTURE INPUT (project state):
"Launch state, AI summaries: rollout at 40% of workspaces (target was 100% by Fri —
2 days late due to EU residency bug, fixed Tue). Attach rate so far: 11% (assumption
in GTM brief was 15% at 90 days; we're at day 12). Support: 14 tickets, 2 escalations
(both the residency bug). Sales: 1 of 3 stalled deals reopened, demo booked. Error
rate: 0.3% against 0.5% rollback threshold. Next: cohort 3 flag removal Thursday.
Audiences: exec team (wants risk + trajectory), sales (wants ammo + timing)."

EXPECTED OUTPUT PROPERTIES:
1. THE RECONCILIATION GATE: every number in the update appears in, or derives
   arithmetically from, the input state (40%, 2 days late, 11% at day 12, 14/2,
   1 of 3, 0.3% vs 0.5%). A number with no input anchor = gate failure. NO INVENTED
   PROGRESS: nothing "on track" that the input marks late; no "customers are loving
   it" (no such signal in state).
2. Audience calibration WITHOUT content drift: the exec version leads with risk +
   trajectory (late-but-recovering, 11% vs 15% assumption honestly framed as day-12
   vs day-90), the sales version leads with the reopened deal + Thursday timing —
   but BOTH carry the same facts; calibration changes emphasis and detail level,
   never the numbers and never the bad news. Bad news absent from one audience's
   version = gate failure.
3. The 11%-vs-15% comparison must keep its time context (day 12 of 90) — presenting
   11% as a miss of the 90-day assumption = distortion; hiding the assumption = spin.
4. Delays carry cause + recovery (2 days late, residency bug, fixed Tue, cohort 3
   Thu) — not blame, not omission.
5. Each version ends with the ask/next relevant to that audience, drawn from state.

PLANTED-FAILURE CASE:
A draft exec update saying "rollout on track, early adoption strong, no significant
issues" — three claims the input contradicts (2 days late; 11% below the 15%
assumption without time framing; 2 escalations) — MUST be caught by the
reconciliation gate and rewritten against the actual state.
