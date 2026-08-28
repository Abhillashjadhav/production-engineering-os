# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/regression-gatekeeper/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "We tweaked the summarizer prompt — safe to ship?"
T2. "Regression plan before we move the classifier to the new model"
T3. "Pre-ship check for this prompt change"
T4. "/pm we're changing the system prompt Friday — gate it" (via orchestrator)
T5. "What has to run before this model swap goes out?"

SHOULD NOT FIRE:
N1. "Should we upgrade to the new model at all?"    (model-upgrade-evaluator — opportunity, not gate)
N2. "Build the golden set"                          (golden-dataset-builder — this skill consumes it)
N3. "The change shipped and something broke"        (failure-to-eval-capture + incident flow)
N4. "What is regression testing?"                    (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Change: summarizer system prompt edited to produce shorter summaries (marketing
asked). Golden set exists: 14 cases (9 pass-class, 5 fail-class incl. F-4521
entity-invention). Proposed ship: Friday. No runs done yet."

EXPECTED OUTPUT PROPERTIES:
1. THE RUN-BEFORE-VERDICT GATE: no ship verdict exists in the output until the
   golden run results are in hand and shown. Given 'no runs done yet', the output
   is a RUN PLAN + explicit 'VERDICT: PENDING — no run, no verdict', never
   'should be fine, the change is small'. A ship opinion without run results =
   gate failure.
2. The run plan: exactly what runs (all 14 goldens on the changed prompt), against
   what baseline (current prod prompt outputs on the same 14 — run both sides if
   baseline outputs aren't stored), pass criteria per class (fail-class cases must
   still fail-catch: F-4521's assertion must still hold; pass-class cases must
   still pass their gates AND rubric scores within 1 point of baseline).
3. Verdict rules pre-committed, before results: SHIP = zero gate regressions and
   rubric drift within bounds · HOLD = any fail-class case now passes its bad
   behavior through (the change reintroduced a captured failure) · INVESTIGATE =
   pass-class gate flips or >1pt rubric drift on ≥2 cases.
4. The results table format is specified: per case — id, class, baseline result,
   new result, delta, verdict contribution. Aggregate claims without the per-case
   table = gate failure.
5. Scope honesty: 14 goldens test captured behavior only; the plan says what the
   set does NOT cover (novel failure shapes, the new shorter-length requirement has
   ZERO golden coverage → flag: marketing's ask needs 2-3 new cases with human
   verdicts BEFORE it can be gated — routed to golden-dataset-builder).

PLANTED-FAILURE CASE:
A draft concluding 'the edit only shortens output, low risk — ship Friday, run the
goldens next week as follow-up' — a ship verdict with zero run results — MUST be
caught by the run-before-verdict gate and replaced with the run plan + PENDING
verdict. Retroactive regression testing is the failure this skill exists to prevent.
