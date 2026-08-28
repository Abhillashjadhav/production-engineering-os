---
name: loop-designer
description: "Iterate-stage skill: turns a recurring chore into a guarded autonomous loop — five-part anatomy (Discover/Plan/Execute/Verify/Stop), five non-negotiable guardrails, and a verifier that is never the executor. Use when a repeated manual task should run on a schedule — 'turn this weekly chore into an autonomous loop', 'design a guarded loop for the digest', 'automate this triage safely' — or when /pm routes such a request here. Do NOT use for one-shot workflow hardening (guardrail-designer), for plain cron scheduling of a script, for executing the loop, or for definitions of autonomous loops."
argument-hint: "<the recurring chore: what you do, from what source, how often, where the output goes>"
---

# Loop Designer

A chore in, a loop out — designed verification-first: what a correct run produces is written before the executor prompt exists, and the executor never grades its own homework.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Step 0 present, first:** before any anatomy is written, Step 0 defines the checkable conditions of a correct run (counts reconcile, citations real, required elements present). The verifier checks these conditions — a loop whose success criteria were written after (or by) the executor fails.
- **G2 — Executor ≠ verifier:** the Verify stage is structurally separate from Execute — an independent pass or mechanical check suite with its own instructions, receiving the artifact and raw source references, not the executor's reasoning. "The agent double-checks its own work" fails the gate.
- **G3 — Five parts, five guardrails:** Discover / Plan / Execute / Verify / Stop all present and named; all five guardrails present, each with named failure + trigger: scope ceiling · output gate (verify fails → no output ships) · kill switch (N consecutive failures → loop disables + alerts) · cost/step budget · no-silent-drift (source anomaly → halt, don't improvise).

## Steps

0. **Define done, first.** From the chore, write the correct-run conditions as checkable statements ("every theme cites ≥2 ticket IDs", "counts reconcile to the ticket total", "zero invented quotes"). These become the verifier's checklist verbatim.
1. **Discover:** the source, the window, the query — stated exactly (last 7 days of tickets from X). Anomaly bounds here feed the no-silent-drift guardrail (volume ±3x usual → halt).
2. **Plan + Execute:** the transformation, method named (cluster by underlying complaint; draft the post). The executor prompt contains the task and the guardrail ceilings — it does not contain the authority to ship.
3. **Verify — independently.** A second pass (separate agent, or mechanical checks) runs the Step 0 checklist against the artifact plus raw source IDs. State the separation mechanism: what the verifier receives, what it can't see (the executor's self-assessment), and its verdict format (pass → Stop may ship; fail → failure report, nothing posts).
4. **Stop:** on pass — deliver + one-line run report; on fail — report instead of output; kill switch after 2 consecutive fails (loop disables itself and alerts); every run logs what it read, produced, and verified.
5. **Emit the runner:** a paste-ready scheduled prompt (Claude Routine or cron + `claude -p`) whose body carries the full anatomy and guardrails, plus the schedule taken from the chore. One runner recommended, not two half-configured ones.
6. **Gate pass:** Step 0 precedes and feeds Verify (G1), separation stated (G2), 5 parts + 5 guardrails each named+triggered (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
LOOP: weekly support-themes digest (Mondays)
STEP 0 — CORRECT-RUN CONDITIONS (written first; the verifier's checklist)
  C1 every theme cites ≥2 ticket IDs · C2 theme counts reconcile to ticket total ·
  C3 zero quotes absent from source tickets · C4 post ≤300 words
ANATOMY
  Discover: tickets from <source>, trailing 7 days; expected volume 60-120 (drift bound)
  Plan/Execute: cluster by underlying complaint → draft #product post [executor prompt: task + ceilings, no ship authority]
  Verify [independent]: verifier pass receives draft + raw ticket IDs only; runs C1-C4; verdict pass/fail with evidence
  Stop: pass → post + run report · fail → failure report, no post
GUARDRAILS (failure → trigger)
  1 scope ceiling: >200 tickets → halt, human · 2 output gate: any C fails → no post ·
  3 kill switch: 2 consecutive fails → disable + alert · 4 budget: ≤X steps/tokens per
  run [ceiling instructs the model; runner cap enforces] · 5 drift: volume outside
  60-120 or schema change → halt, don't improvise
RUNNER (paste-ready): [scheduled prompt embedding all of the above · Mondays 08:00]
LIMITS: novel complaint types are flagged, not force-classified; human reads before
acting on weeks 1-4.
GATE CHECK: G1 pass (Step 0 first) · G2 pass (verifier separate) · G3 pass (5+5)
```

## Hard rules

1. Step 0 comes first and the verifier checks exactly it. Success criteria written by or after the executor are self-grading with extra steps.
2. The executor never ships its own output. The output gate sits between Execute and the world, held by the verifier.
3. All five guardrails, always — a loop that "doesn't need" a kill switch is a loop that hasn't failed yet. Cost ceilings are honest about enforcement: the prompt instructs, the runner's caps enforce.
4. Never design a loop for a chore whose correct output can't be checked (no Step 0 conditions exist) — say so; that chore needs a human or a redesign, not automation.

## Limitations

- The design assumes the runner platform provides scheduling and hard caps; prompt-level budgets instruct the model but don't meter the account.
- Verifier independence is structural (separate pass, separate inputs), not adversarial — a shared systematic blind spot can pass both; golden cases from real runs (failure-to-eval-capture) close that over time.
- Week-1-4 human readership is part of the design, not a disclaimer — trust is earned by verified runs, and the loop spec says when to revisit it.
- Loops compose poorly: one chore, one loop; chains of loops need their own design pass, flagged when detected.
