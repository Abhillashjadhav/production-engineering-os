# ADR-004: Local git workspace + PR record artifact

Status: Accepted · Date: 2026-07-12 · Risk: low · Reversibility: reversible (adapter seam)

## Context
The lifecycle requires branch → commits → PR → review → merge, but V1 must not assume
remote repository permissions, and tests must run offline.

## Decision
`GitAdapter` is an interface. V1's `LocalGitAdapter` creates a real git repository in
the run workspace, a feature branch per run, one commit per plan task, and produces a
PR *record* (JSON + Markdown: title, body, diff stat, commits) as an artifact. Merge
happens in the workspace repo only, and only on a MERGE decision.

## Consequences
+ Real git history proves tests-first ordering and small-change discipline.
+ Offline, deterministic, zero credentials.
− No human-facing hosted PR in V1; a `GitHubAdapter` implementing the same interface is
  the V2 path.
