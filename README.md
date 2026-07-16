# pm-agent-os

An agentic PM operating system for Claude Code. One `/pm` command orchestrates the full product lifecycle — discovery, strategy, build, launch, iterate — through 40 skills, each with binary verification gates, tested fixtures, and a public PR-review record.

---

## The problem

Every PM operating system on the market generates. None of them verifies.

Prompt packs, skill collections, "PM copilots" — they all produce output that looks right: a clean synthesis, a confident market size, a tidy competitive matrix. Whether the synthesis quotes interviews that actually happened, whether the market size has a source, whether "competitor X has no API" was observed or assumed — nothing checks. The output ships, the decision gets made, and the error surfaces weeks later in a roadmap built on an invented quote.

The failure isn't generation quality. It's that nothing sits between the model and you to verify the output before you act on it.

## What's different

Every skill in this repo carries three things, written in this order:

1. **Binary verification gates.** Pass/fail checks defined *before* the skill's instructions were written. Example: interview-synthesizer blocks any output where a pattern cites fewer than 2 verbatim quotes, or where any quote fails a character-for-character match against the source transcript. A gate failure means the output does not reach you — it gets fixed or reported as a failure, never silently shipped.
2. **Tested fixtures.** Each skill has `tests/<skill>/fixtures.md` covering a three-gate harness: frontmatter lint (`tests/lint_skill.py`), trigger accuracy (fire / no-fire phrasings), and a known-answer run (fixture input → expected gated output).
3. **A PR-review record.** Every skill entered this repo through a pull request reviewed by `/pr-review` before merge, with the lint run before the verdict. Gates and fixtures are committed before instructions — the commit order shows it.

None of this asks to be trusted. The repo's own git history is the proof: open any skill's PR and read the review, the fixtures, and the commit sequence.

## Architecture

```
                        /pm  (orchestrator)
                              │
             classifies request → lifecycle stage(s)
                              │
   ┌───────────┬───────────┬──┴────────┬───────────┐
   │ Discovery │ Strategy  │  Build    │  Launch   │  Iterate
   │ 7 skills  │ 6 skills  │ 10 skills │ 5 skills  │ 12 skills
   │           │           │           │ +7 personas│
   └───────────┴───────────┴──┬────────┴───────────┘
                              │
                    reliability spine
      binary gates · tested fixtures · lint harness · PR-review record
```

The orchestrator routes; stage skills execute; the reliability spine verifies. No output crosses from a stage skill back to you until its verification gate passes.

## Install

```bash
git clone https://github.com/Abhillashjadhav/PM-agent-OS- pm-agent-os && mkdir -p ~/.claude/skills && cp -r pm-agent-os/.claude/skills/* ~/.claude/skills/
```

Skills follow the open SKILL.md standard — works with Codex, Cursor, Windsurf, and any agent that reads Agent Skills; the /pm orchestrator and one-command install are Claude Code-native.

## Watch a gate catch a failure

A real planted failure from this repo's own test fixtures — [`tests/regression-gatekeeper/fixtures.md`](tests/regression-gatekeeper/fixtures.md), committed before the skill it tests, like every fixture here.

**The setup:** a summarizer prompt was edited (marketing wants shorter summaries). A 14-case golden set exists, including F-4521 — a captured production incident where the model invented a meeting attendee. No regression runs have happened. Ship is planned for Friday.

**The failure the gate must catch** (planted in the fixture):

> "The edit only shortens output, low risk — ship Friday, run the goldens next week as follow-up."

A ship verdict with zero run results. Every PM has heard it; most have said it.

**What the gate forces instead:** `regression-gatekeeper`'s run-before-verdict gate blocks any ship opinion until golden results exist. The output becomes a run plan (all 14 cases, both sides), pre-committed verdict rules written *before* results (any captured failure passing its bad behavior through = automatic HOLD), a coverage flag (the "shorter summaries" requirement itself has zero golden coverage — it can't be certified, only regression-checked), and the only honest verdict available:

> `VERDICT: PENDING — no run, no verdict.`

The same pattern runs through all 40 skills: every fixture set carries a planted failure its gate must catch — an invented quote, a naked market-size figure, a scored disqualifier, a self-verifying loop. Open any `tests/<skill>/fixtures.md` and look for `PLANTED-FAILURE CASE`.

## Roadmap

| Stage | Skills | Status |
|---|---|---|
| Discovery | interview-synthesizer · feedback-pattern-miner · assumption-mapper · competitor-teardown · opportunity-sizer · jtbd-framer · research-brief | **Shipped** |
| Strategy | strategy-review · roadmap-reality-check · ai-feature-go-no-go · north-star-designer · build-buy-partner · pricing-tradeoff | **Shipped** |
| Build | model-complexity-router · builder-validator · prompt-optimizer-loop · context-auditor · pm-context-system · prd-to-eval · prototype-first-workflow · rag-vs-agent-architect · latency-ux-tradeoff · unit-economics-stress-test | **Shipped** |
| Launch | launch-checklist · gtm-brief · stakeholder-update · announcement-drafter · launch-retro — plus 7 reviewer personas (`.claude/agents/`: engineer, designer, executive, skeptic, customer, data-analyst, legal — "review as X" on any output, every objection line-cited) | **Shipped** |
| Iterate | eval-engine · llm-as-judge-designer · judge-calibration-auditor · golden-dataset-builder · failure-to-eval-capture · guardrail-designer · loop-designer · regression-gatekeeper · model-upgrade-evaluator · eval-vs-abtest-router · drift-monitor-designer · mcp-migration-auditor | **Shipped** |

All five stages shipped: 40 skills + 7 reviewer personas, every one gated, fixtured, and PR-reviewed before it landed — the PR history of this repo is the receipt. `/pm` routes the full lifecycle; requests no skill covers still get an honest no-skill line, never improvised output.

## PM Production Engineering OS (`pmpe`)

The downstream half of the system: where pm-agent-os produces validated product
requirements, **PM Production Engineering OS** turns an approved MVP specification
into tested, reviewed, deployable software — with engineering involvement only for
exceptions, high-risk decisions, or failed automated checks.

```bash
pip install -e ".[dev]"
pmpe run examples/taskflow_mvp_spec.yaml
```

One command executes the full lifecycle: validate → plan → architecture (with ADRs)
→ **tests before implementation** (a `confirm_red` step proves the generated tests
fail first) → implement → quality gates → PR record → deterministic review → safe
fixes → merge gate → local deploy → verified user journey → requirement-level
traceability report. High-risk decisions stop the run until `pmpe approve` records a
named human decision — the same verification-first discipline as the skills above,
applied to shipping code.

Start here: [docs/setup.md](docs/setup.md) · [docs/usage.md](docs/usage.md) ·
[ARCHITECTURE.md](ARCHITECTURE.md) · [example output](examples/sample_output/final_report.md)

## Credits

Harness patterns — the lint gate, the three-gate fixtures convention, and the PR-review agent — carried over from [AI-PM-essential-skills](https://github.com/Abhillashjadhav/AI-PM-essential-skills).

## License

MIT.

---

*Built by [Abhillash Jadhav](https://github.com/Abhillashjadhav) — GenAI PM. Evals, context engineering, agentic reliability.*
