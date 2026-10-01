# Offline whole-provider launcher

This opt-in launcher confines the **entire provider adapter process and its
descendants**, rather than only the generated candidate. It accepts a separate
provider bundle directory containing a regular Python entry file. It does not
connect to a live model, inherit credentials, allow network access, or make a
candidate release-eligible. The generic `--provider-command` remains a distinct
unconfined host-user path.

Example no-credential invocation, using an operator-provided bundle outside
the verifier source, approved inputs, candidate workspace and evidence root:

```bash
pmpe barebones run examples/barebones/e1-contract.json \
  --workspace /tmp/peos-candidate \
  --run-id offline-proof \
  --repository-root /tmp/peos-evidence \
  --approval-receipt examples/barebones/e1-approval-receipt.json \
  --expected-approver fixture-human \
  --provider-offline-bundle /tmp/peos-provider-bundle \
  --provider-offline-entry adapter.py \
  --provider-timeout 20
```

The adapter reads one bounded JSON object from stdin with `purpose` and
`request`, then writes one strict JSON object to stdout. Inside the isolated
mount namespace the entry is `/workspace/adapter.py`, executed with protected
`/usr/bin/python3 -I -B`. The supervisor admits only a system Python and its
parent path chain that the invoking provider user cannot write. The provider
bundle is read-only at `/workspace`; `/tmp` and `/tmp/home` are private tmpfs;
only system Python/runtime paths are read-only. The verifier source, approval
files, evidence root, candidate workspace, user home and host root are not
mounted. Bubblewrap uses `--unshare-all`, `--clearenv`, `--die-with-parent`, a
new session and the existing `prlimit`/output/timeout caps. The child receives
only a fixed `HOME`, `LC_ALL`, `PATH`, `PYTHONDONTWRITEBYTECODE`,
`PYTHONNOUSERSITE`, and `TMPDIR`. An inaccessible sandbox, malformed output,
nonzero exit or timeout fails closed; there is no plain-subprocess fallback.
Before launch, admission rejects any protected verifier, contract, receipt,
evidence or candidate path that overlaps a provider-visible system runtime
mount, including `/usr` and the small set of read-only `/etc` identity files.
A verifier installed under `/usr` cannot use this offline mode; it must run
from an operator-protected location outside those mounts.

The dedicated CI candidate-isolation job selects a malicious no-credential
provider fixture through the actual CLI. It tries host verifier, contract,
approval, ledger and marker write/chmod/rename; a descendant write; host PID
signal; inherited-FD inspection; environment-secret read; and network access.
It also supplies a valid bounded JSON response to check the useful path.
Mocked unit checks cannot replace that supported-host proof. This checkout's
local host cannot establish Bubblewrap isolation; no AppArmor or namespace
setting is changed here.

**Remaining live-provider requirements:** the adapter currently has no network
or credentials, so authenticated Codex CLI is not a supported invocation.
Enabling it needs an operator-controlled verifier/contract/receipt image or
identity, supervisor-only ledger writes, and a confined provider process tree
with narrowly authorized network/auth access that works inside that boundary.
No ambient host credential inheritance or automatic broad mount is permitted.
Provisioning an OS identity, protected roots or credentials is a separate
host/security action; the current run remains `HALTED` with
`PROVIDER_WRITE_ISOLATION_UNVERIFIED` even when the offline fixture works.
