# Security — PM Production Engineering OS

## Model

- **No secrets at rest.** The pipeline never writes a credential into code, config,
  or artifacts. Generated products receive their token via environment variable at
  deploy time (`APP_TOKEN`), generated fresh per deployment with `secrets.token_urlsafe`.
- **Constant-time auth.** Generated auth templates compare tokens with
  `hmac.compare_digest` and refuse to start unconfigured.
- **Parameterized SQL only at runtime.** Generated storage code binds every runtime
  value with `?` placeholders. Identifiers (table/column names) are baked at generation
  time from spec fields that the validator constrains to `[A-Za-z][A-Za-z0-9_]*`
  (rule `INVALID_IDENTIFIER`), so spec input cannot smuggle SQL into templates.
- **Isolated workspaces.** Each run builds in `runs/<id>/workspace/` with its own git
  repo and bot identity; the file writer refuses paths outside the workspace.
- **Security gate on every build.** The built-in scanner (named regex rules: hardcoded
  secrets, eval/exec, `shell=True`, pickle, SQL interpolation) runs as a required gate;
  a finding is a blocking review finding and a NO_MERGE.
- **Human gates.** Security-sensitive, production, and irreversible decisions require
  authenticated, digest-bound approval evidence admitted by Phase Zero. Historical
  V1 fixture approvals cannot authorize shipped execution.

## CI scanning and candidate profiles

CI installs the root Python dependency/toolchain graph from the hash-locked
`requirements.lock`. The core `pip-audit --strict --require-hashes` result is blocking;
missing advisory intelligence or dependency collection is a failure, never a warning.
GitHub Actions are pinned to immutable commit SHAs.

Every exact PR head also runs the committed no-ignore secret gate over source, config,
documentation, tests, evaluations, generated inputs, durable state, ignored run
artifacts, and tracked lockfiles. Only the path/line/fingerprint entries in
`security/secret-allowlist.json` may suppress synthetic fixtures; those entries are
named and expiring. Its redacted, candidate-bound report is retained as a CI artifact.

The security profile control plane in `pmpe.quality.security_profiles` composes secret,
SAST, SCA, license/pinning, SBOM, privacy, and architecture-boundary evidence into one
canonical exact-candidate report. Tool/ruleset identity and authenticated advisory
freshness are mandatory and freshness is rechecked at final disposition. The
repository root must be externally authenticated as the clean checkout at the report's
candidate SHA. Critical/high findings are non-waivable; medium/low waivers
must be named, scoped, authenticated, expiring, and bound to the exact candidate and
policy. Dependency inventory, product privacy intent, privacy-verifier results, and
architecture observations require trusted-authority attestations over their payload
digest and exact candidate SHA; the license allowlist and allowed architecture graph
come only from the digest-validated gate policy. The report converts directly to the
candidate-review `required_checks` EvidenceBundle item without inventing authentication
evidence.

CI runs `bandit -r src scripts/ci`, the complete deterministic security-profile
contract suite, and `scripts/ci/evaluate_security_profile.py` against the checked-out
candidate using the blocking pip-audit result. The composed report and its input
evidence are retained as exact-SHA artifacts. Intentional built-in-scanner fixture
matches use only exact path/line/rule/source-fingerprint entries with owner, rationale,
and expiry from `security/security-profile-policy.json`.

Accepted, reviewed Bandit findings:

| Finding | Location | Why accepted |
|---|---|---|
| B404/B603/B607 (subprocess) | gitops, quality, deployment, orchestration | Fixed argv lists, `shell=False` always, executables are git/python/ruff; inputs are pipeline-internal |
| B310 (urlopen audit) | deployment/local.py | URL is always `http://127.0.0.1:<port>` built locally |
| B608 (SQL string build) | stacks/stdlib_code.py | Flags the *template strings*; identifiers are validator-constrained at ingest, values are parameterized at runtime |

CI fails on HIGH-severity Bandit findings; the table above contains none.

## Reporting

Open a GitHub issue on `Abhillashjadhav/production-engineering-os` with the `security`
label, or email the repo owner. Do not include live tokens in reports.

## Known limitations (V1)

- Generated products use a single static bearer token (single-user scope, per spec);
  rotation = restart with a new `APP_TOKEN`. Documented in every generated README
  and `deploy/ROLLBACK.md`.
- The built-in scanner is pattern-based; it is a gate, not a substitute for a real
  SAST tool on production systems.
