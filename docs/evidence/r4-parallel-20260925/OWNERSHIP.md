# R4 parallel ownership, 2026-09-25

Status: in progress. This packet extends the existing R4 handoff. Separate-chat
workers are not addressable through this thread's agent controls. Their live
activity is unconfirmed; no coordination with that other thread is claimed.
Each worker owns an isolated branch. Original worktrees and public PR heads are
not modified by concurrent workers.

| Worker | Branch | Owns | Dependency |
| --- | --- | --- | --- |
| Architecture | `repair/r4-architecture-20260925` | Reproduced architecture failure, preserving source verification; concrete decision if repair requires a new trust boundary | Existing process source `c67716638731ba3be4ceeab20be6e6fdee631fd3` |
| Provenance | `docs/r4-provenance-20260925` | Historical C7-01 identity reconciliation and supporting evidence | Existing immutable Git objects and publication maps |
| Evidence review | `docs/r4-evidence-review-20260925` | Independent review of retained claims; permitted final-check inventory | Existing R4 source and evidence; final source review waits for architecture outcome |
| Fresh-run readiness | `docs/r4-fresh-readiness-20260925` | Reachable approval/freshness mechanisms and exact remaining decisions | Existing process and PMOS sources; draft regeneration waits for final source |
| Coordinator | `docs/r4-parallel-coordination-20260925` | Ownership, sequential integration, final checks, reviewable publication and accurate handoff | Completed worker results |

The three documentation branches start from
`a56c1c4671c34dd9748c30dd10cd1d0dcd6ecfc0` (public
`4c7f3ea0e1f72decfc7c5ecbae4fd84e5cebef9a`, tree
`2c46b0c1ac13119019fb14ff332f0d5807b2b548`). The architecture branch starts
from the process source (public `ccabeecc7346dffa7354e88c1deec53b1674428a`,
tree `872e53b7cb05bace2d825dca47ea7e27f78c7cf0`).

## Sequential work

1. Review each completed result and its exact source identity.
2. Integrate only compatible completed changes, preserving independent concerns.
3. Obtain independent review of any changed final source.
4. Run permitted checks needed by the actual change. Regenerate source-bound
   drafts/replay only if their source changes; never turn a replay into live proof.
5. Publish reviewable branches with exact local/public tree mappings and give the
   owner the remaining concrete decision or approval request.

## Constraints

- The prior automatically screened active external-cache execution and
  forged/rechained release-context rechecks remain UNVERIFIED. No rerun,
  rephrasing, alternate execution route, delegation or remote CI substitution.
- No scanner/policy allowlist weakening, frozen v1 changes, invented receipts,
  new paid API calls, GitHub merge or deployment.
- Runtime correctness, historical replay, fresh approved delivery and merge
  status remain separate. F-09 monitoring choice remains the owner's decision.
- Feature refs may retain reviewable source; existing PRs are not advanced into
  CI that would execute the previously blocked probes.
