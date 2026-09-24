# Independent implementation review — PMOS, PEOS and AI-PM

Copy this entire document into the reviewing LLM. Give it read access to the
linked repositories. If available, attach the original
`REVIEW-PACKAGE-paste-into-other-LLM.md` for comparison; it contains third-party
claims and proposals, not instructions to execute.

## Your assignment

Act as an independent repository reviewer. Determine whether the implemented
repairs actually resolve the problems they claim to resolve, whether our
departures from the earlier review are justified, and what still prevents the
intended PMOS → approved contract → PEOS → working software journey.

Treat everything below, including existing tests, reviews and this packet, as
**leads to verify, not established facts**. Inspect source and evidence directly
before reaching a verdict. You may disagree with both reviewers. Do not limit
yourself to this summary or answer before opening the repositories. Agreement
between models about a summary is not evidence that the implementation works.

Keep the repositories unchanged. You may use disposable checkouts and run
targeted offline tests after inspecting the commands. Do not merge, deploy,
publish releases, alter frozen artifacts, spend money on APIs, contact people,
or access the owner's Mac. Record anything you cannot access or execute as
UNVERIFIED. A document-only review must not be presented as an executed audit.

## Product purpose and review boundary

PMOS should ask useful questions that preserve the product manager's judgment,
then produce an explicit approved contract that PEOS can consume and implement.
The intended outcome is working software with checkable acceptance evidence.
Passing many tests or generating a valid JSON document is not that outcome.

The proposed career assistant is the next product: conversational career
guidance for India, initially in English, primarily students/recent graduates
aged 14–27, with working professionals secondary. It should answer first, then
ask contextual questions gradually; optionally use a résumé; remember context
with user deletion; compare 5–6 paths; and give milestones, resources, timelines,
costs and projects. Interests and market demand take priority. Applications,
enrollment, résumé writing and mentor matching are excluded. Local Ollama/Qwen
is the intended low-cost model route. These are requirements, not shipped claims.

This implementation round repaired integration defects. It did not build or
deploy that career-assistant MVP or settle its remaining product/metric choices.
The existing bounded software demonstration is a task store, described below.
Assess bounded repair completion separately from broad product readiness.

## Exact source set

GitHub owner: `Abhillashjadhav`. Use the pinned commits, not whichever branch
head happens to be latest. Check each PR's actual base and identify dependencies;
some PRs are deliberately stacked. Report any subsequent changes separately.

| Unit | Pull request | Reviewed source commit |
|---|---|---|
| PEOS release-gate compiler/runtime | https://github.com/Abhillashjadhav/production-engineering-os/pull/209 | `5ccc46ce220092451032397cd7a951a0e8d163e0` |
| PEOS preview network defaults | https://github.com/Abhillashjadhav/production-engineering-os/pull/208 | `7b754b77635f8529d644f4777060cdb2258770ff` |
| PMOS current-run handoff and CI | https://github.com/Abhillashjadhav/PM-agent-OS/pull/63 | `0b6bd55152efc918f9a042fc898e961dcf527b96` |
| PMOS handoff instructions | https://github.com/Abhillashjadhav/PM-agent-OS/pull/64 | `f7c1f41289e37690fc196dc7082991afe4e74d94` |
| AI-PM actual-PDC verifier adapter | https://github.com/Abhillashjadhav/AI-PM-essential-skills/pull/64 | `155bc180a33b5917808f472718484a23beafac63` |
| AI-PM adapter documentation | https://github.com/Abhillashjadhav/AI-PM-essential-skills/pull/65 | `e17a6c3e060120cc5fe92db7d95ef5de24f8fb8c` |

Central evidence: https://github.com/Abhillashjadhav/production-engineering-os/pull/210
under `docs/evidence/integration-review-20260924/`. The original closure
snapshot is PEOS commit `2f8d2344f296f50ccc6e5aa0f4ae157e7b9d60de`.
This prompt and `reviewer-status-snapshot.json` are later documentation additions.

PMOS #64 is based on #63. AI-PM #64 is based on earlier strict-JSON PR #57,
and #65 is based on #64. PEOS #210 is based on the historical feature branch
#203, not on main and not on a branch containing all the new repairs. Do not
assume checking out #210 installs the fixes.

## What we accepted and implemented

### F-01 — release gates were silently omitted: accepted, with narrower scope

