# Branch protection recommendations

The pipeline cannot (and does not try to) modify remote repository settings. Apply
these on GitHub → Settings → Branches → `main` (requires admin):

1. **Require a pull request before merging** — matches CLAUDE.md ("no direct pushes
   to main") and the pipeline's own merge-gate discipline.
2. **Require status checks to pass**: the `ci` workflow jobs
   (`format-lint`, `types`, `security`, `build-smoke`; the `tests` job
   joins the required set when the first test suite lands) plus the existing
   `pr-review` workflow.
3. **Require branches to be up to date before merging** — keeps the repo-wide
   regression property honest.
4. **Require at least 1 approving review**; for changes under `src/pmpe/policies/` or
   `src/pmpe/review/` (the gate definitions themselves), require review by the repo
   owner — changing the gates is a HIGH-risk decision by this repo's own policy.
5. **Disallow force pushes and deletions** on `main`.
6. Optional: require signed commits.

These are recommendations to apply manually; nothing in this repo assumes they are
already active.
