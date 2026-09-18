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
