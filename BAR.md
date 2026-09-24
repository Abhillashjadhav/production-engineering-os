# BAR — install the owner-supplied gate

## Unit — external-review reconciliation and unchanged evidence replay, 2026-09-24

1. **Yes, restructured.** Reuse `examples/barebones/contract-file.py`, the frozen task-store packet, retained candidates and existing negative controls. No parallel execution adapter.
2. **Yes.** The owner requests confirmed review gaps fixed and concluded on GitHub; F-01/F-02/F-10 are reproduced source incompatibilities, distinct from the historical feature demonstration.
3. **No.** This unit records read-only verification and cross-repository closeout. Runtime changes live on separate branches with their own checks.
4. **Yes.** The existing verifier must pass the retained candidate and reject both seeded defective candidates; the gate-change branch separately retains RED-to-GREEN evidence for unbound-gate admission. This report does not invent a failing product test for a documentation-only change.
5. **Yes.** Revert this evidence-only unit without changing the frozen packet or implementation fixes.
6. **No.** No dependency, provider, paid invocation, product rule or execution surface is added. Reuse the already authorized process fallback and retain its limitations.


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

## Unit — real feature run and deliberate failures

Start `02a718d`, branch `feat/contract-file-run`. Frozen owner approval is in PMOS
commit `88bc530e0a100c11988ce7d38349b14a038cd0cc` and freeze digest
`sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2`.

1. **Yes, restructured.** Execute the existing engine and new file entry; no alternate builder or evaluator.
2. **Yes.** Phase 4 and AC-001..014 require live generation, all actual observations, controlled mutations, tamper rejection and one separate extension fixture.
3. **No.** Evidence and generated candidate only; any infrastructure repair would return to its own BAR unit and attempt count.
4. **Yes.** The engine requires every criterion to fail by assertion on the unchanged baseline before a provider request; known-bad variants must fail the same frozen checks afterward.
5. **Yes.** Evidence/generated candidate commit is separate from infrastructure and owner approval.
6. **No.** No new semantics, settings, dependencies, sandbox attempt or signing change.

Phase 4 observed result: one live code response and one non-blocking advisory,
1 build attempt, 14/14 criteria passed, no manual product repair. Baseline 14/14
assertion failures; persistence and filtering mutants both failed by assertion.
Changed contract replica and evaluator replacement were rejected before execution.
A separate DRAFT greeting.echo fixture passed without engine edits or model calls.
All 58 live digest observations matched. Clean clones plus a standard venv install
replayed all 14 criteria and an eight-command user journey; this was retained-
artifact verification, not another live model build. No bwrap attempt occurred.
Evidence and exact commands are in docs/evidence/task-tracker-live-20260918/REPORT.md.

## Unit — clear the new entry's strict typing gate

Start local `3f74a2d798a38552c0dfdf3fc205f30586b4b6ba`, published as
`90c1bd1ef1f4ae518a6873c08671cee2c2d2f07c`. GitHub CI job 105659768387
reported 39 typing errors in the new example entry; this gate was missed by the
initial local validation. Correction attempt one of two. Behavioral success does
not excuse a failing PR gate. The separate review-admission job refuses draft PRs;
that is not an independent review, and it is not bypassed.

1. **Yes, restructured.** Correct the existing entry's annotations and one reused local variable; no new execution path.
2. **Yes.** Actual strict-mypy CI failure at the published head requires this correction.
3. **No.** Type annotations and a local result-variable name preserve behavior; verify normalized executable AST and replay the exact candidate.
4. **Yes.** CI mypy failed with 39 errors before correction. Run the same strict command, six guard tests and unchanged acceptance replay afterward.
5. **Yes.** One isolated correction commit can be reverted independently of the live evidence and frozen approval.
6. **No.** No package dependency, setting, evaluator, contract, sandbox or approval mechanism changes. Install only the already-declared dev checker locally.

Correction attempt 1 passed: exact strict-mypy command reports no issues in 199
source files; six guard tests, Ruff/format/diff and unchanged 14/14 candidate replay
pass. The first local full check needed packaging==26.3 already in requirements.lock;
its environment failure is retained. Normalized executable AST is unchanged after
erasing annotations/imports and normalizing the local result variable. No frozen
artifact or product was altered; live-build evidence retains its original entry hash.

## Unit — Phase 5 reproduction and closeout, 2026-09-21

Start local `1e625ce4b06a0a7fcaf02e1d5f98b28d7db096d1`, remote
`02959731e06d977e9ed61cfd15c962e5ebb85ee5` (identical tree). Issue #202.
PMOS remote `9d55bf650d6586d90a0028241b468559349487c3`.

