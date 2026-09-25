# Fresh approved delivery is blocked before owner contract approval

**An approval receipt alone cannot make the current task-store run release-ready.** The pinned PEOS runtime cannot produce a GATE-004 PASS, even for a real new model call. Its retained evidence reader also rejects every claimed GATE-004 PASS. A freshness verification design and implementation must precede approval of the final revised contract.

This is a static assessment of the source identities below and the already saved R4 replay. No product code, provider, acceptance scenario, security probe or model was executed for this assessment. The separate chat's live work was not observed or coordinated by this agent.

## Evidence and reachable behavior

| Item | What the existing implementation establishes | Remaining prerequisite |
| --- | --- | --- |
| Product replay | Saved `resume-replay-summary.json` and R4 README report 14/14 product criteria, 56 process records and 117 digest observations. GATE-001/002/005 PASS; state HALTED; zero fresh model calls; approval `UNVERIFIED_DIRECT_CALL`. | Retained product behavior is not a fresh approved delivery. |
| GATE-003 | `ProcessGateRuntime.results` can return PASS for complete digest boundaries **only with a validated outer approval packet**. The saved replay had no packet, so source-check PASS was downgraded to NOT_EVALUATED. | Exact approved contract/receipt, approved-contract compiled plan, reviewed draft, publisher input, source manifest and mutant artifacts, with an independently retained expected outer-freeze digest. |
| GATE-004 at runtime | `generation_provenance_result` has one status assignment: FAIL if consistency reasons exist, otherwise NOT_EVALUATED. Its sole return fixes `freshness_verified` to false. A fresh/live-model label only changes the explanation. | An implemented, reviewed mechanism for verifying actual per-invocation provenance; labels cannot satisfy it. |
| GATE-004 during retained inspection | `validate_process_gate_evidence` unconditionally raises `FRESH_GENERATION_NOT_MECHANICALLY_VERIFIED` for `generation_provenance`. | The retained reader must verify the same supported evidence as the runtime. A runtime-only change cannot close this gate. |
| Release admission | `run_to_release_ready` adds a blocking finding for every gate without explicit PASS. The grammar requires `generation_provenance` mode `fresh` and all current provenance obligations. | Keep GATE-004 mandatory and keep the result blocked until the capability exists. |
| Existing entrypoints | `barebones_cmd._run` passes an approved receipt to the runner but no `ProcessGateInputs`. `r3_task_store_migration.py` produces a DRAFT and optional retained replay using `RetainedReplayProvider`; it never approves or calls a model. | A reviewed invocation adapter must bind complete process inputs to the approved run. Merely removing `--replay` creates another draft. |
| PMOS handoff | `validate_current_handoff` uses a synthetic test issuer and `FixtureProvider`; its positive fixture is RELEASE_READY. | This validates compatibility, not owner approval or task-store GATE-003/004 satisfaction. |

The source of each claim is recorded by path and SHA-256 in `assessment.json`. Relevant functions are `ProcessGateRuntime.__init__/results`, `validate_approval_packet`, `validate_process_inputs`, `generation_provenance_result`, `validate_process_gate_evidence`, `run_to_release_ready`, and `approve_contract_draft`.

## Existing subscription and command access

The existing `CommandModelProvider.invoke` exchanges JSON with a local process. Its class identity requirement prevents a test class from qualifying as the declared live-model command provider; it does not prove that a particular command made a new model invocation.

Two provider examples exist in the pinned historical source:

| Existing path | Retained information | What is unestablished |
| --- | --- | --- |
| `examples/barebones/session-file-provider.py` | Locally generated call directory, start time, request digest, supplied response bytes and provider labels. The file transport explicitly requires the active agent session and calls no model API itself. | An independent link between one actual model invocation and these exact request/response bytes. Locally written labels and timestamps are insufficient. |
| `examples/barebones/codex-cli-provider.py` | ChatGPT-authenticated command invocation; generated result; provider/model labels; usage extracted from JSONL. Raw per-call telemetry is not emitted as independently verifiable provenance, and the temporary invocation directory is removed. | A supported, independently verifiable per-invocation record that PEOS can consume and retain. This source inspection does not establish what the current subscription service could expose with a future supported integration. |

**Verifiable provenance through existing subscription/command access is UNESTABLISHED.** This is not a finding that a paid API or another provider is required. No subscription login, command-provider invocation, external model call or service capability check was performed. The accepted profile already names the existing CommandModelProvider with in-session file handoff; frozen v1 inputs remain unchanged.

