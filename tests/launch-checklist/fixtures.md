# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/launch-checklist/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Build the launch checklist for the AI summaries feature"
T2. "What do we need before we can ship this to all customers?"
T3. "Launch readiness list for the March release — team context below"
T4. "/pm we ship in 3 weeks — what has to happen?" (via orchestrator)
T5. "Tailor a go-live checklist: B2B, self-serve + sales-assist, EU customers included"

SHOULD NOT FIRE:
N1. "Write the launch announcement"               (announcement-drafter)
N2. "Draft the GTM one-pager"                     (gtm-brief)
N3. "Go/no-go on shipping this feature"           (ai-feature-go-no-go — decision, not checklist)
N4. "What is a launch checklist?"                  (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Feature: AI meeting summaries, GA to all 2,000 workspaces. Context: B2B SaaS,
self-serve + 4-person sales team; EU customers on EU data residency; support team
of 3 (has NOT seen the feature); feature behind a flag today; pricing +$10/seat
add-on decided; docs site exists; status page exists."

EXPECTED OUTPUT PROPERTIES:
1. THE OWNER+DONE GATE: every checklist item carries (a) a named owner ROLE from the
   stated context (support lead, sales team, PM — never a person invented, never
   "marketing" when no marketing team was stated) and (b) a VERIFIABLE done
   condition — observable, checkable, dated where relevant. "Align with marketing"
   or "make sure support is ready" = gate failure.
   Example of passing form: "Support: all 3 agents have run the feature on 2 test
   workspaces; macros for top-5 expected questions exist in the helpdesk — done when
   macro IDs listed."
2. Tailored to stated context, with at least: flag-removal/rollout mechanics, support
   enablement (team stated as unprepared), EU data-residency check for the AI path,
   billing wiring for the +$10 add-on, docs update, rollback condition + owner.
3. NO generic-template items that contradict context (no "brief the PR agency" — none
   stated; no "app store screenshots" — B2B web).
4. Sequenced: blockers-before-ship vs day-of vs week-after, each item in a phase.
5. Rollback criteria are themselves a checklist item with owner + observable trigger
   ("error rate >X% on summaries endpoint" is fine as a labeled placeholder for the
   user to fill — X flagged, not invented).

PLANTED-FAILURE CASE:
A draft containing "☐ Align with marketing on messaging" (no owner in context, no
done condition) MUST be caught by the owner+done gate: either converted to a concrete
item owned by a stated role with a verifiable condition, or cut with the note that
no marketing function exists in the stated context.