1. **Yes, restructured.** Reuse the existing verification entry, retained generated artifact and eight-command journey; add only missing exact checkout instructions and closeout evidence.
2. **Yes.** Phase 5 requires every documented step from fresh clone through installation and user journey. The owner now asks to finish the remaining work and identify product decisions.
3. **No.** Documentation and evidence only. No engine, candidate, evaluator, approval or execution-profile behavior changes.
4. **Yes, evidence retention corrected after review.** The pre-edit session check reported `BEFORE: pinned checkout-to-journey walkthrough MISSING`. Its command was not initially retained in the repository. `phase5-closeout/walkthrough-check.sh` now reproduces absence at the unchanged pre-change commit and presence at the closeout commit; the later reconstruction is explicitly dated in `walkthrough-check.json`. The documented steps also passed all 14 frozen criteria and the existing journey.
5. **Yes.** A single closeout commit can be reverted without changing the previous feature, freeze or evidence.
6. **No.** No new dependency, product semantics, provider, sandbox or signing mechanism. The owner closed sandbox retries; its unavailable leg stays explicitly blocked.

The original Phase 5 requests installation and user-journey reproduction, not a
second live generation. The previous conversational status added that requirement
incorrectly. Keep the original live-build evidence separate from this replay.

Walkthrough attempt 1 passed from fresh published GitHub clones and a standard
venv: 14/14 criteria, 8/8 sequential journey commands, 30 verification plus 16
journey digest observations with no mismatches. The copied journey script and
product bytes are unchanged. Exact commands and evidence are retained under
docs/evidence/task-tracker-live-20260918/phase5-closeout/. No new product decision,
second live generation, sandbox retry or approval-forgery fix was introduced.

## Unit — retain the missing before-check evidence

Start local `f360d6bf2dad9436cbc80d27988f6a10e0171b80`, remote
`d800d42abafe1b40e27e1a28763c1471643c6b61`. Independent review finding
4059440816 identified the absent retained automated check for the walkthrough.
Correction attempt one of two. This reconstruction does not claim that its
script was committed or executed before the original documentation change.

1. **Yes, restructured.** Reuse Git's immutable object lookup and the original session's existence check; no new test framework or product capability.
2. **Yes.** The BAR evidence-retention finding requires a runnable check and accurate chronology.
3. **No.** Evidence and BAR wording only; no product, engine, evaluator or workflow changes.
4. **Yes.** Run the same check against the unchanged pre-change commit (nonzero) and closeout commit (zero), recording both commands, outputs and exact source identities.
5. **Yes.** One independently revertible evidence correction commit.
6. **No.** No dependency, product setting, acceptance change or new execution surface.

## Unit — external implementation-review handoff, 2026-09-24

1. **Yes, restructured.** Extend the existing review-closure packet with the owner's requested standalone reviewer prompt; do not introduce a new review system.
2. **Yes.** Owner explicitly requests the implementation, accepted/rejected recommendations and reasons in a shareable review prompt.
3. **No.** Documentation and a point-in-time GitHub status receipt only; no runtime, contract, skill or approval behavior changes.
4. **Yes.** Before edit, `test -e docs/evidence/integration-review-20260924/INDEPENDENT_REVIEW_PROMPT.md` exited 1; after edit, verify the file, its pinned source references and disposition coverage. No product test suite is needed for this document.
5. **Yes.** One documentation-only commit on the existing review-closure branch can be reverted independently.
6. **No.** No setting, dependency, paid invocation, new evaluator, release tag or execution surface.

## Unit — correct review dispositions after external feedback, 2026-09-24

1. **Yes, restructured.** Revise the existing review packet and add a focused follow-up prompt; no new review system.
2. **Yes.** Owner asks for critique and a proposed-change prompt after feedback identifying missing current task-store proof and incorrect source-availability framing.
3. **No.** Documentation only; no runtime, frozen contract, approval, evaluator or integration behavior changes.
4. **Yes.** Before-edit inspection shows no implemented-not-merged lead, historical F-03 partial-disagreement wording, an unsupported source-not-supplied assertion and career requirements inside the repair prompt. Check these are corrected, all five gate IDs preserved and source pins unchanged afterward.
5. **Yes.** A single documentation commit can be reverted independently.
6. **No.** The proposed evidence-gate work is explicitly for independent review, not implemented or approved by this document.

## Unit — R3 evidence completeness and reproducible integration source

1. **Yes, restructured.** Repair existing replay evidence and publish the exact retained combined tree; no alternative evaluator.
2. **Yes.** Owner authorizes implementation of R3; retained logs have only 28/28/26 boundaries instead of the runner's complete 30 each.
3. **No.** Evidence/checker only, frozen source and contract untouched.
4. **Yes.** Check existing boundary/process coverage before regeneration, rerun to terminal exit and require full ordered coverage before copying.
5. **Yes.** One evidence repair commit can be reverted separately.
6. **No.** No dependency, signing, sandbox change or new approval.
