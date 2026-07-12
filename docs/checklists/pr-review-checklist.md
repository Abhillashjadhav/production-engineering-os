# PR review checklist (generated-product PRs)

What `pmpe.review.PrReviewer` checks on every build — the human checklist mirrors the
automated one so exceptions are auditable.

## Correctness
- [ ] All required gates green in the retest run (compile, unit, integration, security)
- [ ] `confirm_red.json` proves the tests failed before implementation

## Architecture alignment
- [ ] No files outside the planned layout (`REV_UNPLANNED_FILE`)
- [ ] Every planned component exists (`REV_MISSING_COMPONENT`)

## Test sufficiency
- [ ] Every FR has a `Covers:` marker in tests (`REV_UNCOVERED_REQUIREMENT`)
- [ ] Negative cases present (401/400/404 for the API stack)

## Security
- [ ] Zero `SEC_*` findings (blocking by definition)

## Maintainability & complexity
- [ ] No TODO/FIXME left (`REV_TODO`), no debug prints (`REV_DEBUG_PRINT`)
- [ ] No file above 400 lines (`REV_LONG_FILE`)

## Backward compatibility
- [ ] Greenfield workspace: recorded as not-applicable in the review summary
      (V2 with incremental builds must replace this with a real check)

## Process
- [ ] Merge decision artifact exists with explicit reasons
- [ ] Every escalation has a recorded human decision
