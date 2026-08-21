# Issue #70 — security, privacy, supply-chain, and architecture gates

## Exact base and dependency

- Base: `1045439ccf252794e2288495e8b44df3c8e497d2`
- Depends on merged issue #69 evidence/merge admission.
- One issue, one branch, one primary draft PR.

## Outcome

Every candidate receives one deterministic, exact-SHA security profile. The profile
either proves every required gate or blocks promotion. It never converts a missing
scanner, missing privacy proof, stale advisory source, or self-asserted waiver into a
pass.

## Implementation slices

1. Commit this plan and red tests before implementation.
2. Add normalized, value-redacted finding and policy models.
3. Add a no-ignore secret scan over source, config, docs, tests, evals, generated
   inputs, durable state, ignored run artifacts, and tracked lockfiles. Permit only
   exact path/line/fingerprint synthetic fixture allowlists; reject broad directory
   and lockfile exclusions.
4. Add pinned tool/ruleset identity and authenticated advisory snapshot admission.
   Recheck freshness with trusted live time after source authentication.
5. Add SAST/SCA/license-pinning/SBOM, privacy/retention/deletion, and ArchitecturePack
   boundary gates.
6. Add exact, named, expiring, authenticated medium/low waiver admission. Reject all
   high/critical waivers.
7. Compose every required profile into one digest-bound report and EvidenceBundle
   item. Missing/unsupported gates are blocking.
8. Pin CI verification tools; make core dependency audit and the complete profile
   blocking. Invoke the composed evaluator against the clean exact-SHA checkout and
   retain its canonical report with the dependency-audit input.
9. Run focused and full deterministic verification, independent exact-head review,
   finding disposition, ready revalidation, and protected merge.

## Evidence invariants

- Candidate and policy SHA/digests bind every finding, waiver, advisory snapshot,
  SBOM, and final report.
- Findings contain fingerprints and redacted messages, never secret values.
- Advisory evidence records source, authority, snapshot digest, generated/fetched/
  evaluated times, expiry, and authentication proof.
- The exact tool version and ruleset digest are mandatory; ranges and `latest` fail.
- Security/privacy critical and high findings are non-waivable.
- A stale but refreshable snapshot enters fresh-verification-required; unavailable or
  unverifiable intelligence blocks without pretending to be a vulnerability pass.
- Architecture policy version/digest changes invalidate the candidate profile.
- The repository snapshot is authenticated independently before any local scan result
  can claim the candidate SHA.
- Advisory, secret-allowlist, SAST false-positive allowlist, and waiver authority is
  rechecked at the single final disposition time.
- Privacy deletion, retention, and emitted-telemetry claims come from an executed
  exact-candidate verifier artifact, not from copied intent fields.
- Architecture observation resolves relative and absolute imports before comparing
  the observed layer graph with trusted policy.

## Rollback

Before merge, close the draft PR and remove only the issue-scoped branch through an
explicit recoverable operation. After merge, revert the squash commit. A rollback may
not weaken an in-flight approved contract or reuse stale evidence.
