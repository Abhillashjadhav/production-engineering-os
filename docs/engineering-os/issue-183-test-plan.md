# Issue 183 — exact Phase B selection test plan

Authoritative issue: `#183`

Base commit: `6051d1fa11da92e9820def6ef1b839083f5e04bd`

## Outcome

Prove deterministic, exact, digest-bound selection for only the existing E1
implementation and one bounded recorded/replay tool-agent identity. The slice is a
contract/compiler decision and must not create a template interface, registry,
runtime provider, deployment path, or generalized tool framework.

## Meaningful red

The planning commit adds executable tests importing
`pmpe.barebones_selection`. Collection fails because that module does not exist.
Implementation is not authorized until that exact failure is observed on this
test-only commit.

## Required proofs

1. Both admitted type/version/content-digest triples compile three times to
   byte-identical plans.
2. Duplicate, unknown, aliased, inferred, digest-mismatched, or unavailable
   identities fail before runtime execution.
3. Capabilities come from one closed vocabulary and each capability binds existing
   acceptance criteria, one admitted verifier, and an immutable evidence subject.
4. Only recorded model mode is accepted; configuration cannot contain nested,
   unknown, secret-named, or credential-shaped data.
5. Tool identities, resource scopes, fixture identity, and every execution budget
   are exact and bounded.
6. Approval binds the canonical contract and selection subject, named approver, and
   expiry; mutation or expiry fails closed.
7. The public schema validates both positive fixtures and rejects ignored fields.

## Verification

- Focused unit tests for every positive and negative contract.
- Three-run deterministic byte comparison.
- Published-schema validation and canonical round-trip.
- Ruff format/lint and strict mypy.
- Full exact-head CI and a fresh independent schema review before Phase C.
