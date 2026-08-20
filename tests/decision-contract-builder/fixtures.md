# Decision Contract Builder fixtures

## Trigger cases

- `/pm turn this approved product brief into an engineering contract`
- `Publish the PMOS decision and hand it to PEOS`
- `What product questions still block this build?`

## No-trigger cases

- `Fix this failing unit test`
- `Explain what a ProductDecisionContract is`
- `Resume the already locked engineering run`

## Planted failure

The brief has a North Star of "number of tasks created" and FR-002 has no acceptance
criterion. The skill must return blocking questions for the activity metric and missing
coverage. It must not publish or approve a contract.

## Known-answer run

A complete answers file produces `DRAFT_READY_FOR_APPROVAL`, a canonical draft digest,
and a source map. Approval requires the exact digest and a named approver. A changed scope
after review fails approval. A successful approval produces a runnable contract and an
approval receipt before PEOS handoff.
