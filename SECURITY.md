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

## CI scanning

CI runs `bandit -r src` and `pip-audit`. Accepted, reviewed findings:

| Finding | Location | Why accepted |
|---|---|---|
| B404/B603/B607 (subprocess) | gitops, quality, deployment, orchestration | Fixed argv lists, `shell=False` always, executables are git/python/ruff; inputs are pipeline-internal |
| B310 (urlopen audit) | deployment/local.py | URL is always `http://127.0.0.1:<port>` built locally |
| B608 (SQL string build) | stacks/stdlib_code.py | Flags the *template strings*; identifiers are validator-constrained at ingest, values are parameterized at runtime |

CI fails on HIGH-severity bandit findings; the table above contains none.

## Reporting

Open a GitHub issue on `Abhillashjadhav/production-engineering-os` with the `security`
label, or email the repo owner. Do not include live tokens in reports.

## Known limitations (V1)

- Generated products use a single static bearer token (single-user scope, per spec);
  rotation = restart with a new `APP_TOKEN`. Documented in every generated README
  and `deploy/ROLLBACK.md`.
- The built-in scanner is pattern-based; it is a gate, not a substitute for a real
  SAST tool on production systems.
