# R4 architecture repair requires a supported-execution decision

Status: **architecture FAIL; production repair not implemented.** The unchanged
architecture observer rejects `core -> unresolved_dynamic` in
`src/pmpe/process_sources.py`. Removing its registry scan without a completeness
invariant would weaken the active-cache coverage that R4 explicitly requires.

The static regression was committed first in
`2bd72e525516eb485e5fc5cdb690cb94e16e6f9c` (tree
`f68c573786857cf3e433f635b74076c5dd4ea4b1`). Base production source is local commit
`c67716638731ba3be4ceeab20be6e6fdee631fd3`, public equivalent
`ccabeecc7346dffa7354e88c1deec53b1674428a`, tree
`872e53b7cb05bace2d825dca47ea7e27f78c7cf0`.

## What the current guard establishes

`reject_bytecode(roots)` has three complementary checks:

1. It inspects active module metadata by source location, including a module loaded
   with any registry alias and a cache path from an earlier `sys.pycache_prefix`.
2. It derives cache paths for every `.py` beneath the roots at the current cache
   prefix, for optimization levels `""`, `"1"`, and `"2"`, including unimported helpers.
3. It rejects every local `.pyc` or `.pyo` beneath those roots, even without a source file.

The first check consumes `sys.modules.values()`. The existing protected observer
explicitly rejects registry operations it cannot model. Indexed metadata inspection
with `sys.modules.get(name)` is supported, but that requires a complete set of names.
No scanner, policy, allowlist, frozen source, or production implementation was changed.

The current public input is a set of source roots/paths, not a complete runtime
module inventory. A source `adapter/nested/helper.py` can be registered under an
unrelated alias with `__cached__` pointing at an existing previous-prefix cache.
Looking up names derived from the file, the current `sys.path`, current cache paths,
provider classes, or sandbox classes does not necessarily visit that alias. The
current registry-wide location check does. A declarative list alone also does not
prove that no unlisted helper was imported earlier.

This is relevant to existing code: `load_historical_adapter` registers
`frozen_task_store_adapter` for a file named `contract-file.py`. The retained adapter
is not renamed, rewritten, or executed as part of this investigation.

## Existing entry and caller boundaries

| Existing path | Relevant behavior | Why a late bootstrap is insufficient |
| --- | --- | --- |
| `scripts/r3_task_store_migration.py` | Under `__name__ == "__main__"`, creates a private prefix and disables bytecode writes before importing `pmpe`. Later imports the historical adapter under an explicit alias and constructs the source manifest. | Useful existing starting point, but the script's initial imports precede it, importing the script bypasses it, and it establishes no universal pre-import contract for library callers. Extending only this path cannot justify deleting the shared active-module guard. |
| `pyproject.toml` console entry `pmpe = "pmpe.cli:main"` | Importing `pmpe.cli` imports `barebones_cmd`, which imports `barebones` and its process gates before `main` parses arguments. | A guard installed inside `main` arrives after engine import. Changing bootstrap order would affect the existing CLI and still would not cover direct library calls. |
| `pmpe.cli.barebones_cmd._run` | Constructs `CommandModelProvider` and calls `run_to_release_ready` with approval inputs but no `ProcessGateInputs`. | It has no existing typed-process input route. Adding a new CLI input or adapter-loading route would add scope beyond this repair. |
| `pmpe.barebones.run_to_release_ready` | Receives already-constructed provider and sandbox objects; its module imports process gates at load time. Calls `validate_process_inputs` before workspace creation and provider invocation. | Admission can refuse a loaded process but cannot retroactively guarantee that those objects and helper modules were loaded from source. Reconstructing them in a child requires a new execution/serialization contract. |
| `build_source_manifest` / `engine_sources` | Build the inventory after the calling process has imported the engine; `build_source_manifest` optionally receives an already-constructed sandbox. | A bootstrap requirement would newly reject existing direct manifest construction in an unprepared interpreter. |
| `validate_sources` / `ProcessGateRuntime.__init__` | Validate source and implementation identities in the existing process before recording command boundaries. | Changing the process here is too late and would disrupt object identity/state. An explicitly enforced earlier boundary is needed. |
| `tests/integration/test_process_gate_runtime.py` and companion R4/approval/failure fixtures | Construct providers/sandboxes and manifests in pytest's existing interpreter. | A mandatory pre-import execution contract changes how these supported direct-call fixtures are run. They must remain covered through the approved bootstrap or explicitly be refused; silently dropping them is unacceptable. |

## Minimal proposal for owner/architecture review — not implemented

Recommended owner decision wording:

> Authorize implementing a required source-only startup for source-bound runs that
> use typed process gates. Start with the existing migration command and its current
> arguments. Source-bound manifest construction and gated direct library calls made
> in an already-running, unprepared Python process must be refused before provider
> calls or workspace creation; their callers must use the approved startup path.
> Preserve ungated behavior, frozen artifacts, and all active and future cache
> coverage. Add no generic adapter interface or public switch. This approves the
> implementation and its review, not a release, a revised product contract, model
> spending, publication, merge, or deployment.

