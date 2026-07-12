# PRD — pm-agent-os Stage 1: scaffold, identity, Discovery stage

**Date:** 2026-07-07
**Owner:** Abhillash Jadhav
**Status:** In build

## Problem
Every PM operating system on the market generates; none verifies. Outputs look right and ship wrong. pm-agent-os is the PM OS where every output passes a binary verification gate before the user sees it.

## Success criteria (ship gates for stage 1)
1. Template plugins and marketplace.json removed; harness (pr-review command, reviewer agent, lint_skill.py, three-gate fixtures convention) kept and verified working.
2. README is the launch asset: positioning → problem → what's different → architecture → install + open-standard compatibility line → gate-demo placeholder → 5-stage roadmap → credits. Flat practitioner tone, zero hype words, every claim inspectable in the repo.
3. `/pm` orchestrator routes Discovery, returns "stage not yet shipped" for the other four stages, and enforces: no output returns until its verification gate passes.
4. Seven Discovery skills shipped, each with gates + fixtures written BEFORE instructions (commit order is evidence), each passing the three-gate harness before its PR.

## Discovery skills and their binary gates
| Skill | Transform | Gate |
|---|---|---|
| interview-synthesizer | transcripts → patterns | every pattern cites ≥2 verbatim quotes; zero invented quotes |
| feedback-pattern-miner | raw feedback → ranked themes | theme counts reconcile to input total |
| assumption-mapper | idea → assumptions ranked by risk | each tagged testable/untestable with a proposed test |
| competitor-teardown | product → structured teardown | every claim marked observed vs. inferred |
| opportunity-sizer | TAM/SAM/SOM | every number carries a stated source or is labeled estimate |
| jtbd-framer | feature idea → JTBD statements | zero solution language in job statements |
| research-brief | question → structured research plan | each method mapped to the decision it informs |

## Design intent
Tactical workflow mechanics (auto-firing triggers, self-audit loops, context economics) follow the coaching patterns from prior plugins; the judgment layer (what counts as evidence, gate design, claim verification) follows the evals/reliability discipline.

## Ship plan
8 PRs total: one for scaffold + README + orchestrator, one per Discovery skill. Every PR through `/pr-review`; no merge without APPROVE. Final PR left open for owner review.
