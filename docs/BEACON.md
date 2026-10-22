# Beacon integration

The canonical `pmpe` CLI automatically attempts optional Beacon recording around
its existing command dispatch. The same integration covers callers of
`pmpe.cli.main(argv)`, including the `legacy` compatibility routes.

## Install the optional adapter

Use the same virtualenv Python that runs `pmpe`:

```bash
.venv/bin/python scripts/install_beacon_adapter.py
```

If the project environment has a different path, use its Python instead.
The installer reads `beacon-source.lock.json` and installs the shared adapter
from a reviewed immutable commit in LinkedIn OS. The core runtime is not
vendored into this repository and remains an optional dependency.

Run the existing `pmpe ...` commands as usual. No report opens automatically.
Capture is best effort: an absent adapter or collector must not change command
returns, exception handling, approval checks, contract validation, or release
policy.

## Coverage

| Entry point | Coverage |
|---|---|
| Installed `pmpe` console command | Automatic run capture around command dispatch |
| `pmpe.cli.main(argv)` | Same dispatch wrapper and returned integer |
| `pmpe barebones ...` and compatibility/legacy CLI routes | Covered through the canonical CLI |
| PM Evals Web comparison, report generation, evaluation and ingestion POST endpoints | Automatic operation metadata around HTTP handling |
| `pm-evals` check/submit/flush/watch/linkedin/init commands | Automatic command-lifecycle metadata; long-running workers keep a single command record |
| Direct Python calls to engine/provider functions | Not implicitly wrapped; existing evidence behavior remains |
| PM Evals health/overview reads and static frontend requests | Deliberately excluded; no workflow work is performed |
| Standalone examples and CI scripts | Explicit optional launcher below |

For an inventoried command outside the canonical CLI, the shared runner provides
an explicit wrapper:

```bash
python3 scripts/run_with_beacon.py -- COMMAND ARGUMENTS
```

The record contains workflow lifecycle and exit-status metadata only. It does not
copy raw command arguments, contract content, prompts, model output, or secrets.
Existing PEOS evidence and decision identities are authoritative; optional
recording is not a new approval, deployment, or quality signal.

The optional launcher runs its command directly if the shared package is absent.
Use the virtualenv Python holding the adapter when recording is desired.
The PM Evals backend is separately packaged: install the same pinned adapter in
its virtualenv using the repository's installer. Its recording identity is the
server's current working directory; no request controls the recording destination.
Web records identify operations and transport success/failure, not evaluation
verdicts. They never inspect request bodies, uploaded filenames, headers, or
credentials. Health and read-only dashboard requests do not generate records.
Concurrent requests have independent IDs and do not mutate process environment.

When `--repository-root` is supplied to a CLI command, its value determines the
record's project identity; otherwise the current working directory is used.
This avoids silently treating all installed `pmpe` projects as one repository.

## Verification and rollback

Focused offline checks validate failed-adapter isolation and nonzero CLI returns.
No live model workflow, deployment, publication, or Mac installation is part of
those checks. Confirm native Beacon readback on the actual execution machine
before calling this deployed.

Rollback can remove the optional adapter or revert the CLI integration. Do not
delete contract/evidence stores. Existing runtime gates remain active throughout.
