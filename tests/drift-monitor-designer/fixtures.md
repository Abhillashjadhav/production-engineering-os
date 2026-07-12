# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/drift-monitor-designer/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Design drift monitoring for the shipped summarizer"
T2. "How do we know when the AI feature degrades in production?"
T3. "Production monitoring plan for the support-draft model"
T4. "/pm the feature shipped — what do we watch?" (via orchestrator)
T5. "Set up quality drift detection for the classifier"

SHOULD NOT FIRE:
N1. "Design guardrails for the workflow"           (guardrail-designer — per-request defenses, not trend monitoring)
N2. "Gate this prompt change before ship"          (regression-gatekeeper — point-in-time, pre-ship)
N3. "Build the analytics dashboard"                 (instrumentation build, not drift design)
N4. "What is model drift?"                          (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Shipped feature: AI meeting summaries (GA 6 weeks). Volume ~9,000 summaries/wk.
Known quality dimensions from the eval: no invented content (gate), action-item
attribution (gate), concision (rubric). Available plumbing: output logging, user
edit/delete events, thumbs up/down (12% leave feedback), weekly judge-scored
sample capacity of 150 summaries. Rollback flag still exists."

EXPECTED OUTPUT PROPERTIES:
1. THE THRESHOLD+ACTION GATE: every monitored signal carries (a) a threshold —
   numeric where the input gives a basis, else a labeled placeholder with a
   baseline-collection step — and (b) a NAMED response action (who/what fires:
   sample review, rollback flag, recalibration). A signal with no threshold
   ('watch edit rates') or no action ('alert if it rises') = gate failure.
2. Signal design uses ONLY the stated plumbing, layered by cost:
   - continuous proxies: edit-distance/delete rate on summaries, thumbs-down rate
     (12% feedback rate honestly noted as a biased, lagging sample)
   - scheduled ground truth: the weekly 150-summary judge run against the eval's
     gates (the real quality signal; proxies only triage)
   - input drift: meeting length/language distribution shifts (upstream cause)
3. Thresholds tied to baselines: week-1-6 numbers where they exist ('baseline
   edit rate unknown → first 2 weeks establish it, thresholds set at +X% over
   baseline, X labeled'); never invented absolute numbers presented as calibrated.
4. Every action names its route: proxy breach → pull a 50-case judge sample within
   24h · judge-run gate-failure rate >N% → regression-gatekeeper posture + rollback
   flag decision · sustained drift confirmed → failure-to-eval-capture for new
   cases + judge-calibration-auditor if judge-vs-thumbs diverges.
5. Alert hygiene: each signal states its expected false-positive source (holiday
   volume dips, long-meeting weeks) and the damping rule (2 consecutive windows,
   not single spikes).

PLANTED-FAILURE CASE:
A draft signal 'monitor summary quality weekly and alert if it drops significantly'
— no defined signal, no threshold, no named action — MUST be caught by the gate
and decomposed into the concrete layered signals above.
