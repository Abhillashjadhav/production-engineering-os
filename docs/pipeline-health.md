# PEOS pipeline health

Pipeline health is a statement about **one identified contract, source tree,
run and proof set**. A past green run, a passing fixture, a compiler result or
a hash-valid local ledger is not health for a later tree or a different
authority. Each required stage has one of these explicit statuses:

| Status | Meaning |
| --- | --- |
| `PASS` | The required check completed on the identified inputs and its proof was verified |
| `FAIL` | The check ran and its required outcome failed |
| `SKIP` | The check was deliberately omitted; it is not a pass |
| `BLOCKED` | A required capability, decision, authority or proof is unavailable |
| `PENDING` | The check has not completed yet |
| `UNKNOWN` | The result or evidence cannot be verified, including uncertain persistence |

The pipeline is **healthy** only when *every* required stage is `PASS` for the
same final tree, approved contract digest and applicable run, with zero
`FAIL`, `SKIP`, `BLOCKED`, `PENDING` or `UNKNOWN` stages. A `FAIL` makes it
unhealthy. Any other non-PASS state makes health incomplete, never green.
Record each stage's last proof link or digest, observed input revision, check
time and scope; missing proof is `UNKNOWN` or `BLOCKED`, not inferred `PASS`.

The core stages are: contract mapping and exact-digest owner approval; provider
generation; candidate and supervisor execution; every approved product case;
all required release conditions (including meaningful RED, approval-bound
before/after integrity, in-session provenance and accurate limitations);
independent provider-write confinement; normal unit, integration, UAT, type,
lint, build and supported-host CI; and the final outside-verifier decision.
An old check cannot be transferred across a changed tree or contract. A
test-only issuer/provider/sandbox must be labeled as such at each stage.

For the PMOS task-tracker reference currently checked in, the static mapping
and 14-case **test-only fixture UAT** have ordinary local evidence. The new
draft still lacks the owner's exact-digest approval and real provider run.
GATE-001 has no authorized live-run verdict; GATE-002 through GATE-005 have no
complete current proof. Protected provider-write isolation has no authenticated
live proof. The current engine's `HALTED` result is therefore the correct
release result even where the test fixture's 14 assertions pass. This page is
a health definition and limitation report, not a gate certificate.
