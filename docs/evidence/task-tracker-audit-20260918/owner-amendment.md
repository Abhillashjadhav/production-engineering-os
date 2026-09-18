# Owner amendments and Phase 2 continuation

The owner explicitly superseded the earlier authority halt. This run now requires
approval-time artifact digests, checked immediately before and immediately after
each authoritative check. Every mismatch fails the run. Hashes do not establish
prevention against the root builder: the builder can modify the checker or its
evidence, or change and restore bytes between observations. Root access is a
permanent limitation. The owner explicitly deferred repair of forgeable approval
receipts; no signing mechanism or secret was added.

Two corrections to the earlier external review remain clear:

- New business actions do not require engine-source edits. Existing `Template`
  bindings already compile them; the missing path is a declarative file and CLI
  loader. This run has not yet executed a new action as a delivered feature.
- Prior live-provider evidence already exists in the repository. Its historical
  model calls were not independently verified by this run. This run's two actual
  session responses are separately retained as Phase 0 transport evidence.

## Exact sandbox experiment

Command:

```bash
.venv/bin/python docs/evidence/task-tracker-audit-20260918/sandbox-network-amendment.py --exact-share-net > /tmp/pmpe-network-amendment.json
```

The diagnostic captures the existing production command and actually executes the
amended command. It does not change shipped defaults or implement another sandbox.
The exact network-only override retains `--unshare-all` and adds `--share-net`:

```text
--unshare-all --share-net
```

All other arguments are byte-for-byte unchanged. See
[sandbox-share-net-exact.json](sandbox-share-net-exact.json): exit `1`,
`bwrap: setting up uid map: Operation not permitted`, elapsed
`3.4616010016179644` ms. No candidate started.

The earlier strict namespace diagnostic separately replaced `--unshare-all` with:

```text
--unshare-user --unshare-pid --unshare-ipc --unshare-uts --unshare-cgroup
```

Bubblewrap's mount setup remains. Network unsharing is omitted; no other isolation
was removed to obtain success. Every other production argument is unchanged:
`--die-with-parent`, `--new-session`, `--clearenv`, root tmpfs, read-only runtime
and candidate mounts, read-only `/dev`, new `/proc`, 64 MiB `/tmp` tmpfs and the
existing prlimit settings. The complete exact argv is in
[sandbox-network-amendment.json](sandbox-network-amendment.json).

Observed: exit `1`, `bwrap: setting up uid map: Operation not permitted`.
Elapsed: `3.163831999700051` ms. No candidate process started. Effective candidate
mounts and namespaces therefore remain unverified. The real-sandbox leg is blocked
by this environment; under the owner's amendment that no longer blocks Phase 2.

## Admitted fallback and its limits

The owner allows candidate execution under the isolation this environment permits.
The [resource probe](host-resource-probe.json) actually executed the existing
`prlimit` mechanism around a harmless Python observation. It records exact argv,
effective resource limits and the container namespaces. It is not a product run.

The fallback cannot claim additional candidate user, PID, mount, IPC, UTS, cgroup
or network namespaces, read-only candidate/runtime mounts, or a private `/tmp`
and `/proc`. The existing outer container remains. Resource caps, timeouts, path
validation, model/output budgets, every acceptance assertion and before/after
artifact checks must remain. No further sandbox check is disabled to claim the
real-sandbox leg succeeded. No second sandbox is being built.

## Provider correction

Owner-authorized correction attempt 1 cleared the five lint findings on PR #199.
Ruff 0.16.4 passed on both changed files, the test formatting check passed, and all
six transport tests passed in `2.263s`. Published head:
`1abfbd47061a947e8ce077523a60516a0b6cdcb0`; tested local head:
`863fc449051033d3b51627e95ab50b7f301edd1f`; matching tree:
`668a7cc27f7a9488b69691c54db9a11ecb3a51bc`.
The updated self-review is explicitly labelled; it is not independent human
approval. Existing session model evidence was not regenerated or relabelled.

GitHub's [format-lint job](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/35358277263/job/105642914939)
also completed successfully on that corrected head. The draft review-admission
gate is separate; it is not counted as an independent code review.

## Phase 2 boundary

PMOS is preparing `reviews/task-tracker-v1/`: publisher input, a publisher-created
DRAFT contract, an owner-readable acceptance grid, proposed evaluator source,
declarative bindings, an execution profile and a review manifest. Proposed IDs,
duplicate creation and repeated completion remain decisions for the owner.

No approval receipt or product code is generated at this stage. The evaluator
source is a reviewable proposal; it must be validated against the real baseline
and deliberately broken candidates before any passing result becomes completion
evidence. The CLI loader and before/after enforcement remain implementation work
after contract approval. Meaning-changing changes require renewed approval.

The existing sandbox source is unchanged, the historical forgeability finding is
not repaired, and no merge, deployment or release is authorized by this continuation.
