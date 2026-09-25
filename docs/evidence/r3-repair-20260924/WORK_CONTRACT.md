# R3 implementation contract

Owner instruction: assess the three attached R3 reviews and implement supported
changes. Reuse the existing PMOS-to-PEOS path and preserve product-manager intent.

Outcome: a reviewable implementation of the confirmed repair findings and a
semantics-preserving draft migration of the task-store gates, with complete
evidence and reproducible source. Do not report a fresh approved product run
until exact new artifacts are approved and that run actually occurs.

Leading checks: reproduced failures before changes; targeted regressions;
independent reviewer reproduction; published source/tree equality. Guardrails:
unchanged original 14 criteria and evaluator, frozen v1 preserved, no discarded
gates, no paid calls, no Mac access, no sandbox retry, no weakened security
policy, no signing/authentication claims from hashes, no merge/deployment.

Work packets:

- Root: reproduce/fix incomplete replay evidence, publish the exact combined
  test tree, join evidence, independently review code and publish draft PRs.
- Gate admission worker: reject misplaced/empty declarations; check retained
  gate/candidate bindings in inspection/support paths. No new signing system.
- Migration worker: four typed process/evidence gate kinds and runtime
  collectors, strict compilation, draft-only migration and honest replay.
- Verifier worker: digest syntax and explicit unverified provenance/approval;
  preserve existing raw-byte integrity and frozen catalog grader.
- PMOS worker: externally supplied expected ledger head in the fixture,
  canonical-vs-byte receipt wording, authority caveat and published identities.
- Independent reviewer: replay completeness/frozen identity and migration/code
  checks. A worker is not the sole reviewer of its own result.

Each worker has an isolated worktree and may only commit its scoped changes.
Root owns remote publication; repository review rules still govern merge.

The external migration proposal is not accepted literally: embedding a full
freeze digest in a contract included in that freeze creates a cycle. The draft
must instead bind an immutable source/evaluator/profile manifest, with a later
outer freeze binding the final contract/receipt and that manifest. Command
completion boundaries must exist before a gate may certify their completeness.
Disclosure distinguishes observed facts from operator attestations.

F-09 consolidation/deletion is excluded until the owner chooses a system of
record. The attached comparison is reviewer evidence, not a locally reproduced
audit of the tarball. Keep both systems intact. Fresh generation and revised
exact-digest approval remain a concrete final handoff; no approval is fabricated.