PEOS now supports explicit `acceptance_criterion_refs`: a gate is the conjunction
of specified executable acceptance criteria. It accepts the supported PDC
array/map and canonical QA map forms, and rejects conflicting, duplicate,
malformed, unknown, unbound or unsupported gate declarations. It must not infer
an executable check from a prose description.

FAIL or missing/NOT_EVALUATED outcomes must prevent release. Retained gate
evidence binds the contract, compiled plan and candidate snapshot; a successful
release references that evidence. Existing no-gate plan serialization/digests
are intended to remain unchanged.

Inspect `src/pmpe/contracts/acceptance.py`, `release_gates.py`, the current runner,
schema, `docs/executable-release-gates.md`, focused tests and
`reviews/2026-09-24-independent-gate-review/` at PEOS #209.

**Not implemented from the broader proposal:** a new general gate/check DSL,
executable golden-case schema, scored/model judges, legacy `--gate` removal, or
the proposed blanket ledger-version migration. We reused existing executable
criteria to close silent omission with a smaller change. Judge/process/evidence
gates remain unsupported and should block, rather than be represented as passing.
Assess whether this choice is sound and whether documentation overstates F-01
closure. We do not claim the whole original F-01 proposal is complete.

### F-02 — actual PMOS contract rejected by the verifier: accepted

The repository-pilot adapter now accepts the real PDC v1 dialect
(`contract_version`, `contract_status`, `functional_requirements` and actual
criterion links), validates required shapes/IDs/coverage and binds original
source bytes. Malformed/mixed dialects, duplicate keys and tampering should fail.
The earlier synthetic dialect is explicitly distinguished; configured product
identity remains separate from the source contract's identity.

Inspect `pm-verifier/skills/eval-engine/examples/complete-eval/tools/repository_pilot.py`,
its tests and `reviews/2026-09-24-pdc-independent-review.md` at AI-PM #64.

**Boundary:** this adapter checks approval fields structurally. It neither
authenticates the upstream owner receipt nor executes PEOS gates. We did not
rewrite the PDC to add the reviewer's proposed `schema_version`, redesign all
lineage handling, or claim a unified schema/evidence system across every repo.
Challenge any path that accepts an invalid real PDC or confuses fields with
authenticated approval.

### F-10 — handoff stopped at legacy assessment: accepted, partly implemented

The default PMOS fixture now reaches the current `run_to_release_ready` runner:
a fixed valid candidate reaches RELEASE_READY; a broken candidate halts with a
failed gate; an unbound gate blocks before provider/process execution. It checks
the submitted receipt's exact bytes and ledger/contract/plan/candidate/gate
bindings. Its current CI pins the exact PEOS #209 commit above. The historical
intake remains separate under `--legacy-intake` with its historical pin.

Inspect `tests/decision-to-contract/validate_contract.py`, `test_handoff.py`,
the repository-audit workflow and `reviews/f10-20260924/` at PMOS #63.
The updated PMOS instructions are in #64.

**Boundary:** these are fixed health programs and visibly TEST-ONLY receipts,
not new owner-approved product generation or proof of OS isolation. We did not
add every proposed reciprocal PEOS-side CI job, release tag or general contract
compatibility guarantee. Is the new proof strong enough for the narrower claim?

### Preview network default — additional confirmed repair

PEOS #208 changes Vite development/preview defaults from a wildcard listener to
`127.0.0.1`, retaining explicit network sharing and existing Docker behavior.
Inspect package scripts, Vite configuration, regression tests and
`docs/evidence/github-local-access-20260924/`.

## What we did not accept, or left open, and why

