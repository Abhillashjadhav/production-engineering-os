# Phase 0 — actual in-session provider handoff

Issue: [#198](https://github.com/Abhillashjadhav/production-engineering-os/issues/198).
Base: `dd4271b70fcb9cb5b9dd279fe516c2fe50806751`.

The owner approved the current agent session as the model responder. The new
`examples/barebones/session-file-provider.py` implements the existing command
JSON interface; no engine, contract schema, approval check or evaluator changed.

## Observed results

- Six standard-library transport tests passed on the first implementation attempt.
  The pre-implementation round-trip test failed because the provider file was absent.
- A direct command handoff completed: [record](round-trip.json), with its original
  request, response, emitted output and call timing under `handoff/`.
- A second handoff used the existing, unmodified
  `pmpe.cli.barebones_cmd.CommandModelProvider.invoke`:
  [record](command-wrapper-round-trip.json), with its files under `command-wrapper/`.
  It returned the matching request digest and the session-authored completion.
- Each request included a fresh marker. The orchestrating assistant read the
  emitted request before writing the adjacent response. The response was not
  produced by a fixture responder or replayed from an earlier completion.

The JSON records contain the measured elapsed values. They include orchestration
and file-handoff delay; they are not inference-latency benchmarks.

## Reproduction

Transport checks (responses here are test fixtures, not model evidence):

```bash
python3 -m unittest discover -s tests/unit -p test_session_file_provider.py -v
```

Installed in this run using the documented standard environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

The install completed. Installing the separate development tools with
`.venv/bin/python -m pip install --timeout 15 --retries 0 pytest==9.1.1 ruff==0.16.4`
failed with `No matching distribution found for pytest==9.1.1`. No dependency pin
was changed. The six new tests ran using `unittest`; this is not a claim that the
repository-wide pytest or lint gates passed.

For an actual session handoff, run the following command in a yielding terminal:

```bash
.venv/bin/python - <<'PY'
import shlex, sys, uuid
from pmpe.cli.barebones_cmd import CommandModelProvider
from pmpe.contracts.canonical import canonical_digest
request = {
    'instruction': 'Explain what an approved product contract controls; include the marker.',
    'marker': 'SESSION-P0-' + uuid.uuid4().hex,
}
request['request_digest'] = canonical_digest(request)
command = shlex.join([
    sys.executable, 'examples/barebones/session-file-provider.py',
    '--handoff-dir', '/tmp/pmpe-session-handoff',
])
print(CommandModelProvider(command, 240).invoke(purpose='advisory_review', request=request))
PY
```

The active agent must read the new `call-*/request.json` and write an adjacent
`response.json` containing that exact `request_digest` and a newly generated
`summary`. Publish it atomically: write `response.tmp`, then rename it to
`response.json`. For a `code` request, respond with the existing `files` mapping
instead. The shim adds truthful transport metadata, retains the raw response and
emitted output separately, and uses the existing `PMPE_PROVIDER_TIMEOUT_SECONDS`
budget. Missing, malformed, stale or mismatched responses do not produce success.

## Limits

This demonstrates the provider transport and a real response from this agent
session. No task-tracker implementation or approved task-tracker acceptance run
has occurred. The model's exact identity and token usage are not exposed here;
the metadata says `session-model-unreported` and no per-call price is invented.

Reproduction requires an active agent session. There is no headless model backend,
paid API call, CLI authentication dependency, or independent evaluator established
by this adapter. The shim does not protect approval or evaluator authority; those
remain separate audit and acceptance requirements.

## Owner-requested lint correction

The first provider PR check reported UP017, two E501 findings, I001 and RET503.
The owner authorized a new correction with a two-attempt limit. Attempt 1 cleared
all five findings: use `UTC`, wrap two statements, normalize import spacing and
explicitly raise the same unittest failure exception on a missing handoff.
No transport assertion or acceptance outcome changed.

Ruff 0.16.4 installed successfully on this later attempt; the earlier dev-install
failure remains historical evidence, not a claim that the package is unavailable.
Commands run from the provider worktree:

```bash
../peos/.venv/bin/ruff check examples/barebones/session-file-provider.py tests/unit/test_session_file_provider.py
../peos/.venv/bin/ruff format --check tests/unit/test_session_file_provider.py
python3 -m unittest discover -s tests/unit -p test_session_file_provider.py -v
git diff --check
```

Results: `All checks passed!`; `1 file already formatted`; six tests passed in
`2.263s`; diff check exited 0. The six responses remain transport fixtures, not
additional live model calls. The existing two live handoff records are unchanged.
