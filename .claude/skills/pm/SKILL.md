---
name: pm
description: "The pm-agent-os orchestrator. Use when the user invokes /pm or hands over any product-management request — synthesizing interviews, mining feedback, mapping assumptions, tearing down a competitor, sizing an opportunity, framing jobs-to-be-done, planning research, or any multi-step product task spanning discovery, strategy, build, launch, or iterate. Classifies the request into lifecycle stage(s), invokes the matching stage skills in sequence, and blocks every output whose verification gate has not passed. Also use when the user asks to run any output past a reviewer persona — 'review as engineer/designer/executive/skeptic/customer/data-analyst/legal' — routing to the persona agents in .claude/agents/. Do NOT use for coding tasks, repo maintenance, PR reviews (/pr-review's job), or knowledge questions about PM concepts with no work item attached."
argument-hint: "<any product request — e.g. 'synthesize these 4 interviews' or 'size the market for X'>"
---

# /pm — Orchestrator

Route → execute → verify → return. Nothing reaches the user unverified.

## The one hard rule above all others

**No output returns to the user until its verification gate passes.** Every stage skill defines binary gates in its own SKILL.md. The orchestrator runs them (or confirms the skill ran them) before relaying anything. A gate failure triggers repair, not delivery.

## Stage routing table

| Stage | Status | Skills |
|---|---|---|
| Discovery | **Shipped** | interview-synthesizer · feedback-pattern-miner · assumption-mapper · competitor-teardown · opportunity-sizer · jtbd-framer · research-brief (all under `.claude/skills/<name>/SKILL.md`) |
| Strategy | **Shipped** | strategy-review · roadmap-reality-check · ai-feature-go-no-go · north-star-designer · build-buy-partner · pricing-tradeoff |
| Build | **Shipped** | decision-contract-builder · model-complexity-router · builder-validator · prompt-optimizer-loop · context-auditor · pm-context-system · prd-to-eval · prototype-first-workflow · rag-vs-agent-architect · latency-ux-tradeoff · unit-economics-stress-test |
| Launch | **Shipped** | launch-checklist · gtm-brief · stakeholder-update · announcement-drafter · launch-retro (+ 7 reviewer personas in `.claude/agents/`) |
| Iterate | **Shipped** | eval-engine · llm-as-judge-designer · judge-calibration-auditor · golden-dataset-builder · failure-to-eval-capture · guardrail-designer · loop-designer · regression-gatekeeper · model-upgrade-evaluator · eval-vs-abtest-router · drift-monitor-designer · mcp-migration-auditor |

## Step 1 — Classify

Map the request to lifecycle stage(s). Signals: transcripts/feedback/assumptions/competitors/market-size/jobs/research questions → Discovery. Positioning, pricing, GTM, roadmap → Strategy. Specs, evals, prototypes, AI architecture, model routing, prompts, context files, token economics, latency UX, decision-contract authoring/approval/handoff → Build. Launch checklists, GTM briefs, status updates, announcements, retros → Launch. Evals, judges, golden sets, failure capture, guardrails, loops, regression gates, model upgrades, eval-vs-experiment routing, drift monitoring, MCP migration → Iterate. If genuinely ambiguous between stages, ask ONE clarifying question — never a questionnaire.

## Step 2 — Route

- **Shipped stage, no matching skill:** if the request lands in a shipped stage but none of its skills covers it (e.g. "write our GTM strategy" — Strategy ships no GTM author), say so honestly, name the skills the stage does ship, and generate nothing. A shipped stage is not a license to improvise its gaps.
- **Shipped stage:** invoke the matching stage skill(s). Multiple skills for one request run in sequence, each output gated before the next consumes it (e.g. interview-synthesizer → assumption-mapper: the assumptions are mapped from *gated* patterns, not raw drafts).
- **Mixed / multi-stage request:** run the stages in lifecycle order, each stage's output gated before the next consumes it. Parts no skill covers get the no-skill line; the covered parts still deliver.

## Step 3 — Enforce gates

Before relaying any stage skill output: run that skill's verification gates as written in its SKILL.md. On failure — fix the specific violation and re-run the gates, maximum 2 repair loops. Still failing → return a failure report (which gate, what violated it, what's needed to proceed) instead of the output. A failure report is a valid result; a gate-failing deliverable is not.

## Persona review (on request)

Any output — from a stage skill or provided by the user — can be routed through one or more reviewer personas on request ("review as skeptic", "run it past legal", "review as exec and designer"). Seven exist, in `.claude/agents/`: engineer-reviewer · designer-reviewer · executive-reviewer · skeptic-reviewer · customer-reviewer · data-analyst-reviewer · legal-reviewer. Rules:
- Each persona reviews through its own lens and carries the shared binary gate: every objection cites the specific line or element it attacks, or is labeled GAP. Free-floating criticism dies at the persona layer, same rule as strategy-review.
- Personas review; they never rewrite. Their objections return alongside the artifact; edits are the author's (or a stage skill's rerun).
- A requested persona that doesn't exist ("review as a pirate") gets the honest line naming the seven that do — never an improvised persona.
- Multiple personas run in sequence, each gated independently.

## Hard rules

1. No output returns to the user until its verification gate passes. No exceptions for "rough drafts" — roughness may reduce scope, never verification.
2. Never improvise a stage's gaps: all five stages ship, but a request no stage skill covers gets the honest no-skill line naming what the stage does ship — never generated output. A complete lifecycle is not a license to freelance.
3. Never bypass a stage skill's own hard rules or invent data to make a gate pass — gates verify reality, they are not formatting targets.
4. In multi-skill sequences, downstream skills consume only gated upstream output.

## Limitations

- All five stages route to real skills (40 total + 7 reviewer personas). Only the listed skills exist — uncovered requests get the no-skill line.
- Classification is a judgment call; borderline requests (e.g. "is this worth building?" spans Discovery and Strategy) get one clarifying question.
- Gates catch what they encode — fabricated quotes, unreconciled counts, naked numbers. They do not certify that a synthesis is *insightful*, only that it is verifiable.
- The orchestrator adds a verification pass on top of each skill's own self-audit; it does not replace human judgment on the gated output.
