# BAR — install the owner-supplied gate

Base: `dd4271b70fcb9cb5b9dd279fe516c2fe50806751`. Branch: `docs/pmos-peos-bar-gate`.
Unit: install the exact six-question policy from the owner's 2026-09-18 cloud-run prompt.

1. **No.** The base tree has no AGENTS.md or BAR Gate; CLAUDE.md was inspected.
2. **Yes.** The owner's settled decision explicitly requires AGENTS.md in both repositories as the first change.
3. **Yes.** Agent workflow changes for callers that previously used CLAUDE.md alone; new work must now record the gate. This documentation-only unit has its own branch. No product/runtime caller changes.
4. **Yes.** Before this change, the automated file/six-question check exited 1 for both repositories; the post-change check also compares the gate text with the supplied definition.
5. **Yes.** Reverting this documentation commit removes only AGENTS.md and this unit's BAR record.
6. **No.** No runtime setting, dependency or extension is added; the gate is explicitly owner-requested.

Expected pre-change RED is prerequisite evidence, not a failed implementation attempt.
Implementation validation attempts: 1; exact-text comparison and six-question check passed; git diff --check passed.

## Unit — Phase 1 current-seam reproduction

Branch: `audit/task-tracker-seam`. Output is evidence from the existing compiler,
approval verifier and sandbox; it introduces no runtime behaviour.

1. **No.** This owner-requested task-tracker audit record does not exist. Reuse the shipped fixtures and verification functions; do not create a parallel evaluator.
2. **Yes.** Phase 1 explicitly requires current action/measure, provider, approval, sandbox and installation evidence before a feature contract is proposed.
3. **No.** Run existing entry points and isolated probes; do not modify engine, approval or acceptance code.
4. **Yes.** The existing compiler and approval tests supply executable checks; reproduce the approved feature's unsupported behaviour before any repair. A later repair must demonstrate the corresponding failing check passing in its own BAR unit.
5. **Yes.** Audit evidence is an independent documentation concern on its own branch.
6. **No.** No runtime setting, dependency, schema or extension is introduced by this unit.

If an explicit owner halt condition is reproduced, stop feature work and report the
evidence. Do not fix or weaken an acceptance check to obtain a passing run.

Outcome: one diagnostic run completed and triggered the owner's halt condition.
The session and provider could open evaluator/approval source for writing; no
bytes were written. Receipt forgery was reproduced on a synthetic fixture.
The real sandbox failed to establish isolation. No repair was attempted; the
failed safety properties remain failures. Phase 2 onward was not started.

## Unit — owner-amended sandbox and authority evidence

The previous halt is historical. The owner now accepts before/after artifact
digest checks, retains root access and receipt forgery as limitations, and approves
testing the existing sandbox with only network unsharing removed. No signing fix
or second sandbox is authorized. Branch: `audit/task-tracker-seam`.

1. **Yes, restructured.** Reuse the exact command built by `BubblewrapCandidateSandbox.run`; do not add a sandbox implementation.
2. **Yes.** The owner amended the reproduced NETLINK_ROUTE failure and authority halt explicitly.
3. **No.** This unit adds diagnostic evidence; shipped sandbox defaults and acceptance behavior remain unchanged.
4. **Yes.** The retained Phase 1 real command fails before candidate execution; run the same command with only the approved network namespace change and record whether it passes.
5. **Yes.** One audit follow-up commit contains the amended evidence and can be reverted independently.
6. **No.** No engine flag, dependency or extension is introduced; this is the explicitly requested diagnostic variation.

Observed: the network-only amended command failed at UID-map setup (exit 1).
The separately labelled host/container resource probe exited 0 and reported the
requested prlimit values; enforcement was not stress-tested. No product ran.
The owner permits the weaker-isolation continuation, so the environment failure
is retained as a real-sandbox limitation and Phase 2 proceeds.

## Unit — Phase 0 in-session provider

Branch: `feat/in-session-provider`. The owner explicitly approved this transport in Phase 0.

1. **No.** Searching `src/pmpe` and `examples/barebones` found the command wrapper, Codex adapter, API adapter and scripted fixture, but no session-file transport. Reuse `CommandModelProvider`; add only its missing transport example.
2. **Yes.** Phase 0 requires a real in-session file round trip when no callable no-key provider exists. PATH checks returned no codex/claude and the base environment could not import pmpe.
3. **No.** Add an optional example command with its own tests; existing callers, interfaces and defaults remain unchanged.
4. **Yes, after restructuring.** `python3 -m unittest discover -s tests/unit -p test_session_file_provider.py -k test_round_trip -v` ran one test and failed with `owner-approved session-file provider is absent` (exit 1). The failing check exists before implementation.
5. **Yes.** One provider commit and its tests/evidence can be reverted without changing the engine or the policy commit.
6. **No.** The handoff directory is required by the owner-approved transport; reuse the existing provider timeout environment variable and add no package dependency.

Implementation validation attempts: 1. Six transport checks passed. The actual in-session round trip exited 0; request, response, output and elapsed-time evidence are retained under docs/evidence/session-provider-20260918/. Expected pre-implementation RED does not count as an implementation failure.

## Unit — owner-requested provider lint correction

Branch: `feat/in-session-provider`; separate worktree. Owner's amendment explicitly
starts this correction at attempt one of two. Starting head is local
`2725c784f8245ff90e8aa370f6ec1d6d9eea5124`, published as
`e67ec19ae6d9b205ea744d833cc0aa4f18f06eb1` with the same tree.

1. **Yes, restructured.** Extend the existing provider and test; no parallel implementation.
2. **Yes.** PR #199 CI job 105617666543 reproduced UP017, two E501 findings, I001 and RET503; the owner explicitly requested correction.
3. **No.** Equivalent UTC spelling, line wrapping, import spacing and an explicit test-failure raise preserve existing transport behavior and assertions.
4. **Yes.** The existing Ruff job failed with the five findings before this change; rerun the same lint gate and the six transport tests afterward.
5. **Yes.** One follow-up commit touches only this BAR record, the existing provider/test and correction evidence.
6. **No.** No setting, runtime dependency or extension surface is added.

Attempt 1: PASS. Ruff 0.16.4 reported `All checks passed!` on both changed
Python files; its formatting check reported `1 file already formatted` for the
test file. All six unchanged transport tests passed in 2.263 seconds.
