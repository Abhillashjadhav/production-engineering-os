# R4 retained-inspection BAR

1. **Does this already exist? Yes.** Reuse and strengthen `validate_release_gate_evidence` and the existing barebones reader; the alternative-engine approach is stopped.
2. **Approved criterion or reproduced blocker? Yes.** R4 N1–3/N5, C4-F1/F2/F4, and F-C3-2/3/4 identify inconsistent retained evidence accepted by these readers.
3. **Existing behavior affected? Yes.** Gated and ungated retained inspection/status, synthetic packet fixtures, support-package reading, and PMOS callers may reject packets lacking coherent attempts or genuine receipt bindings; this isolated inspection branch owns the change.
4. **Executable RED-before/GREEN-after check? Yes.** `reviews/r4-inspection/red.txt` records 45 failing new mutation/anchor cases and 44 passing existing controls on unchanged source; source implementation may proceed.
5. **Revert as one unit? Yes.** Reader/CLI changes and direct regression/control fixtures form one logical inspection repair; the shared process validator is a separate integration dependency.
6. **Unrequested setting/dependency/extension? No.** Preserve the public validator signature; `head_anchor` explains the existing optional head argument and adds no authority.

No frozen source, trusted policy, scanner, allowlist, model, deployment, merge, or publication changes. A self-consistent unsigned rewrite remains unauthenticated without an independently retained head.

## W5 — supported approved-bundle run (#224) — 2026-09-25

1. **Already exists? Partly.** `examples/barebones/contract-file.py` loads frozen bindings, and the migration script assembles `ProcessGateInputs`. Neither is a supported CLI path. The loader's bindings and safe-path rules are promoted into `pmpe.approved_bundle`, and the example stays frozen as historical evidence.
2. **Reproduced blocker? Yes.** The review (2026-09-25) found that `barebones_cmd._run` passes no bindings and no `ProcessGateInputs`, so gated contracts cannot run through the CLI.
3. **Changes existing behaviour? No.** A new `run-bundle` subcommand; `run` and the other commands are unchanged.
4. **Failing check first? Yes.** `reviews/w5-approved-bundle-20260925/red.txt`: 13 failing before implementation.
5. **Revert as one unit? Yes.** Two new modules, one registration line, docs and tests.
6. **New setting/dependency/extension? No new dependency.** The bundle layout is a fixed schema with no plugin surface. Measures must be frozen `tests/` files; actions may target explicit template modules, as the engine's default template does.

## W2 — source-only admission replaces registry scans (#217) — 2026-09-25

Owner decision, 2026-09-25 18:29 IST, answering `reviews/r4-architecture-20260925/DECISION_REQUIRED.md`: **"Approve source-only start"**. Gated runs must start in a fresh source-only interpreter. The guard checks process state instead of scanning `sys.modules`. Gated direct calls in an unprepared interpreter are refused.

1. **Already exists? Yes.** Extend `reject_bytecode` / `implementation_identity` in place; no parallel checker.
2. **Approved criterion or reproduced blocker? Yes.** `tests/unit/test_process_source_architecture.py` fails on the unchanged scanner; the owner decision above authorizes the boundary.
3. **Changes behaviour with callers/tests? Yes.** Every gated path (manifest build, source validation, typed process admission) now refuses interpreters without `-B`/`PYTHONDONTWRITEBYTECODE` plus an unchanged, empty startup cache prefix. CI's `tests` job already sets both. `scripts/r3_task_store_migration.py` relaunches itself source-only with unchanged arguments. Local `pytest` must use the same environment (CONTRIBUTING). Classes with no own functions can no longer establish canonical identity.
4. **Failing check first? Yes.** `reviews/w2-source-only-20260925/red.txt`: the architecture test, four subprocess admission probes and the cache-path parity test fail before the fix commit.
5. **Revert as one unit? Yes.** One source file, the migration bootstrap, and docs; the tests stay as the RED evidence.
6. **New setting/dependency/extension? No.** No scanner, policy or allowlist change. The startup requirement is the owner-approved boundary; no new flag or loader API.

## R4 architecture compatibility repair — 2026-09-25

1. **Does this already exist in either repository? Yes.** The existing `reject_bytecode` path owns this check; a parallel checker is stopped. This unit extends that path only if equivalent coverage is demonstrated.
2. **Approved criterion or reproduced blocker? Yes.** The unchanged architecture scanner reports `core -> unresolved_dynamic` for `src/pmpe/process_sources.py`; the current handoff explicitly makes this a release blocker.
3. **Existing behavior affected? Yes.** Source-manifest construction, typed process admission, per-command source validation, manifested adapters/helpers, and the retained migration call this path; branch `repair/r4-architecture-20260925` owns the unit.
4. **Automated RED-before/GREEN-after check? Yes.** `tests/unit/test_process_source_architecture.py` checks the actual guard source with the unchanged architecture observer. Its failing baseline must be recorded and committed before implementation.
5. **Revert as a single unit? Yes.** The isolated architecture repair branch contains only its task, gate, directly relevant regression, implementation (if sound), and verification evidence.
6. **Unrequested setting, dependency, or extension surface? No.** No addition is authorized. If preserving active-cache guarantees requires a new inventory contract or bootstrap requirement, stop implementation and record the exact decision instead.

