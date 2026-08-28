# Personal Execution OS governed workflow packs

This vertical proves that the same contract, task-graph, execution, evidence, and approval
mechanism can run personal knowledge-work workflows without weakening the Production
Engineering OS boundary.

## One-command demo

```bash
pmpe personal-workflows quickstart --output /tmp/pmpe-personal
```

The command generates a schema-valid synthetic request and runs 21 independent workflow
packs in one parallel batch. The six Tier-1 packs are:

1. **Goal-to-Verified-Release** — acceptance evidence, parallel Codex packets, independent
   verification, and a digest-bound release verdict.
2. **AI Eval and Release Gate** — frozen golden cases plus deterministic quality, latency,
   cost, and safety gates.
3. **Weekly PM Command Centre** — ranked commitments, requested actions, schedule conflicts,
   and draft updates.
4. **Meeting-to-Decision** — pre-brief, prior decisions, owner-complete actions, and an exact
   follow-up draft.
5. **Evidence-to-Roadmap-to-Release** — claim provenance, an explicitly human-selected option,
   delivery requirements, and release checks.
6. **Issue-to-Draft-PR** — issue scope, impact paths, dependencies, deterministic checks,
   candidate digest, and an exact draft-PR payload.

Nine Tier-2 operational-completion packs and six Tier-3 builder/learning packs are documented
in [tier2-tier3-workflow-packs.md](tier2-tier3-workflow-packs.md).

The run writes:

- `personal-work-contract.json` — approved goal, outcome metric, leading metrics, and
  guardrails;
- `task-graph.json` — bounded capabilities, prohibited actions, dependencies, and definitions
  of done;
- `workflow-results.json` — output and evidence digest for every worker;
- `evidence-ledger.json` — source identity, observation time, URI, and content digest;
- `approval-outbox.json` — calendar, email, merge, and deployment actions that were drafted
  but not executed;
- `mobile-review.json` — compact workflow and exact-approval cards for narrow screens;
- `personal-execution-report.json` — the joined outcome and evidence digest.
- `workflow-catalog.json` — versioned product, input, permission, check, approval, and recovery
  metadata for the extended packs.

No email is sent, calendar is changed, code is merged, or production is deployed. Those
actions remain `PENDING_APPROVAL`.

To separate data generation and execution:

```bash
pmpe personal-workflows generate --seed 2026 --output /tmp/pmpe-personal
pmpe personal-workflows validate \
  --input /tmp/pmpe-personal/synthetic-workflow-request.json
pmpe personal-workflows run \
  --context /tmp/pmpe-personal/synthetic-workflow-request.json \
  --output /tmp/pmpe-personal
```

Generate a starter for one pack:

```bash
pmpe personal-workflows starter \
  --pack issue-to-draft-pr \
  --output /tmp/pmpe-issue-starter
```

The admitted user-input contract is
`src/pmpe/schemas/personal_workflow_request.schema.json`. Selected workflows must have an
exactly matching input block. Every evidence source carries content plus its canonical digest;
unknown or tampered references fail before execution. A North Star that counts prompts, tasks,
logins, or another activity is rejected.

## PMOS decision-authoring seam

The missing PMOS layer is now represented by three commands:

```bash
pmpe contract draft --answers answers.json --output /tmp/pmos-authoring
pmpe contract approve \
  --draft /tmp/pmos-authoring/contract-draft.json \
  --expected-digest sha256:<reviewed-digest> \
  --approver <named-product-owner> \
  --approved-at 2026-08-19T12:00:00Z \
  --output /tmp/pmos-approved
pmpe contract handoff \
  --contract /tmp/pmos-approved/contract-approved.json \
  --receipt /tmp/pmos-approved/approval-receipt.json \
  --expected-approver <named-product-owner> \
  --run-dir /tmp/pmpe-engineering-run
```

An incomplete or inconsistent answers file produces `blocking-questions.json` and exits
with code 3. The builder does not create an incomplete schema-valid fiction. Approval is
bound to the exact reviewed draft digest; any change requires fresh approval.

## Current boundary

This is a local deterministic runtime. It accepts user-authored JSON as well as labelled
synthetic starters, but it prepares rather than dispatches Codex packets and external actions.
Connector writes, remote PR creation, model release, merge, and deployment require a separate
adapter plus approval of the exact outbox payload. The kernel stays provider-independent, and
PEOS remains the authority for engineering verification.

## Governed runtime assurance

Issue #121 adds five runtime capabilities without widening that authority boundary:

| Capability | Enforced runtime rule | Offline proof |
|---|---|---|
| Calendar adapter | A write requires a named approval bound to the exact action, event, changes, and pre-write calendar digest; approvals are single-use. | `FakeCalendarConnector` |
| Product-worker adapter | The request is bound to contract/task/artifact digests; steps and output bytes are budgeted; every capability is allowlisted; product-truth-shaped output is rejected. | `FakeProductWorkerConnector` |
| Event/eval registry | Every canonical JSONL record names contract, task, and artifact digests and extends a verified digest chain; same-process parallel appends are serialized. | `EventRegistry` |
| Retry and rollback | Only classified transient failures retry, attempts are bounded, and failed work is never called rolled back until the target digest is positively verified. | `FakeRecoverableConnector` |
| Outcome learning | Failed evaluations produce digest-bound `PROPOSED` regression cases only; the loop has no API for installing or editing a regression suite. | `OutcomeLearningLoop` |

Run the full local demonstration:

```bash
pmpe personal-runtime quickstart --output /tmp/pmpe-personal-runtime
```

The command writes `synthetic-runtime-input.json`, `runtime-events.jsonl`,
`regression-proposals.json`, and `runtime-assurance-report.json`. A reusable synthetic input
is also committed at `examples/personal-runtime/synthetic-runtime-input.json`.

### Connector boundary

`CalendarConnector`, `ProductWorkerConnector`, and `RecoverableConnector` are protocols, not
provider implementations. A future real connector must preserve these contracts and add its
own authentication, provider idempotency, durable approval-consumption store, and
cross-process append coordination. This issue deliberately supplies only deterministic local
fakes and performs no network or provider writes.
