# PMOS → PEOS — Phase 1 halt evidence

This is the historical Phase 1 snapshot. The owner subsequently replaced its halt
condition and authorized continuation. See [owner-amendment.md](owner-amendment.md)
for the current authority model, sandbox observations and Phase 2 boundary. The
original findings below remain evidence; root access and receipt forgery are now
permanent stated limitations, not blockers for this bounded run.

Terminal status: **BLOCKED**. The owner required a halt if acceptance checks were
reachable by the builder. The actual session and a provider child both opened
evaluator source for writing. No bytes were written; all recorded before/after
digests match. See [results.json](results.json), keys `in_session_builder_authority`,
`provider_authority` and `halt`.

Issue: [#200](https://github.com/Abhillashjadhav/production-engineering-os/issues/200).
The earlier missing-BAR and missing-provider blockers are superseded. The supplied
gate is committed in both repositories, and the cloud file handoff completed
through the existing provider interface. See the
[Phase 0 evidence](../session-provider-20260918/README.md).

## Scope and source identity

Both checkouts began clean on `main`. The observed starting heads were exactly the
historical reference heads, so later commits on other branches are not audited:

| Repository | Starting commit | Work branch |
| --- | --- | --- |
| PMOS | `27d0418cb258fa5e374447f88185ff1b7117f182` | `docs/pmos-peos-bar-gate` |
| PEOS | `dd4271b70fcb9cb5b9dd279fe516c2fe50806751` | `audit/task-tracker-seam`, stacked on the provider branch |

PEOS local head when the probe ran was
`2725c784f8245ff90e8aa370f6ec1d6d9eea5124`. Its tree is
`6a9317fb969062b386c049f8f2141912a7f495e1`, also the tree of the
published provider head `e67ec19ae6d9b205ea744d833cc0aa4f18f06eb1`.
Local and connector-created commit metadata differ; published trees were compared
with the tested local trees. No engine or evaluator source changed in these PRs.
The audit's own final commit is the head of its draft PR and can be obtained with
`git rev-parse HEAD` after checkout; the PR description records its full SHA.

## Current findings

| Lead | Classification | Observed result and evidence |
| --- | --- | --- |
| New business actions require engine edits | Already supported through the Python API; CLI gap reproduced | Default compilation rejects `audit.new_action` with `ACTION_NOT_REGISTERED`; supplying existing `Template.actions` compiles it without an engine edit. `results.json`: `default_new_action`, `custom_new_action`; `src/pmpe/barebones.py`: `compile_barebones_plan`; `src/pmpe/cli/barebones_cmd.py`: `_compile`, `_run`. No declarative loader was added. |
| No registered measures | Reproduced for the default template | `default_template().measures` is empty. Existing `Template.measures` accepts the synthetic `audit.missing_records` criterion. `results.json`: `measure_compilation`. |
| A measure evaluates end to end | Blocked in this environment | Calling the existing `_criterion_findings` measure path with the real `BubblewrapCandidateSandbox` failed before candidate execution. No measured product value is claimed. `results.json`: `measure_evaluation`. |
| Only fixture model evidence exists | Already superseded | This run retained two actual session responses, one through unchanged `CommandModelProvider.invoke`. The base repository also contains claimed historical live-provider evidence in `docs/evidence/e1-real-provider-20260826/README.md` and `docs/evidence/real-behavior-drift-20260827/README.md`; those historic model calls were not rerun here. |
| Approval is forgeable | Reproduced | Altering an expected result makes the original receipt fail. Recomputing the public contract, draft and receipt hashes makes verification pass for the same expected fixture approver. No signing secret or human decision was used. `results.json`: `approval`; `src/pmpe/contracts/authoring.py`: `verify_contract_approval`. |
| Evaluator is outside builder control | Reproduced failure; owner halt triggered | Both session and command-provider identities have effective UID 0 and can open `barebones.py`, `acceptance.py`, `authoring.py` and the acceptance compiler test for writing. `results.json`: authority records. Opening used no truncation and wrote zero bytes. |
| Exercised tests use a real sandbox | Mixed in existing tests; actual execution blocked here | `tests/conftest.py` substitutes `_LocalCandidateTestSandbox` in three barebones test files; E1 opts out with `PMPE_TEST_REAL_SANDBOX=true`. This probe directly used the production sandbox without that fixture. Its isolation setup failed. |
| Clean documented install runs the workflow | Runtime install succeeded; full workflow blocked | A fresh clone, standard venv and `pip install -e .` succeeded. The separate pinned pytest/ruff install failed at pytest resolution. The documented README asks for the dev extra; that exact full setup and an end-to-end user journey are not demonstrated. See Phase 0 README and sandbox evidence. |
| Stateful journeys fit the existing execution path | Unverified, with a relevant constraint | Source shows a fresh verification copy per criterion, a read-only candidate mount and disposable `/tmp`. Restart persistence across actions needs an explicit trusted journey observer; no product semantics or adapter was implemented after the halt. `src/pmpe/barebones.py`: `_verify_snapshot`, `_run_action`, `BubblewrapCandidateSandbox.run`. |

The audited PMOS seam is `.claude/skills/decision-to-contract/SKILL.md` and
`tests/decision-to-contract/valid-answers.json`, which feed the existing PEOS
`build_contract_draft` publisher. Approval then uses `approve_contract_draft` and
`verify_contract_approval`; the barebones CLI compiles, invokes `CommandModelProvider`,
runs the candidate sandbox and records verification through `run_to_release_ready`.
This is a source trace, not a newly executed PMOS task-tracker journey.

## Exact diagnostic commands

From this PEOS checkout, using the runtime installed during Phase 0:

```bash
.venv/bin/python docs/evidence/task-tracker-audit-20260918/probe.py > /tmp/pmpe-phase1-results.json
```

The recorded invocation wrote to this directory's `results.json` instead.
Exit code: `0` means the diagnostic completed, not that the system passed. The
recorded duration was `144.73411600192776` ms. The diagnostic emits no feature
approval and invokes no model. The provider-child response is a privilege probe,
explicitly labelled `diagnostic_only_not_model`.

The real sandbox's captured command lines are under `sandbox_commands`. They
requested read-only runtime and candidate mounts, isolated namespaces, a 64 MiB
temporary filesystem, 1 GiB address-space limit, CPU limits, a 64 MiB file-size
limit, 256 file descriptors and 128 processes. These are requested settings;
effective candidate mounts and limits could not be observed because setup failed.
The independent minimal diagnostic was:

```bash
/usr/bin/bwrap --unshare-all --ro-bind / / -- /bin/true
```

It exited `1` with:

```text
bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted
```

No namespace, permission, resource or approval check was removed to proceed.
The repository's separate historic matrix uses sealed memory files and a read-only
source mount (`src/pmpe/evals/real_behavior_drift_eval.py`, `_snapshot_command`).
That mechanism was inspected, not exercised or represented as protecting this
in-session builder. This finding concerns the current path and privileges; it does
not claim that every possible deployment must have the same authority failure.

## Work completed and work stopped

The first changes were the exact owner-supplied `AGENTS.md` gate and bootstrap BAR
records: PMOS [PR #57](https://github.com/Abhillashjadhav/PM-agent-OS/pull/57),
PEOS [PR #197](https://github.com/Abhillashjadhav/production-engineering-os/pull/197).
The provider adapter, tests-first history and retained completions are in
[PR #199](https://github.com/Abhillashjadhav/production-engineering-os/pull/199).
Those changes are infrastructure, not generated task-tracker code.

The six provider transport tests passed again on the published file contents:

```bash
python3 -m unittest discover -s tests/unit -p test_session_file_provider.py -v
```

Observed: `Ran 6 tests in 2.259s`, `OK`. These six tests use fixture responses and
prove transport behavior only. Phase 0's two separate live responses are retained
under `session-provider-20260918`. The existing wrapper round trip recorded
`9177.658066000731` ms; the direct handoff recorded `12574.136892006209` ms.
These include orchestration delay and are not model-latency benchmarks.

The first provider implementation passed its six transport checks. Subsequent CI
reported five lint errors, so the unit is not merge-ready. That is one failed CI
validation; no repair attempt or branch regeneration followed the explicit halt.
See [review.md](review.md) for the findings and exact job links.
Phase 1 completed one diagnostic run, with two calls
to the real sandbox plus its minimal failure diagnostic. Those are observed
infrastructure failures, not attempts to repair or weaken safeguards.

No task-tracker build, approved acceptance grid, criterion result, known-bad
persistence/filter candidate, artifact-tamper rejection, extension execution or
Phase 5 end-to-end reproduction is claimed. Phases 2–5 did not run because the
explicit halt condition was reached. Identifier, duplicate-creation and repeated-
completion semantics remain unresolved; the owner-approved feature itself remains
settled. No manual product repair occurred because no product was generated.

Human/session interventions: the owner supplied the gate, approved the feature
scope and chose the in-session transport; the orchestrating assistant answered two
real handoff requests and performed infrastructure work. The provider requires an
active agent session and cannot reproduce model completions headlessly. Token
counts, per-call price and total billed usage are unavailable; no estimate is made.
No paid API, rented compute or subscription was introduced.

## Required next gate

Retain the working provider and the owner-supplied gate. Resume feature work only
when the existing real sandbox can start and the evaluated artifacts and approval
authority are protected from the builder's actual privileges. A key stored beside
the code or a promise not to edit files would not establish that boundary. The
current run does not authorize a second sandbox or weaker acceptance checks.

Then complete the concrete PMOS-authored contract and acceptance grid for owner
approval before generation. No contract redesign or broad platform-readiness claim
is justified by the evidence recorded here.
