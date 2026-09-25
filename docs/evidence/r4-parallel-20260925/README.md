# R4 parallel follow-up — decisions still required

Four independent workstreams investigated the remaining R4 items concurrently.
Historical provenance is reconciled and the retained packet is independently
checked. **Runtime repair and fresh approved delivery are not complete.** The
architecture failure persists; GATE-004 has no reachable PASS path in current
source; two previously screened final rechecks remain UNVERIFIED.

The separate chat's workers could not be contacted through this thread. This
work used isolated branches and did not advance the existing PRs. The
[ownership record](OWNERSHIP.md) makes that boundary explicit.

| Workstream | Result | Evidence |
| --- | --- | --- |
| Historical provenance | CLOSED: both historical local commits map to verified public Git trees; no frozen claim was rewritten. | [Provenance reconciliation](PROVENANCE.md) |
| Retained evidence | Source, manifest, archive and reported replay outcomes agree. This is evidence validation, not a new execution or runtime authentication. | [Independent review](review/ACCEPTANCE.md) |
| Architecture | BLOCKED: existing bytecode guard conflicts with the unchanged architecture policy. Removing its broad module scan without complete import admission would weaken coverage. | [Architecture decision](https://github.com/Abhillashjadhav/production-engineering-os/blob/3b8a8f20c899572e1e465634ffce6571462aa65b/reviews/r4-architecture-20260925/DECISION_REQUIRED.md) |
| Fresh-run readiness | BLOCKED: approval alone is insufficient. Current GATE-004 never returns PASS, and retained validation rejects a claimed PASS. | [Readiness assessment](readiness/READINESS.md) |

## Concrete execution decision

Recommended approval: **implement a controlled source-only entry for typed
process-gated runs, using the existing migration entry first; reject unprepared
direct library calls before provider or workspace side effects.** The entry
must admit the engine, adapter and helpers before execution and establish a
complete module inventory. Preserve the existing protection against active,
future and local caches. Preserve approved ungated behavior and the protected
scanner/policy. No scanner exception or self-asserted clean flag is acceptable.

This changes the supported calling contract: existing callers that construct
providers and import helpers in an arbitrary interpreter cannot claim the new
source-only guarantee. They need the reviewed entry or a separately justified
admission mechanism. The architecture proposal contains affected callers,
acceptance criteria and the remaining design proof; it does not claim that a
complete loader mechanism has already been implemented or verified.

The repository's `AGENTS.md` BAR question 6 requires an owner decision before
adding that execution surface. The approval requested here is implementation
scope only; it is not contract, release, merge or deployment approval.

Fresh delivery has a separate prerequisite: establish a trusted per-invocation
generation-proof capability. The current subscription/command wrappers do not
establish it. Approve a bounded design using existing access, or defer fresh
delivery while leaving GATE-004 NOT_EVALUATED. No paid API or provider selection
is implied. An operator label, timestamp, local UUID or saved response cannot
be promoted into independently verified fresh generation.

## Sequence after the decision

1. Implement and verify the approved source-entry contract. A freshness design
   can proceed independently after its own scope decision.
2. Independently review the finalized implementations, integrate compatible
   results, then run permitted checks against their exact final source.
3. Regenerate source-bound drafts and retained replay only after that source is
   final. This session changed no runtime, so it did not regenerate either.
4. Resolve the remaining verification restrictions and CI/review gates through
   an approved route. The previous screening-stopped checks are not rerun here,
   directly, under another name, by another worker, or through remote CI.
5. Only when fresh-generation proof is available, present the exact revised
   contract for owner approval, freeze its identities, then run the fresh phase.

## Evidence limits and publication

The retained task-store result remains **14/14**, 56 process records,
GATE-001/002/005 PASS, GATE-003/004 NOT_EVALUATED and terminal **HALTED**. The
current GATE-003 evidence records 117 digest observations; the migration's
historical boundary log separately records 114. There were zero fresh model
calls in this follow-up. The earlier historical-runtime authentication limit
is unchanged.

The architecture branch adds a static failing regression and benign metadata
fixtures: nine metadata cases and one existing deterministic process fixture
pass. These do not replace the screened active-cache execution or rewritten
release-context rechecks. No architecture GREEN or final source approval is
claimed. Neither this packet nor the fixture results authorize a merge.

Review-only branches retain exact snapshots without advancing PR-triggered CI
that would run the screened probes. Publication mappings identify local and
public Git trees separately. F-09 remains the owner's monitoring choice.

The independent reviewer approved the decision packet at local `4779c8d`
(public `a2401127`, identical tree) for documentation accuracy only. This
receipt addition records that completed review; it is not runtime approval.
See [review receipt](independent-packet-review.json),
[packet validation](final-validation.json), and
[exact publication mappings](publication-map.json).
