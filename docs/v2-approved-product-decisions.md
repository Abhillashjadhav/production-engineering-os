# V2 approved product decisions (locked)

These decisions are approved inputs to the V2 build. Implementation must not
reopen them; discovering a conflict produces a ProductChangeRequest, never a
silent reinterpretation.

- **PD-01 — PM Agent OS owns product intent**: problem, target user, product
  outcome, scope/out-of-scope, product requirements, acceptance criteria, North
  Star/leading metrics/guardrails, product trade-offs, release eval definitions.
- **PD-02 — Production Engineering OS owns engineering execution**: architecture,
  implementation planning, code and tests, integration, quality and security,
  code review, product-contract conformance, architecture simplicity, release
  verification, regression and drift monitoring, technical debt.
- **PD-03 — Contract immutability**: the approved ProductDecisionContract is
  immutable within an engineering run; never edited in place. Required product
  changes emit a ProductChangeRequest; a newly approved contract version starts a
  new run.
- **PD-04 — Architect authority**: reversible technical decisions only. Escalate:
  user-visible behaviour changes, product scope changes, acceptance-criterion
  changes, data-policy changes, commercial behaviour, irreversible architecture
  choices, destructive migrations, security-sensitive choices not explicitly
  approved, any choice that materially changes a product trade-off.
- **PD-05 — Agents are not architecture**: engineering specialists are AI
  execution agents, not components of the software; the Engineer Router selects
  the minimum agents needed to implement the architecture.
- **PD-06 — Four independent read-only assurance agents**: Code Reviewer, Product
  Conformance Reviewer, Architecture & Simplicity Reviewer, Eval Integrity &
  Drift Auditor. Same frozen candidate, fresh contexts, never edit files, blind
  to each other's findings until all four complete.
- **PD-07 — Reviewers never fix**: a separate Approved Findings Fixer modifies
  code only for ACCEPTED finding IDs; product-decision findings become
  ProductChangeRequests, never engineering fixes.
- **PD-08 — Draft PR only**: the system creates a branch and draft PR; it never
  auto-merges.
- **PD-09 — Deployment ladder**: local/test automatic after required checks;
  staging automatic after all gates; production requires a named, recorded human
  approval bound to the candidate digest; post-approval execution may automate
  canary verification and rollback. No real cloud-production adapter in this
  slice.
- **PD-10 — No Loop Engineering**: no self-prompting loops, general schedulers,
  background daemons, or a loop runtime in this repository.
- **PD-11 — Claude Code is the runtime**: no Anthropic/OpenAI/Codex SDKs, model
  API keys, or provider API calls in the product. The deterministic Python core
  owns state, contracts, validation, policies, evidence, and gates; Claude Code
  skills and project subagents own generative architecture, planning,
  implementation, and review work.
- **PD-12 — Codex is not runtime**: optional manual cross-model review after the
  branch is frozen only.

## Design principles (priority order)

correctness → reliability → simplicity → traceability → security → proven
extensibility → speed → cost. No AI theatre: no empty personas, no unverifiable
claims, no fake production data, no agent framework/microservices/queues/vector
DBs, no new dependency without a concrete requirement and ADR, no document that
is not consumed or verified, no code that exists to look comprehensive.
