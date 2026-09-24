# R3 repairs and migration review

Status: **implemented changes are draft and unmerged**. This packet does not
claim a newly approved or freshly generated product. The original frozen v1
contract, evaluator, receipt and freeze are unchanged.

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
| R3-10 falsy criterion findings | Accepted for strict evaluator-return hardening in the typed-gate change. |

The typed migration preserves the original requirements rather than replacing
process gates with criterion conjunctions. A draft binds an immutable
source/evaluator/profile manifest; a later outer freeze binds the final contract,
receipt, plan and manifest. Embedding that outer freeze inside its own contract
would create a digest cycle and is not accepted.

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

A fresh task-store run on a revised exact contract needs a new concrete approval.
No live provider call, paid call, merge or deployment is included here. A replay
or TEST-ONLY provider is not evidence of fresh model generation. Career-assistant
requirements remain a separate product brief.
