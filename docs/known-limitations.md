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
