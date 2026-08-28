# Known limitations (V1)

Explicit, reviewed, and deliberate — each was weighed during the independent review.

## Verification depth

1. **`Covers:` markers are trusted.** The reviewer accepts a requirement as covered if
   its id appears in any `Covers:` marker in any test file, including file-level
   aggregates. V1's deterministic test architect writes truthful markers, so this is
   sound today; an LLM-backed test generator (V2) could game it. V2 must tie coverage
   to executed test outcomes, not markers.
2. **`confirm_red` proves failure, not meaningfulness.** Generated tests fail before
   implementation because the `app` modules don't exist yet (ImportError), so red is
   guaranteed but doesn't distinguish "fails because unimplemented" from "would fail
   for any reason". A vacuous suite that imports nothing would be caught (it would
   pass, which confirm_red rejects); a suite that imports app but asserts little would
   not. The requirement-coverage review check is the compensating control.
3. **The retest step always re-runs all gates**, even when the fix agent changed
   nothing. This is deliberate — the lifecycle promises "re-run all tests" after the
   fix stage and the cost is a few seconds — but it is redundant work in the common
   clean-run path.

## Human-gate semantics

4. **The fix-step escalation does not block the run.** When blocking findings can't be
   auto-fixed, the run completes through the merge gate (NO_MERGE) with the escalation
   recorded open, instead of halting mid-pipeline. Safety holds because the findings
   independently force NO_MERGE; the deviation from "high risk always blocks" is
   intentional so the PM still gets a full report. Rejecting that escalation therefore
   yields NO_MERGE rather than a failed run.
5. **Approving a contradiction doesn't edit the spec.** The approval documents the
   product decision, but the spec text still contains both sides; the build proceeds
   on the functional requirements as written.

## Product scope (by design, see ROADMAP.md)

6. One reference stack (`python-stdlib-crud-api`); one entity journey verified in
   deployment (the first entity).
7. Generated auth is a single static bearer token (single-user products).
8. "Merge" and "PR" are local to the run workspace; "deploy" is a verified local
   process plus a promotable artifact. Remote/cloud equivalents are adapter seams.
9. The NSM (builds reaching verified production + first use without engineer
   intervention) needs fleet-level usage data; V1 records each run's contribution in
   `metrics.json` but cannot aggregate across runs yet.
10. Validator heuristics (vague-AC detection, activity-only NSM, dependency keywords)
    are pattern-based: they catch the common failure shapes, not all of them.

## V2 (0.2.0) — accepted limitations from the independent review round

11. **Crash-window ledger duplication.** Evidence is written before the state
    transition persists (evidence-first by design). A crash in that window can
    leave the stage un-advanced; re-issuing the command then appends a second,
    identical ledger event. Store transitions and stage state recover cleanly
    (fixed in the same review round); the ledger itself is append-only with no
    dedup key, so under interruption an action can be one-to-many in the
    record. Trajectory checks are duplicate-tolerant (first-occurrence and
    set-based logic).
12. **Fire/no-fire eval cases check constants, not behavior.** The
    auto-generated stage-routing cases prove the eval YAML agrees with the
    engine's STAGE_AGENTS map — a consistency check between two repo surfaces,
    not a live-routing test. The enforced surface is the engine's admission
    (`stage_of` gating), which the run-engine tests cover directly. The
    permission cases (read-only, worktree) DO check the real frontmatter.
13. **Reviewer agent evals are schema-level, not domain-level.** The
    planted-failure cases prove the shared review validator rejects
    wrong-candidate and evidence-free reviews; they do not prove each reviewer
    catches its own defect class (that is live Claude judgment, checked by the
    demo's planted defects and, in live runs, by the four-way review round).
14. **The runtime read-only proof is drawn at the git-tracked boundary.**
    `readonly_snapshot`/`verify_unmodified` diff git-tracked content (`git
    ls-files`, plus an explicit untracked allowlist). This is deliberate: it
    excludes untracked runtime files — Claude Code's own
    `.claude/scheduled_tasks.lock`, dependency/build caches — symmetrically on
    both sides, so a transient harness file the harness itself creates or
    deletes cannot register as a reviewer write. The trade-off is that a
    reviewer *creating a new untracked file* is not detected by the content
    proof (a tracked-file change or removal still is). The primary control
    remains the reviewers' frontmatter tool list (Read/Grep/Glob only), enforced
    by the Claude Code runtime and asserted by the permission evals; the content
    proof is belt-and-braces. Two related scopes: the candidate **freeze**
    digest (`pmpe.engineering.candidate`) intentionally still hashes the whole
    tree — narrowing it would move already-frozen candidate digests — so the V2
    `verify_frozen` path retains the whole-tree behaviour; and a non-git root
    now fails closed with a clear error rather than silently walking the tree.
15. **The engine does not spawn worktrees itself.** `specialist_worktree` is
    the isolation seam for the live `/production-engineer` skill; in fixture
    mode (CI, demo) specialists are simulated and only their artifacts pass
    through admission, so worktree isolation is exercised by its own
    integration tests rather than by the demo run.
16. **Five specialist profiles are vocabulary without agent files.**
    `SPECIALIST_PROFILES` names frontend/data/eval/security/platform owners
    that have no `.claude/agents` definition yet; routing to them fails closed
    until a definition exists (selecting an undefined specialist is a
    RoutingError by design).

## Personal runtime assurance

17. **Runtime connectors are protocols plus deterministic local fakes.** Calendar, product
    worker, and recoverable-operation interfaces are ready for provider implementations, but
    no real calendar, model, or external action connector ships in issue #121.
18. **Registry and approval serialization is process-local.** The JSONL event chain detects
    alteration on read and serializes threads sharing one registry instance. Multi-process or
    distributed use needs an append service or operating-system lock. Calendar approval
    consumption is also in memory; a real adapter needs a durable single-use receipt store.
19. **Learning proposals require human admission.** Failed evals generate reviewable proposed
    regression cases. They are intentionally not installed, executed, or promoted into the
    canonical eval suite automatically.