## Minimal owner design decision — UNAPPROVED

**Recommended:** authorize a bounded freshness-verification design that reuses existing subscription/command access, keeps GATE-004 mandatory, and proceeds to implementation only if actual per-invocation evidence can be independently verified. The design must bind that evidence to the exact run, request and response, retain it for the reader, and state its trust boundary. If existing access cannot expose such evidence, fresh approved delivery stays blocked and the missing capability is reported.

The alternative is to defer fresh delivery and close only whatever source/replay review is separately demonstrated, explicitly retaining the incomplete fresh-delivery status. Neither choice authorizes operator-attestation PASS, a different provider, paid API spend, a new signing-authority project, merge or deployment.

This design decision is separate from approval of the final product contract. The draft currently recorded as `sha256:52f1cb0955c50cb186c7b1044aa18d049d7e64f9bd63fe740feb614db234c06c` binds the old process source manifest. It must not be approved as if it covered the architecture repair or a freshness implementation that does not yet exist.

## Required order after independent work completes

1. Integrate the architecture repair and permitted independent reviews; preserve exact source/publication identities. The prior security-screening-stopped active external-cache and retained-context-binding adversarial rechecks remain UNVERIFIED. Static review and ordinary replay do not replace them.
2. Resolve the freshness design decision, establish a usable provenance capability, then implement and review its runtime, retained-reader and invocation integration. If the capability remains unestablished, stop the fresh-delivery unit without minting an approval or running the model. Safe source/replay work can still complete separately.
3. From the final reviewed source, regenerate the new source inventory and publisher input, rebuild the DRAFT and proposed plan, and confirm the unchanged product acceptance semantics. Present that exact source/draft/profile/binding bundle for owner approval. Any meaning-changing profile amendment belongs to a new version, not a frozen-v1 edit.
4. Only after actual approval of the exact final draft digest, use the existing publisher to derive the approved contract and receipt. Recompile the plan against the **APPROVED** contract; its digest differs from the DRAFT plan. Freeze the approved contract, receipt, reviewed draft, publisher input, approved plan, source manifest, exact mutants and other reviewed inputs in an outer packet. Retain the expected freeze digest outside the generated evidence store. Hash consistency does not authenticate the owner; the accepted unsigned-approval limitation remains explicit.
5. Run one fresh, bounded generation through the verified existing-access path with complete `ProcessGateInputs`, the approved receipt/authority and exact receipt bytes, the reviewed sandbox/profile and exact negative controls. Baseline, generation, candidate verification, release admission and evidence inspection are sequential dependencies. Within AC-013, each create process must exit before the next starts; the contract excludes concurrent writers.
6. Retain real request/response provenance, commands, outputs, process records, boundary observations and an independently captured terminal ledger head. Accept delivery only if every required gate has supported PASS evidence and final inspection agrees. Keep delivery, merge and deployment verdicts separate.

The current implementation does not provide a ready-to-run command for steps 2–5. Publishing a synthetic passing packet or increasing the number of agents cannot supply the missing capability.

## Exact source identities and assessment check

| Source | Local commit | Tree | Published source identity |
| --- | --- | --- | --- |
| PEOS process | `c67716638731ba3be4ceeab20be6e6fdee631fd3` | `872e53b7cb05bace2d825dca47ea7e27f78c7cf0` | `ccabeecc7346dffa7354e88c1deec53b1674428a` (same published tree) |
| PMOS runtime | `639875203503ae5c9f15e2ff0f7f8317c788e5a1` | `1ff086e93938ffa048b93fa7a258aff37bcd0c6d` | Mapping retained in the existing `pmos-publication-map.json`; combined docs/runtime handoff is `c95469338b64f22edcd9d260246e3c9186b0d302`. |
| Historical provider examples | `4d4a9afdc8a5a75b28fce10499ec5ff405b1b60d` | `ab13172635a9cf4bb94bceb6e95d338523f9d922` | `c1ab2def189fb87c8d1979e5cb7407b80d97a7a5` (same published tree) |

`verify_static.py` reads only git objects and saved JSON; it does not import PEOS, execute provider code or inspect a forged ledger. Its RED result precedes this report in the branch. Its GREEN result verifies the pinned file hashes, the evaluator's no-PASS AST, the retained-reader rejection, the CLI argument gap and the saved HALTED replay. It is a documentation consistency check, not runtime correctness or release certification. Any later source change requires reassessment of the affected findings.