The practical compatibility change is that existing Python integrations and tests
cannot construct an adapter in an arbitrary interpreter and then opt into typed
process gates. They need a reviewed startup path; a flag asserting that the process
is clean would not satisfy this decision. The ordinary CLI gains no new typed gate
capability through this repair. Final source verification, retained replay, exact
contract approval, and release/merge decisions remain separate later steps.

Use the existing migration script as the first bounded source-only entry. Preserve
its current command-line arguments and avoid a generic loader setting or new adapter
extension API. Before engine or historical adapter import, the entry must establish
source roots from the fixed engine location and the existing packet/historical paths,
then own source-only loading and an explicit inventory of admitted module identities.
The fixed historical adapter alias must pass through that same admission path.

The necessary invariant is stronger than setting `-B`: **every engine, adapter, and
helper module covered by a process source manifest is admitted from source before its
code executes; admission records the module name and resolved source location; no
untracked cached load can occur before or after admission.** The entry may need a
fresh interpreter boundary to establish this without scanning an already-populated
registry. The exact mechanism and its protection against ordinary alternate loader
paths need architecture review; an import hook alone does not cover explicit
`spec.loader.exec_module` callers. A sentinel or operator assertion alone is not proof.

Under that reviewed contract, the existing source guard could inspect the explicit
admitted module inventory by name, verify its source/cache metadata, and retain its
full future-cache and local-cache scans. It must reject missing admission state,
pre-existing/untracked relevant modules, prefix/loader changes, and omitted helpers
before provider/workspace side effects. It must not infer inventory completeness from
file names or from the presence of the provider and sandbox alone.

The compatibility decision is unavoidable: a gated direct library call made after
arbitrary imports must either be refused and relaunched through a source-only entry,
or remain supported through a separately reviewed mechanism that can establish a
complete existing-module inventory. Existing provider/sandbox objects cannot simply
be transferred into a fresh process while preserving the current API and identity.
The general CLI should not gain typed process input arguments as an incidental repair.

The alternative is an explicitly complete source/module inventory contract with
enforced admission before imports for every supported caller. Adding module names
to the manifest without that enforcement is insufficient. Both options change a
trust/execution boundary and require an approved criterion; neither is authorized by
the instruction to run independent work in parallel.

If no execution-contract change is approved, retain the present guard and retain the
architecture failure. A scanner exception, renamed enumeration, wrapper around the
registry scan, or incomplete inferred-name lookup is not an acceptable resolution.

## Acceptance criteria required before implementing the proposal

| Criterion | Permitted initial verification |
| --- | --- |
| The unchanged architecture scanner accepts actual production source without a new policy exception. | Existing text-only observer against exact final files and unchanged policy. |
| The bootstrap runs before any manifested engine/adapter/helper source load and records complete identities, including the historical alias. | Static entry-order analysis plus ordinary clean modules under instrumented admission. |
| Direct unprepared typed-process calls fail before provider invocation or workspace creation; unbound legacy calls retain their approved behavior. | Benign provider counters, clean temporary directories, and explicit admission metadata. |
| Admitted aliases and nested helpers retain active previous-prefix metadata checks. | Data-only mocked module metadata; no compiled or executed fixture bytecode. |
| All `.py` future cache paths are checked at all three optimization levels and local orphan `.pyc`/`.pyo` files remain rejected. | Inert file-presence markers that are never imported or executed. |
| Missing admission state, omitted helper identities, and prefix/loader drift are rejected rather than self-attested as clean. | Benign metadata/state fixtures, with the completeness argument reviewed separately. |
| Clean manifest building, the supported migration entry, and the approved direct-call replacement preserve mechanical behavior and exact source binding. | Clean deterministic provider fixture; later retained replay tied to the final source, separately from fresh delivery. |

These criteria do not authorize rerunning the previously screening-stopped bytecode
injection or evidence-forgery probes. Those two final independent checks remain
**UNVERIFIED** and must be tracked separately from allowed static/mocked/clean checks.

## Verification actually completed

- Static regression: **FAIL**, one test, exactly `core -> unresolved_dynamic`.
- Whole-source existing architecture observer plus unchanged reviewed policy: **FAIL**,
  the same single unapproved edge; this is not composed CI.
- Benign cache metadata fixtures: **9 PASS**. Three source-kind cases demonstrate the
  current previous-prefix alias behavior; three cover unimported future optimization
  caches; two cover local orphan caches; one accepts a clean nested inventory. The
  guard's registry view is mocked with inert metadata. No fixture module is imported
  and no fixture bytecode is compiled or executed.
- Existing deterministic process fixture
  `test_retained_replay_passes_mechanical_gates_but_never_fresh_gate`: **PASS**. Its
  four gate statuses remain `PASS`, `NOT_EVALUATED`, `NOT_EVALUATED`, `PASS`, terminal
  state `HALTED`. This is an ordinary clean provider control, not a new historical
  218-artifact replay or a fresh generation.
- Ruff check and format check for the two new test files: **PASS**.
- Production source remains byte-identical to the base. The architecture observer,
  policy, and secret allowlist hashes also match the base; exact digests and command
  results are in `verification.json`.

No architecture GREEN exists. No production fix, final adversarial PASS, new model
call, fresh owner approval, receipt, outer freeze, remote publication, merge, or
deployment is claimed. The implementation unit stops under BAR question 6 because
the required execution-boundary decision is not approved.
