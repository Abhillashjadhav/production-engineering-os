# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/guardrail-designer/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Design guardrails for our AI support-reply workflow"
T2. "What can go wrong in this agent flow, and what stops it?"
T3. "Error/hallucination/edge-case protection for the summarizer pipeline"
T4. "/pm harden this workflow before we scale it" (via orchestrator)
T5. "Guardrail review: here's the flow, where are we exposed?"

SHOULD NOT FIRE:
N1. "Design a guarded autonomous loop for this chore"  (loop-designer — loops have their own anatomy)
N2. "Build the eval for this feature"                  (eval-engine — offline verification)
N3. "Monitor this feature for drift in production"     (drift-monitor-designer)
N4. "What are AI guardrails?"                           (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT (workflow):
"AI support-reply workflow: ticket arrives → model drafts a reply using the customer
record and policy docs → draft goes to the agent queue → agent clicks send (or edits).
Volume 400/mo. Agents are trained to review but get 30+ drafts/day at peak.
Known incidents: one draft included another customer's account balance (retrieval
pulled the wrong record); one promised a refund policy we retired in January."

EXPECTED OUTPUT PROPERTIES:
1. THE NAMED-FAILURE+TRIGGER GATE: every guardrail states (a) the specific failure
   it prevents and (b) its trigger condition — the observable event/check that fires
   it. "Add validation" (no failure named) or "prevent hallucinations" (no trigger
   condition) = gate failure. Passing form: "G: cross-record leak (incident 1) —
   TRIGGER: any account number/balance in draft ∉ this ticket's customer record →
   block draft, flag retrieval".
2. Coverage derived from the workflow's actual surfaces, at minimum:
   - retrieval wrong-record (incident 1) → record-match check
   - stale policy citation (incident 2) → policy-version check against current corpus
   - invented commitments (class risk) → commitment-pattern screen
   - reviewer fatigue at 30+/day (stated) → the human layer is itself a failure
     surface: risk-tiered queue (money/legal drafts can't be one-click sent), not
     'agents will catch it'.
3. Each guardrail placed in the flow (pre-draft, post-draft, pre-send) with its
   action on trigger (block/flag/route) and its cost (latency, false-positive
   friction) stated.
4. Layering shown: mechanical checks before human review, human review calibrated
   to what mechanical checks can't catch — never 'the agent reviews everything' as
   the only line.
5. No invented incidents or compliance requirements; known incidents drive the top
   guardrails, class risks labeled as class risks.
6. Residual risk stated: what these guardrails do NOT catch (novel failure modes) →
   wired to failure-to-eval-capture when they occur.

PLANTED-FAILURE CASE:
A draft guardrail "add a validation layer to ensure output quality and prevent
hallucinations" — no named failure, no trigger condition, no placement — MUST be
caught by the gate and decomposed into the concrete checks above or cut.
