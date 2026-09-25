# BAR: C7-01 historical commit provenance

Date: 2026-09-25. Owner: provenance workstream. Base: `a56c1c4671c34dd9748c30dd10cd1d0dcd6ecfc0`.

1. **Already exists? No.** Existing publication files omit the direct `733a409d` alias; this unit extends those records with an explicit, evidence-backed addendum rather than changing the historical files.
2. **Approved criterion or reproduced blocker? Yes.** Review C7-01 reports unresolved local commit identities in `reviews/r3-process-gates/FINAL.json`; the user authorized independent parallel completion.
3. **Changes behavior with a caller or test? No.** Only additive provenance documents, captured read-only metadata, and their offline verification check are added on this isolated branch.
4. **Fail-before/pass-after automated check? Yes.** `verify_provenance.py` is written first and must fail while the claim map is absent, then verify original Git blobs, local trees, public metadata and the existing publication chain after the addendum is supplied.
5. **Independently revertible? Yes.** All additions are under this evidence directory and can be reverted without product changes.
6. **Unrequested setting/dependency/extension? No.** The check uses Python's standard library and read-only Git commands; it adds no runtime surface or CI configuration.

No frozen v1 material, original review claim, scanner, policy, allowlist, approval, branch ref, PR, or deployed state is modified. The stopped planted-bytecode and forged/rechained evidence probes are outside this unit and are not run.
