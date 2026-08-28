# Issue 185 — protected security-verifier bootstrap test plan

Authoritative issue: `#185`

Base commit: `05d01f76116cc746c4ee19f13601b40e7afbd98e`

## Outcome

Run the required security check from a protected `pull_request_target` workflow.
The pull-request checkout is only input. During the one-time #133 bootstrap, every
file that can execute as part of the verifier and its hash-locked toolchain must
match an independently reviewed protected manifest. Once the verifier exists on
the protected base, the workflow must always execute that base copy.

## Meaningful red

The planning commit adds executable tests that import
`scripts.ci.verify_trusted_security_bootstrap`. Collection fails because that
protected verifier and its workflow do not yet exist. No implementation is admitted
before this missing-module failure is recorded at the exact planning head.

## Required proofs

1. Exact protected-base and candidate Git identities are authenticated.
2. Bootstrap mode accepts only PR #133 and an exact, unexpired, self-digested
   manifest covering the full `src`, `scripts/ci`, `requirements.lock`, and
   `pyproject.toml` execution surface.
3. Missing, modified, extra, symlinked, or non-regular bootstrap files fail before
   candidate Python can execute.
4. A complete protected-base verifier always wins; candidate verifier changes are
   never selected. A partial protected verifier fails closed instead of falling back.
5. The workflow is sourced with `pull_request_target`, has read-only permissions,
   checks out base and head separately, disables candidate credentials, and exposes
   no merge, deployment, or secret authority.

## Verification

- Focused bootstrap/workflow tests.
- Full CI, Ruff, strict mypy, and a fresh independent exact-head review.

