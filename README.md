# production-engineering-os

**PM Agent OS decides what should be built and verifies product reasoning. Production Engineering OS turns that approved decision into verified software and keeps it conformant.**

This repository hosts both planes of that boundary:

- **PM Agent OS** — one `/pm` command orchestrates the product lifecycle (discovery, strategy, build, launch, iterate) through 40 skills, each with binary verification gates, tested fixtures, and a public PR-review record.
- **Production Engineering OS** (`pmpe`) — takes an APPROVED ProductDecisionContract from that plane and runs it through an evidence-ledgered engineering pipeline: architecture, planning, routed specialists, independent review, executed traceability, and a deployment ladder that ends in a draft PR — never an auto-merge, never a silent production push.

The seam between them is a single immutable artifact: the digest-locked contract. Product changes flow back as ProductChangeRequests, never as mid-run edits. Start with [docs/v2-production-engineering.md](docs/v2-production-engineering.md).

## Production Engineering OS (`pmpe`)

### Try the verified demo

Prerequisite: Python 3.11 or newer (`python3.12` is used below).

```bash
git clone https://github.com/Abhillashjadhav/production-engineering-os.git
cd production-engineering-os
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pmpe demo --base-dir /tmp/pmpe-demo
cat /tmp/pmpe-demo/demo-report.json
```

The demo is a labelled synthetic run. It locks a sample contract, catches planted
security, traceability, complexity, trajectory, and drift failures, applies its
accepted fixes, reruns tests, and writes the evidence-backed report above. It does
not generate an arbitrary product, open a real pull request, or deploy to cloud.

The live contract-admission path is available for operator-driven runs:

```bash
pmpe eng start --contract examples/v2-demo/contract.json --run-dir runs/demo
```

- **Contract in, verified handoff out.** `pmpe eng start` refuses anything that is not an APPROVED, unblocked contract and locks a canonical digest; every later step re-verifies it and fails closed on mutation. The `draft-pr` stage records a handoff reference. It does not open a remote pull request.
- **Claude agents propose, the Python core disposes (PD-11).** Generative work belongs to the agents in `.claude/agents/v2-*.md` (driven live by the `/production-engineer` skill); admission, state, gates, and evidence belong to deterministic Python. No model SDKs or API keys anywhere in the product.
- **Assurance that can prove itself.** Four independent reviewers — read-only by construction (tool lists) and by runtime proof (tree snapshots) — examine the same frozen candidate; findings live in an enforced lifecycle; the fixer touches only ACCEPTED ids; the verifier is never the fixer.
- **Coverage means execution.** Traceability counts only executed, passing tests — markers, skips, and import-dead modules count against coverage, not toward it.
- **Evals as tripwires.** Agent evals share the engine's admission validators, trajectory evals audit the evidence ledger (TRAJ-01..14), and drift compares against a baseline where any new hard-gate failure is an automatic HOLD.
- **Production is a human decision.** local/test are automatic after checks, staging after all gates, production only with a named approval bound to the exact candidate digest — and even then execution is fixture-mode only; there is deliberately no cloud adapter.

The V1 single-command executor is retained only as an explicit test fixture and is
not installed or registered by the CLI. Phase Zero is the sole admissible shipped
lifecycle authority; read-only access to historical V1 state remains documented in
[docs/usage.md](docs/usage.md).

---

# PM Agent OS

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

## Credits

Harness patterns — the lint gate, the three-gate fixtures convention, and the PR-review agent — carried over from [AI-PM-essential-skills](https://github.com/Abhillashjadhav/AI-PM-essential-skills).

## License

MIT.

---

*Built by [Abhillash Jadhav](https://github.com/Abhillashjadhav) — GenAI PM. Evals, context engineering, agentic reliability.*
