---
name: prompt-optimizer-loop
description: "Build-stage skill: improves an existing prompt one mutation per round against a scoring checklist, logging every round and reverting anything that doesn't score better. Use when the user has a prompt that underperforms — 'improve this prompt', 'tune my extraction prompt', 'this prompt works 60% of the time, make it reliable', 'optimize it one change at a time' — or when /pm routes a prompt-repair request here. Do NOT use to author prompts from scratch (no baseline to mutate), for knowledge questions about prompting, for artifact generation with frozen criteria (builder-validator), or for model selection (model-complexity-router)."
argument-hint: "<the prompt + what good output looks like (checklist or examples) + a test input>"
---

# Prompt Optimizer Loop

One mutation, one score, keep or revert. Attribution is the whole method — change two things and you learn nothing.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — One mutation per round:** each round applies exactly one named, diffable change (add a constraint · add/replace an example · restructure one instruction · tighten one ambiguity). A multi-change round fails the gate even when the score improves — improvement without attribution is luck, not learning.
- **G2 — Score logged per round:** every round records mutation, score before, score after, keep/revert. Scores come only from the checklist run against the test case — no unscored "feels better" rounds.
- **G3 — Revert on non-improvement:** a tied or lower score reverts the mutation; the next round mutates from the last-kept version. The log shows reverted rounds as reverted, never silently rewound.

## Steps

1. **Establish the harness.** Need three things: the baseline prompt, a scoring checklist (binary items, 1 point each — derive one from the user's description of "good" if not provided, and confirm it), and at least one test input. Score the baseline first; that's round 0.
2. **Diagnose before mutating.** Which checklist items fail, and what in the prompt plausibly causes each miss? The next mutation targets the highest-value failing item — not the easiest edit.
3. **Mutate once.** Name the mutation type and show the diff. Resist bundling: an example AND a constraint is two rounds.
4. **Re-score** against the same checklist and test case. Same inputs every round — changing the test mid-loop invalidates the log.
5. **Keep or revert, log it.** Improved → keep, next round builds on it. Tied/worse → revert, log the dead end (dead ends are data: they localize what doesn't matter).
6. **Stop** on: full score · 2 consecutive non-improvements (plateau) · 5 rounds. Deliver the final prompt, final score, and the round log — the log is the deliverable that makes the result trustworthy.

## Output format

```
ROUND LOG (checklist: 5 items · test case: fixture call)
R0 baseline — score 2/5 (misses: resolution status, action items; over 120w)
R1 +constraint "≤120 words, bullet action items with owners" — 2/5 → 4/5 — KEEP
R2 restructure: move status line to top — 4/5 → 4/5 — REVERT (tie; back to R1 version)
R3 +example (one worked summary) — 4/5 → 5/5 — KEEP
STOPPED: full score.
FINAL PROMPT: [R3-kept version]
GATE CHECK: G1 pass (1 mutation/round) · G2 pass (4 rounds, 4 scores) · G3 pass (R2 reverted)
```

## Hard rules

1. One mutation per round, no exceptions — including "it obviously needs both". Two improvements bundled = revert and replay as two rounds.
2. Never score without running the checklist against the test case. The checklist is the only rubric; vibes don't move the log.
3. Never build on a non-improving mutation. The last-kept version is the only valid base.
4. Never edit the checklist mid-loop to make a mutation look better — the checklist freezes at round 0 (sharpen it only by restarting the loop, stated).

## Limitations

- Single-test-case scoring can overfit the prompt to that case; the skill flags when a kept mutation looks case-specific and recommends a second test input.
- Five rounds of single mutations explore a narrow path — a prompt that needs a ground-up rewrite will plateau early, and the plateau stop says exactly that.
- Checklist quality bounds everything: binary items the user didn't want optimized produce a faithfully optimized wrong prompt.
- Scores measure checklist compliance on the test input, not production reliability — a held-out eval (prd-to-eval territory) is the next step for high-stakes prompts.
