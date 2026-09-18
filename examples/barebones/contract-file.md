# Frozen contract file entry

This entry loads the existing Template fields from a reviewed `bindings.json` and
invokes the existing compiler, model provider and runtime. Business identifiers
are data. Engine source and the contract schema do not change.

Install with Python 3.12 using the documented standard flow:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

With sibling PMOS and PEOS checkouts, run from PEOS:

```bash
.venv/bin/python examples/barebones/contract-file.py check \
  --packet ../pmos/reviews/task-tracker-v1 \
  --root PM-agent-OS=../pmos --root production-engineering-os=. \
  --freeze-digest sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2 \
  --output /tmp/task-tracker-check --authorized-host-fallback
```

Use a fresh output directory each time. Replace `check` with `build` to execute the
unchanged engine baseline, obtain live code through the session-file provider and
verify the candidate. `build` requires an active agent session: the agent reads each
`OUTPUT/handoff/call-*/request.json` and writes the adjacent `response.json` with
the same request_digest. The code response supplies `files`; the advisory response
is explicitly non-blocking. Requests, responses and elapsed times are retained.
The command waits at most 600 seconds per call, bounded by the existing provider.
There is no paid API or claim of headless generation.

Use `verify --candidate PATH` to recheck an existing candidate with the identical
approved criteria and source artifacts. It does not call a model. Compatibility
is rechecked before execution. A clean install can reproduce verification and the
CLI user journey without a model, while generating new code needs a live session.

The file loader rejects escaping paths, unprotected evaluator targets, missing
package initializers and unsupported bindings. Only existing action/measure
criteria are admitted here. Compatibility covers the runtime, resource limiter,
no-dependency profile, explicit fallback authority, bindings, receipt and exact
compiled plan. A compatible result means the engine can attempt and evaluate the
work; it is not delivery evidence.

Every action/measure process has all frozen artifacts and its materialized
acceptance files hashed immediately before and after execution. The outer command
also checks on exit and exception. A mismatch raises a fatal error; the next run
cannot silently update expected hashes. The new entry script's exact bytes are
recorded separately as engineering evidence and checked through the run.

The owner closed Bubblewrap attempts after user-namespace denial. This command
uses the authorized existing-container fallback and adds no isolation mechanism.
Absent: extra user/PID/mount/IPC/UTS/cgroup/network namespaces, read-only runtime
and candidate mounts, and private tmpfs/proc. Retained: process-group timeout,
prlimit AS/CPU/file-size/open-file/process caps, bounded output, existing candidate
path/security checks, immutable expected outcomes and artifact digest checks.
Root can still alter checkers/evidence or restore transient changes between hashes;
these observations are tamper evidence, not prevention. Receipt forgery is unfixed.