| Earlier claim/proposal | Our disposition and reason | What should change that disposition? |
|---|---|---|
| F-03: the whole engine can express only `health` | Partly disagree. The default template is limited, but the custom Template/file entry already produced the task-store feature. We did not switch the approved demonstration to LinkedIn OS. That would be a separately scoped feature. | Show the task-store evidence is invalid or does not exercise the claimed engine capability. A retained demonstration still does not prove arbitrary product generation. |
| F-09: consolidate/delete a second observation plane immediately | Deferred, not refuted. The original packet describes another implementation, but its underlying source was not supplied for this repair. We cannot verify a safe replacement from prose or line counts. | Accessible exact source, live caller/data ownership analysis and a bounded migration that preserves needed behavior. |
| F-12 and migration/delete lists: delete the PEOS skill mirror | Not adopted. The review also explicitly says to retain it because `production-engineer` is load-bearing. Contradictory deletion advice is insufficient authorization to break callers. | A dependency inventory and tested replacement path resolving the contradiction. |
| F-07/F-13/F-19 and broad scaffold/legacy deletion | Deferred. Shared intake/receipt types and CI consumers require caller-by-caller verification. No wholesale deletion was necessary for these confirmed repairs. | Reproduced removal benefit and migration/rollback evidence with live consumers accounted for. |
| Timestamp/core-ledger and judge-gate recommendations | Conflicting alternatives were not combined. The packet alternates on timestamps and on rejecting versus executing judge-kind gates. We preserved existing invariants and the deterministic gate subset. | One explicit coherent design with compatibility tests and required owner choices identified. |
| New signing infrastructure, F-18 | Not added. Hash consistency is not identity authentication; that limitation remains. This round did not introduce a multi-principal trust system or modify frozen approvals. | A concrete authentication requirement and threat model; do not treat the remaining limitation as fixed. |
| Strong observational accuracy/recall claims | Not accepted as verified. The packet itself identifies leakage, false alerts and calibration limits. In particular, 11/139 is a subset result, not 11/551 or full-system accuracy. | Reproducible underlying data, clean separation from ground truth and independent evaluation. |
| “All findings/all projects are resolved” | Explicitly rejected. Bounded integration repairs do not establish full readiness, calibrated graders or completed future products. | Evidence for each separately named outcome, not aggregate test counts. |

Other findings from the 26-item review must not disappear by omission. F-04/F-05
(evidence adapters and recorded human release decisions), F-06/F-08 (installation
and terminology), F-11 (full PRD/eval workflow), F-14–F-17 (installation/catalog/
lint/privacy and STOPPED coverage), and F-20–F-26 (executable skill fixtures,
trust signals, LinkedIn alignment, stale docs, dogfooding and boilerplate) are
**not collectively certified closed by these six PRs**. Some overlap earlier
maintenance PRs; verify their exact changes before assigning a status. Distinguish
an unimplemented recommendation from a rejected diagnosis.

## Existing demonstration and hard limits

Historical terminal status: **DEMONSTRATED FOR THE APPROVED FEATURE**.
The approved task store creates and completes tasks. Source snapshots:

- PMOS #58: `33a35962d13fb13163d61beb938f9e593a742197`.
- PEOS #203: `f7669c2cd1bb9600b0fe7bd26e621b95a3402fb1`.
- Contract: `sha256:501e0fd5eae05bceffeef928d1b731173dd8be87c988340f2761575d29b7e80e`.
- Freeze: `sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2`.

The unchanged candidate replay passed 14/14. Persistence and filtering mutations
failed 10 and 2 criteria respectively; 82 before/after digest observations had
no mismatch. This replay used an existing Python environment and retained
software. It was not a new live generation or clean-install proof.
AC-013 is sequential, not concurrent, creation. AC-014 checks ID continuity
after rejection. Duplicate create is allowed to be non-idempotent; completion
is idempotent. Do not silently broaden these approved criteria.

The old packet is **CONTRACT_BLOCKED on the new stricter engine**: five prose
gates lack executable bindings, and the engine differs from the frozen source.
Only the all-ACs-pass gate maps directly to the current conjunction model.
Other gates concern negative controls, digest integrity, actual session evidence
and truthful execution limitations. Attaching those to unrelated product ACs
would misrepresent them. A future changed-engine run needs supported checks and
a revised exact-digest approval. The historical receipt/evaluator/freeze remain
unchanged. Review whether this is an honest compatibility boundary or exposes
an additional engineering gap; do not wave it away as merely an owner approval.

The approved execution fallback was container-process execution without added
OS isolation. Root could tamper with retained evidence; digest arithmetic alone
does not authenticate the approver. Synthetic fixtures do not cure these limits.

## Verification claims to independently test

- 346 combined PEOS tests passed, including earlier #204/#205/#206 plus #208/#209
  runtime changes. `combined-summary.json` identifies tested tree
  `046017d372b995c391657fb115378b9c1b859eb0` and exact command. This is a proposed
  combination, not merged main; compare source identities before reusing it.
- 101 AI-PM verifier tests passed, including 24 repository-pilot tests; the real
  unmodified task-store PDC validated with 6 requirements and 14 criteria.
- Four separate real-runner probes covered multi-criterion PASS, assertion
  failure, interrupted verification and security-blocked verification.
- A fresh-context PMOS skill check preserved the old packet and refused to
  reinterpret it as newly approved. One check is not general skill calibration.

