# Tier-1 and PMOS launch contract

## Product promise

Turn an approved user outcome into bounded work, verified evidence, and a safe next action.
The system is not complete when it generates text; it is complete when the user can inspect
the outcome, evidence, open risks, and any action waiting for approval.

## North Star and gates

**North Star:** percentage of accepted work contracts completed with verified evidence by
the committed deadline.

Leading measures:

- time to first verified outcome;
- first-pass acceptance rate;
- evidence coverage;
- weekly repeat runs;
- rework avoided.

Guardrails:

- zero unauthorized external writes;
- zero silent failures or invented product decisions;
- bounded cost, time, retries, and tool permissions;
- no release-ready claim without exact-head CI and independent review;
- no autonomous merge, deployment, spend, deletion, or communication.

## Usability contract for every input

Every workflow must:

1. state the user problem and desired outcome;
2. ask only for missing decisions that change the result;
3. accept a guided input or a versioned file/API payload;
4. return a named outcome rather than only generated content;
5. expose evidence, uncertainty, cost, permissions, and failure state;
6. preview consequential actions and require exact-payload approval;
7. provide a synthetic starter and one runnable command;
8. work on a mobile review surface without hiding technical truth.

## Tier-1 workflow packs

### 1. Goal-to-Verified-Release

**Problem:** a product goal is separated from the evidence, implementation, and release
proof needed to complete it.

**Outcome:** an approved goal reaches an independently reviewed release candidate with
requirement, test, risk, and evidence traceability. Human release remains a separate action.

### 2. AI Eval and Release Gate

**Problem:** teams compare AI changes informally and discover quality, latency, cost, or
safety regressions after launch.

**Outcome:** golden cases and candidate trials produce a reproducible verdict, failure
taxonomy, regression pack, and approval recommendation.

### 3. Weekly PM Command Centre

**Problem:** commitments, risks, decisions, and customer signals are fragmented across
calendars, tickets, documents, and messages.

**Outcome:** one evidence-backed weekly state shows commitments, risks, decisions, owners,
and proposed updates. External writes remain drafts until approved.

### 4. Meeting-to-Decision Loop

**Problem:** meetings create notes but decisions and ownership are lost after the call.

**Outcome:** the user receives a pre-brief, evidence-backed decisions, open questions,
owners, deadlines, and approval-gated follow-ups that are tracked to completion.

### 5. Evidence-to-Roadmap-to-Release

**Problem:** customer evidence is summarized without an explicit, traceable product
decision or post-release outcome check.

**Outcome:** source evidence becomes options, an approved prioritization decision, bounded
delivery work, release proof, and a measured outcome report.

### 6. Issue-to-Draft-PR

**Problem:** coding assistance can change code without proving scope, tests, review, or
alignment to approved product truth.

**Outcome:** one ready issue produces an isolated branch, bounded implementation, exact-head
checks, independent review evidence, and one draft PR. Merge remains human-controlled.

## Five PMOS capabilities

### 1. Non-technical Guided Mode

A plain-language, accessible flow for intent, blocking questions, evidence, uncertainty,
costs, permissions, lifecycle state, and recovery. It consumes authoritative APIs and never
becomes a second control plane.

### 2. Mobile-first review and approval

Compact cards show the exact subject digest, proposed action, impact, reversibility,
evidence, permission scope, cost, and an expiry or explicit non-expiring policy. Approval binds the exact payload; any change
requires another approval.

### 3. Canonical PMOS bundle intake

Native bundle/manifest intake preserves stable IDs, provenance, approval state, metrics, and
unresolved truth. Ambiguous, unsupported, or lossy inputs are diagnosed and quarantined.

### 4. Governed live adapters

Calendar and product-worker adapters use least privilege, allowlists, budgets, idempotency,
and exact-payload approval. Workers may execute approved tasks but may not redefine product
truth. Connector-free local fakes remain available for first use.

### 5. Assurance and learning

An append-only event/eval registry binds contracts, tasks, artifacts, actions, retries, and
outcomes. Rollback must be verified. Outcome learning proposes new regression cases or a
ProductChangeRequest; it never silently changes approved behavior.

## Launch order

The implementation work may run in parallel, but admission remains dependency-aware:

1. Guided/mobile approval and canonical intake establish trusted product truth.
2. The six packs compile that truth into bounded task graphs.
3. Adapters execute only approved actions.
4. Evals, independent review, and rollback evidence decide readiness.
5. A named human approves release; the learning loop observes outcomes afterward.

## India-first operating requirements

- mobile review before desktop complexity;
- Hinglish and voice capture as input adapters, without translating away exact evidence;
- INR cost display, low-token modes, and BYOK/local-first deployment options;
- asynchronous approvals to reduce meeting load;
- PII/secrets redaction and explicit connector permissions;
- a connector-free synthetic first run targeting a verified outcome within 10 minutes.