Allowed verification is source/static analysis, the existing text-only architecture observer,
clean inventory/provider fixtures, lint/types, and benign data-only/mocked checks. The
screening-stopped bytecode injection and evidence-forgery final checks remain UNVERIFIED;
they must not be rerun, rephrased, relocated, or replaced with equivalent execution.

## Distinct support-package caller unit

1. **Existing path? Yes.** Extend the package reader's current contract/receipt/candidate checks; do not synthesize a barebones plan or add another engine.
2. **Reproduced blocker? Yes.** The real package sealer has a separate two-event format; strict barebones validation would reject it, while its old reader accepted an interposed unknown event.
3. **Existing behavior affected? Yes.** Package sealing, reuse, and assembly consume this reader; the coordinator explicitly extended this branch's boundary to its call site.
4. **Executable RED/GREEN? Yes.** The archived baseline gives one failure and three preserving controls in `package-red.txt`; the changed reader and full support file give 88 passes in `package-green.txt`.
5. **Single-unit revert? Yes.** A pure sequence guard, one import/call substitution, and four direct tests form a separate commit.
6. **Unrequested setting/dependency? No.** The existing package schema and caller distinguish this format. No marker, policy, scanner, or settings change is added.

## W1a — malformed human-test bindings on the R4 process line (2026-09-25)

1. **Already exists? Yes.** PR #205 (`bd3e081`) fixed this against `main`; this unit reuses its exact test and source change on `ccabeecc` instead of writing a parallel fix.
2. **Reproduced blocker? Yes.** Handoff W1 / review P1: `human_test: null` compiles to zero criteria and still counts as requirement coverage. `reviews/w1-consolidation-20260925/human-test-binding-red.txt` records 21 failing / 44 passing on unchanged `ccabeecc` source.
3. **Changes behaviour with callers/tests? Yes.** `compile_acceptance_plan` now raises for malformed bindings that were previously dropped silently; contracts that relied on that silent drop will be refused before any provider or sandbox call.
4. **Failing check first? Yes.** Test commit precedes the fix commit.
5. **Revert as one unit? Yes.** Two commits, one test file and one source function.
6. **New setting/dependency/extension? No.**

## W1b — setup/teardown failures counted as meaningful RED on the R4 process line (2026-09-25)

1. **Already exists? Yes.** PR #204 (`12fa805`, `c061e21`) fixed this against `main`; this unit reuses its tests (including the allowlisted-fixture position) and source change on top of W1a.
2. **Reproduced blocker? Yes.** Handoff W1 / review P1: a fixture failing before the test body was classified as an assertion failure. `reviews/w1-consolidation-20260925/call-phase-red-red.txt` records 4 failing / 44 passing on unchanged W1a source.
3. **Changes behaviour with callers/tests? Yes.** `_run_pytest_node` now raises `ContractInvalidError` for setup/teardown failures and non-assertion exceptions that previously counted as RED; intentional `pytest.fail` and assertion failures keep their meaning.
4. **Failing check first? Yes.** Test commit precedes the fix commit.
5. **Revert as one unit? Yes.** One source function and one test file.
6. **New setting/dependency/extension? No.**

---

# Merged from the R4 replay-checker / contract-file line (4c7f3ea)

# BAR — install the owner-supplied gate

## Unit — resume R4, retain ordinary replay and publish review snapshots

1. **Yes, restructured.** Continue the existing R4 source branches, migration and checker; no new engine or evaluator.
2. **Yes.** The owner asked to continue PMOS review, and the retained work contract authorizes engineering repair and draft publication.
3. **No.** This evidence unit changes no runtime, scanner, security policy, frozen v1 input or approval. Any remaining implementation repair requires its own unit.
4. **Yes.** Retain exact outputs of the existing ordinary replay and static gates. The architecture gate fails; blocked adversarial rechecks remain unverified. No new test is needed for this evidence-only record.
5. **Yes.** The resumed evidence and publication record are a separate reversible commit.
6. **No.** No dependency, provider, permission, security exception, sandbox retry or owner decision is introduced. Review-only branches preserve source without restarting the blocked adversarial checks through a PR update.

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
