# R3 repairs and migration review

Status: **implemented changes are draft and unmerged**. This packet does not
claim a newly approved or freshly generated product. The original frozen v1
contract, evaluator, receipt and freeze are unchanged.

Current changes: [PEOS inspection #211](https://github.com/Abhillashjadhav/production-engineering-os/pull/211),
[typed migration #212](https://github.com/Abhillashjadhav/production-engineering-os/pull/212),
[PMOS #65](https://github.com/Abhillashjadhav/PM-agent-OS/pull/65)
([docs #66](https://github.com/Abhillashjadhav/PM-agent-OS/pull/66)), and
[AI-PM #66](https://github.com/Abhillashjadhav/AI-PM-essential-skills/pull/66)
([docs #67](https://github.com/Abhillashjadhav/AI-PM-essential-skills/pull/67)).
Copy [REVIEW_PROMPT.md](REVIEW_PROMPT.md) for a further source-first audit.
`ci-snapshot.json` records the point-in-time GitHub checks. Static security,
format, type and several product checks pass; full Python test jobs and the
migration's trusted-security check are still running in that snapshot. Draft
review admission remains blocked. These are not
merged or fully CI-cleared changes.

## Review dispositions

| Finding | Disposition and bounded change |
| --- | --- |
| R3-01 incomplete replay publication | Accepted. All three replays were regenerated to terminal exit, then checked before copying. Each contains 30 digest boundaries and 14 process rows; retained product passes all 14 criteria, both seeded mutants fail. Original truncation cause is unknown. |
| R3-02 unpublished combined source | Accepted. Published the exact original tested tree, then reran its 346-test command. This historical reproducibility snapshot is not a merge candidate. |
| R3-03 ignored gate declarations | Accepted. Reject misplaced, misspelled, prefixed/suffixed and empty declarations at contract metadata grammar boundaries. Preserve absent gates. |
| R3-04 unverified PDC provenance | Accepted. Require strict digest syntax and explicitly mark approval unverified and source digest FORMAT_ONLY. Hash syntax does not authenticate an upstream approval. |
| R3-05 mutable unsigned evidence | Accepted within trust boundary. PMOS fixture retains the observed head outside the reopened store. PEOS inspection checks gate/plan/candidate bindings and optionally an externally trusted head. A fully self-consistent rewrite remains unauthenticated without that external anchor. |
| R3-06 authority framing | Accepted as documentation correction. VERIFIED alone is not owner approval; direct-call authority remains explicit. |
| R3-07 unavailable local hashes | Accepted. Publish exact source trees and record local-to-published mappings; preserve historical records. |
| R3-08 replay gate coverage | Accepted. Historical criterion replay is not process-gate execution. Current-engine typed migration must evaluate process gates explicitly; retained replay cannot establish fresh generation. |
| R3-09 receipt identity | Accepted. Distinguish canonical runtime identity from exact-byte fixture checks. |
| R3-10 falsy criterion findings | Fixed: gate results require an explicit tuple of findings; malformed falsy values are NOT_EVALUATED rather than PASS. |

The typed migration preserves the original requirements rather than replacing
process gates with criterion conjunctions. A draft binds an immutable
source/evaluator/profile manifest; a later outer freeze binds the final contract,
receipt, plan and manifest. Embedding that outer freeze inside its own contract
would create a digest cycle and is not accepted.

Independent implementation review also reproduced two retained-inspection gaps:
a malformed compiled criterion could pass, and a later verification failure did
not invalidate an earlier gate PASS. The follow-up reconstructs the plan with the
existing compiler from sealed test bytes and rejects contradictory later events.
Both original probes now return `EVIDENCE_INVALID`; the intact control remains
eligible. See `INDEPENDENT_ADMISSION_REVIEW.md` for independent reproduction.

The PEOS security gate exposed an existing dynamic loader whose line-bound
allowlist no longer matched after inserting validation. The fix replaces that
loader with an ordinary import; policy and scanners are unchanged. Generated
support-package proof bytes consequently change: existing bundles can use their
pinned prior verifier, or be reassembled for the new verifier. No retained bundle
or original task-store artifact was rewritten.

## Completed draft migration

The publisher-built v2 draft and full replay are in
[this pinned handoff](https://github.com/Abhillashjadhav/production-engineering-os/blob/524fee6f8ab7ab33d745d26b4c2ed63356d68e90/reviews/r3-process-gates/README.md).
All 14 compiled behavioral criteria remain identical to v1. The draft digest is
`sha256:e7af374535ddf236d4298b926caf9de5d5445df4d6b61b62654b90caa81c6a37`;
it has no owner receipt and is not an approved runnable contract.

| Current-engine retained replay | Result |
| --- | --- |
| Terminal state | HALTED; approval/fresh-generation obligations are unmet |
| GATE-001: original product criteria | PASS, 14/14 |
| GATE-002: meaningful negative controls | PASS; persistence/filtering fail 10/2 criteria |
| GATE-003: all approval-bound digests | NOT_EVALUATED; no new complete approved packet |
| GATE-004: fresh in-session generation | NOT_EVALUATED; retained bytes, no live model call |
| GATE-005: execution and authority disclosure | PASS within documented attestation limits |
| Complete evidence | 277 blobs, 8 events, 56 process records, 117 digest observations |

Independent review closed four migration findings: incomplete outer-packet
coverage, retrying after an observed mismatch, colliding guard namespaces, and
bypassing the deterministic publisher. It reran 39 core checks and 12 final
approval checks, reconstructed the draft exactly, and checked 226 source hashes.
See `INDEPENDENT_MIGRATION_REVIEW.md`; this reviewer inspected retained replay
artifacts but did not independently execute the product a second time.

`final-publication.json` maps final local/public identities and records exact
whole-tree equality after stacking the migration on the repaired inspection
branch. The Python API recipe is the supported post-approval entry point; the
existing CLI does not supply process-gate inputs and refuses them. No signing,
root containment, independently proven live-provider identity or general product
readiness is inferred from these results.

## Reproducibility

- Exact historical combined source: commit
  `766e13d553705b8465701bb97f9949bb58f4c415`, tree
  `046017d372b995c391657fb115378b9c1b859eb0`, branch
  `repro/review-346-exact-tree-20260924`.
- `combined-source.json` records checkout and test instructions.
- `combined-recheck.json` and `combined-exact-tree-recheck.txt` record the
  independently rerun historical command (346 passes).
- `replay-correction.json` records old incomplete counts, actual new commands,
  exit codes, and complete coverage. The corrected replay files live in
  `../integration-review-20260924/{retained,persistence,filtering}`.
- `check_replay_complete.py` is the regression check committed before repair.

## Remaining owner-controlled decisions

F-09's source was supplied to the original reviewer; the previous explanation
that it was not supplied is withdrawn. Keep both monitoring implementations
until the owner chooses the system of record. The supplied comparison is review
evidence; this workspace has not independently reproduced the unavailable
archive's contents. No deletion or consolidation is authorized by inference.

The concrete choice is A: keep `pm_evals_monitoring` as the system of record and
port the observation-plane ideas through an adapter/contract change; or B: use
observation-plane as its replacement and migrate the existing API/UI/storage
consumers before removing the old plane. Neither option is selected here.

A fresh task-store run on a revised exact contract needs a new concrete approval.
No live provider call, paid call, merge or deployment is included here. A replay
or TEST-ONLY provider is not evidence of fresh model generation. Career-assistant
requirements remain a separate product brief.
