# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/north-star-designer/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Design a north star metric for our product"
T2. "What should our NSM be? We're a team scheduling tool"
T3. "Build the metric tree from north star down to team inputs"
T4. "/pm we keep optimizing revenue and losing users — what should we actually measure?" (via orchestrator)
T5. "Is MRR a good north star for us? Propose better"

SHOULD NOT FIRE:
N1. "What is a north star metric?"                  (knowledge question)
N2. "Set up our analytics dashboards"                (instrumentation, not metric design)
N3. "Why did activation drop last month?"            (diagnosis — research-brief)
N4. "Set this quarter's OKR targets"                 (target-setting, not metric design)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Product: team scheduling tool for agencies (B2B SaaS, per-seat). Users book internal
and client meetings. Retention correlates with teams that connect both calendar and
video-call accounts. Revenue: per-seat subscriptions. We currently track MRR as our
main metric."

EXPECTED OUTPUT PROPERTIES:
1. THE LEADING-METRIC GATE: the proposed NSM must be leading, not lagging, and the
   output must STATE THE CHECK it passed — the causality test in explicit form:
   "when this number moves this week, [revenue/retention] moves later; the reverse
   is not true" plus what a team can do THIS WEEK to move it. A metric where the
   causality runs the wrong way (MRR, churn, NPS) proposed as NSM = gate failure.
2. Expected shape for this fixture: a value-delivery metric like "weekly meetings
   successfully scheduled per active team" (or defensibly similar) — NOT MRR
   (lagging: revenue result), NOT signups (activity without value delivery).
3. The output must explicitly reject the current metric (MRR) with the reason
   classed: lagging — it records value already captured, cannot be acted on weekly.
4. Metric tree required: NSM at root → 2-4 input metrics (e.g. teams fully connected
   [both integrations, per the stated retention correlation], scheduling success rate,
   active teams) → each input mapped to the team/lever that moves it.
5. Gaming check: the output names at least one way the NSM can be gamed and the
   guardrail metric paired against it.
6. No fabricated data: the design uses the stated retention correlation; it must not
   invent benchmark values or claim measured correlations not in the input.

PLANTED-FAILURE CASE:
A draft proposing "monthly recurring revenue per connected team" as the NSM — revenue
composite, still lagging — MUST be caught by the leading-metric check (moving it this
week is not actionable; revenue follows value with a lag) and replaced with the
value-delivery metric upstream of it.
