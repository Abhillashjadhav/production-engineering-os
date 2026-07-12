# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/strategy-review/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Pressure-test this strategy doc"
T2. "Here's our 2027 product strategy — tear it apart before the board does"
T3. "Red-team this positioning memo"
T4. "/pm review our platform strategy" (via orchestrator, doc attached)
T5. "What's weak in this strategy one-pager?"

SHOULD NOT FIRE:
N1. "Write our product strategy"                    (authoring, not reviewing — needs a doc to attack)
N2. "Review this PR"                                (/pr-review's job)
N3. "Tear down Linear's strategy"                   (competitor-teardown — external product, not our doc)
N4. "What makes a good strategy?"                   (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT (strategy doc, numbered lines):
L1. We will win the SMB scheduling market by being the easiest tool to adopt.
L2. Our wedge is one-click calendar migration from Calendly.
L3. We expect 30% of Calendly's SMB churn to convert to us within a year.
L4. Pricing will undercut Calendly by 50% to remove all friction.
L5. Long-term we defend through network effects as teams invite each other.
L6. We will not build enterprise features until we own SMB.

EXPECTED OUTPUT PROPERTIES:
1. EVERY weakness cites the specific line(s) it attacks by number, quoting the attacked
   text. A free-floating criticism ("the strategy lacks focus") with no line citation
   = gate failure.
2. Expected genuine attack surfaces the review should find (any 3+ of):
   - L3: a conversion number with no stated basis (30% of churn — from where?)
   - L4: 50% undercut vs. L1 "easiest to adopt" — price positioning conflated with
     adoption positioning; margin consequence unstated
   - L5: claimed network effects with no mechanism in a scheduling tool (L2 is a
     single-player wedge — contradiction between L2 and L5)
   - L1: "easiest to adopt" is a claim every competitor makes — no stated falsifiable basis
3. Each weakness carries: severity (fatal / serious / minor), the failure mode it
   creates, and the question the author must answer to repair it.
4. Contradiction pairs must cite BOTH lines (e.g. L2 vs L5).
5. The review must also state what survives the attack (strongest line and why) —
   pure demolition with no survivors named = incomplete review.

PLANTED-FAILURE CASE:
A draft weakness "the go-to-market section is underdeveloped" — the fixture doc has no
GTM section, so there is no line to cite. The line-citation gate MUST catch it: either
it converts to "missing entirely: GTM — the doc never says how L2's migration tool
reaches Calendly churners (gap, no line to cite)" explicitly labeled a GAP, or it's cut.
Free-floating criticism surviving to output = harness failure.
