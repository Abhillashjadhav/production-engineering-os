# C7-01 historical provenance reconciliation

Checked on 2026-09-25. **Both local identities in the historical `FINAL.json` now have verified public equivalents with identical complete Git trees.** This closes the missing-reference part of C7-01. It does not issue new test results, change the current runtime's verification status, or establish owner approval or release readiness.

| Historical field | Local commit | Public equivalent | Exact shared Git tree |
| --- | --- | --- | --- |
| `combined_tests_and_docs_head` | `733a409d5b0a72f7ad0550db974f70623e259992` | [`e091917babec860aea7e789c00fd22e4ea2a43c9`](https://github.com/Abhillashjadhav/production-engineering-os/commit/e091917babec860aea7e789c00fd22e4ea2a43c9) | `460d443b7f5cae7585d6182db661c991193e7d38` |
| `implementation_source_commit` | `68ae80fbe85332551b36f2a0b6dfe24d7ba1bc3d` | [`8be179fab325b78f170adf474057536d944b788c`](https://github.com/Abhillashjadhav/production-engineering-os/commit/8be179fab325b78f170adf474057536d944b788c) | `537b78a0492328e2b29737db9b2763413eb11f38` |

These are content-equivalence mappings, not claims that the local and public commit objects or their ancestry are identical. GitHub does not resolve the original `733a409d` commit ID itself; the public equivalent above resolves and reports the same tree.

## Evidence for the mappings

The existing [`final-publication.json`](../r3-repair-20260924/final-publication.json) already maps replayed local commit `c209e7d9ff00f94ece14bdd5238b5891c84d59dc` to public `e091917b` with tree `460d443b`. Read-only Git inspection confirms that original local `733a409d` and replayed local `c209e7d9` have that exact same tree. A fresh GitHub Git-data API GET independently returns tree `460d443b` for public `e091917b`. The missing direct alias is therefore derived from two exact tree equalities, rather than an assumed resemblance between patches.

For `68ae80fb`, the previous R4 publication receipt recorded public `8be179fa` and tree `537b78a0`. Fresh Git inspection and a GitHub Git-data API GET independently confirm both ends of that mapping. No new public commit was required for either result.

The exact source URLs, returned commit/tree/parent IDs, and pinned file blob IDs are retained in [`provenance/public-commits.json`](provenance/public-commits.json). It is a relevant-field projection of read-only API responses, with unrelated account metadata omitted. The complete direct mapping and receipt digest are in [`provenance-map.json`](provenance-map.json).

## Preserve the historical claim and its scope

The original [`FINAL.json` at public `524fee6f`](https://github.com/Abhillashjadhav/production-engineering-os/blob/524fee6f8ab7ab33d745d26b4c2ed63356d68e90/reviews/r3-process-gates/FINAL.json) remains unchanged. Its Git blob is `1762fccb2005edf7e833000223573c7ea559b88a`, and its raw file digest is `sha256:d1fce625ff5c53525f0735adbef1c02d64adb8111260831d979ccfbc50a73102`. The public blob ID matches the original local publication source. Existing historical test counts, secret scans, security scans and replay claims remain attributed to their original snapshots; this addendum does not independently rerun or validate those claims.

Local `733a409d` descends from `68ae80fb` through `e909d105`. Their six changed paths are four secret-follow-up evidence files and two test files. Their `src`, `scripts` and `schemas` subtrees are byte-identical; their full trees differ. This explains why the implementation-source identity and combined test/documentation identity are separate. It does not permit reporting the two complete snapshots as interchangeable.

The current R4 runtime and its outstanding checks retain their separate identities and status in the current handoff. C7-02 contract identity, the stopped adversarial rechecks, final CI/review, fresh-run evidence and owner approval are outside this provenance unit.

## Verification performed

The repository BAR requires a check before this documentation change. The first commit writes an offline verifier and records its expected failure because the direct C7-01 map is missing. After adding the map, the same check validates both local trees, both public tree receipts, the original local/public claim blob, the existing publication chain and its public blob, the complete historical file delta, the unchanged implementation subtrees, and the workstream's additive scope.

Run the verifier in the original isolated provenance worktree, with its originating Git object database intact. It requires the historical local commits, including `733a409d`, `68ae80fb` and `c209e7d9`, and checks that every change from base `a56c1c4671c34dd9748c30dd10cd1d0dcd6ecfc0` stays within this evidence directory. The coordinator includes other changes, such as its root `BAR.md`; running this workstream-specific check there intentionally fails the narrow scope assertion.

```sh
cd /workspace/scratch/b6efdedb2992/pmos-parallel-20260925/provenance
python3 -B docs/evidence/r4-parallel-20260925/provenance/verify_provenance.py
```

A standalone GitHub clone does not contain the unpublished local commit objects merely because their public tree equivalents are available. Readers of such a clone can inspect the pinned public Git-data tree responses and retained receipts in `provenance/public-commits.json`; reconstructing the local-object comparisons requires the originating object database as well. The recorded GREEN result applies to the isolated worktree above.

The retained RED output is [`provenance/red.txt`](provenance/red.txt); the GREEN result is [`provenance/green.json`](provenance/green.json). The check imports no product code, executes no historical test or adversarial probe, and makes no remote writes. No frozen v1 file, scanner, policy, allowlist, approval receipt or original evidence file was edited.