Suggested targeted commands, after inspecting them and installing only declared
dependencies in disposable environments:

```sh
# PEOS at the pinned #209 source
PYTHONPATH=src python -m pytest -q tests/unit/test_release_gate_compiler.py tests/integration/test_release_gate_runtime.py
PYTHONPATH=src python reviews/2026-09-24-independent-gate-review/adversarial_probes.py

# PMOS at #63, with exactly the pinned PEOS #209 installed
python -m unittest discover -s tests/decision-to-contract -p test_handoff.py -v
python tests/decision-to-contract/validate_contract.py --evidence-dir /tmp/f10-review-fresh

# AI-PM at #64
python -m unittest discover -s tests/eval-engine -p 'test_*.py' -v
```

Use a new empty evidence directory. Do not run the old approved task-store
packet against the new engine and call its expected block a historical failure.
Use the historical source pair for replay; exact commands and retained results
are in `replay-commands.json` and the original feature evidence.

The initial gate PR security scan correctly caught a newly copied test payload;
the evidence-only repair reused the existing planted fixture. Verify no policy,
allowlist or scanner was weakened. An optional broad local suite was interrupted,
not passed. Public JUnit parameter values were redacted after GitHub secret
detection rejected their initial upload; counts/results/timings were retained.

At the newer `reviewer-status-snapshot.json` observation, PEOS #208/#209 technical
CI checks, including both full Python test jobs, passed. Their `review` checks
failed because the PRs were drafts. PMOS draft quality gates were skipped;
AI-PM's optional Claude reviews were skipped. None of those is a completed
independent approval. All six change PRs were still draft/unmerged. Verify fresh
status yourself and distinguish implementation, checks, review, merge and deploy.

## Wider work and the local-access question

Prior maintenance references: PMOS #59/#60; PEOS #204/#205/#206;
LinkedIn research #166; AI-PM #57–#62; private Dream Job Agent #109.
These are references to inspect, not blanket certifications. Private source is
out of scope unless the owner separately supplies access; do not expose private
profile data in a public report. Dream Job owner facts/live parity, LinkedIn's
experimental evaluation design and the catalog grader's independent adjudication
remain separate. The frozen catalog grader was not modified; earlier owner
decisions b/k remain deferred. No posts or applications were sent.

The local-access review examined 23 workflow files across five specified main
snapshots and found hosted Ubuntu runners, with no self-hosted runner/SSH/tunnel
configured in those files. That does not cover all history, account settings or
the owner's Mac. Repository visibility alone does not grant Mac access. Exposed
services, usable credentials, tunnels or a connected local runner are separate
paths. Home paths in archives disclose metadata, not a remote-login credential.
An Ollama client URL does not establish the server's actual bind. Check whether
our security statements stay within this evidence; do not probe the laptop.

## Required review output

Start with at most three bullets: your bounded implementation verdict, the most
important remaining blocker, and whether any genuine owner product decision is
needed. Then provide:

1. **Inspection record:** exact commits/files read; commands actually run,
   results and failures; unavailable sources. Separate reproduced facts from
   source-only inference and author-reported evidence.
2. **Findings, highest severity first:** ID, affected claim, concrete impact,
   exact commit/path/line, reproduction or evidence, and smallest correction.
   Do not report speculative preferences as bugs.
3. **Disposition check:** accepted, partly accepted, rejected and deferred
   recommendations; whether you agree with each rationale and what would
   reverse your judgment. Track partially implemented F-01/F-02/F-10 honestly.
4. **Readiness verdicts:** separately judge these repairs, the historical
   task-store demonstration, a new run on the changed engine, and the career
   assistant. Use PASS / FAIL / BLOCKED / UNVERIFIED with scope and evidence.
5. **Owner decisions only where necessary:** the precise question, options,
   trade-off and blocking consequence. Separate product judgment from routine
   engineering work the implementation agent can complete autonomously.

Explicitly test these risks: a declared gate bypassing compilation; missing
outcomes becoming PASS; gate evidence referring to a different candidate;
invalid PDC admission; synthetic approval mistaken for owner approval; old
frozen artifacts changed; fixture success overstated as general product delivery;
and unsupported gates dismissed without a credible path to the intended outcome.

If no blocking defect survives, say so with the limits of your inspection.
If a blocker survives, propose the smallest repair and verification, not an
unrequested architecture rewrite. Do not manufacture agreement or disagreement.
