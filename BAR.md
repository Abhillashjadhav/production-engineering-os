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

## Unit — approved contract file entry and tamper-evident host execution

Branch `feat/contract-file-run`, isolated worktree from local
`863fc449051033d3b51627e95ab50b7f301edd1f` (remote provider base
`1abfbd47061a947e8ce077523a60516a0b6cdcb0`). Issue #202.

1. **Yes, restructured.** Reuse Template, compile_barebones_plan, run_to_release_ready, CandidateSandbox protocol and CommandModelProvider. Add one example CLI entry, not an alternate engine or sandbox.
2. **Yes.** Approved AC-001..014 and Phase 3 require file bindings, compatibility checks and before/after frozen-artifact verification. The owner explicitly authorized host fallback and closed bwrap testing.
3. **No.** Existing source, callers, defaults and evaluator bytes stay unchanged. The added entry invokes existing APIs with explicit host-fallback authorization.
4. **Yes.** Focused checks first fail because the loader/guard entry is absent; cover path permissions, tamper rejection before execution and after exceptional execution, and actual unchanged-engine evaluation.
5. **Yes.** The adapter, its tests and evidence form one independently revertible unit on their own branch.
6. **No.** Only required file inputs, digest anchor, explicit fallback flag and existing provider transport; no new dependency, product setting or plugin surface.

Expected pre-implementation RED is not an implementation attempt. Two failed
implementation validations require a clean restart; no third debugging attempt.

Implementation validation: the first lint preparation identified formatting and
exception-naming findings; these were corrected before execution. Six focused
infrastructure tests pass, Ruff/format/diff checks pass, and the approved packet
compiles with zero compatibility diagnostics. Existing src/ and frozen evaluator
bytes are unchanged. No live product generation has occurred at this checkpoint.
