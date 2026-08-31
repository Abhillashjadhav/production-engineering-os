# Phase C recorded tool-agent

PMPE now contains one concrete, exact-selected offline tool-agent path. It replays
the repository-owned `recorded-tool-agent-happy/v1` transcript, validates every
request and response against committed closed tool schemas, dispatches only the
support knowledge-base lookup and the pure one-sentence transform, and seals the
run into the existing `.pmpe` evidence ledger.

The public entry point is:

```python
from pmpe.recorded_tool_agent import run_recorded_tool_agent
```

Pass the exact Phase B contract and approval objects, an empty output directory,
a filesystem-safe run ID, the expected approver, and a timezone-aware trusted
clock. A successful result has `state == "RELEASE_READY"`, `cause == "PASS"`,
and `deployment_authority is False`. Inspect the returned `evidence_path` with
`pmpe.evidence.ledger.EvidenceLedger.open_existing`.

No ambient environment is accepted. The implementation has no network client,
provider credential path, subprocess call, arbitrary path input, filesystem tool,
write tool, dynamic code, recursive agent, cloud operation, approval authority,
or deployment operation. Any fixture, resource, transcript, schema, order, tool,
argument, result, or budget mismatch produces a hash-chained `HALTED` terminal.

This proves one deterministic offline recorded tool-agent implementation only. It
does not prove a shared template protocol, live model access, provider quality,
prompt-injection security in general, staging, deployment, or production readiness.

From a source checkout, run the bundled synthetic example with:

```bash
PYTHONPATH=src python examples/recorded-tool-agent/run.py /tmp/pmpe-recorded-example
```
