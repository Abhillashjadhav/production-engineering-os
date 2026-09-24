# R4 retained-inspection BAR

1. **Does this already exist? Yes.** Reuse and strengthen `validate_release_gate_evidence` and the existing barebones reader; the alternative-engine approach is stopped.
2. **Approved criterion or reproduced blocker? Yes.** R4 N1–3/N5, C4-F1/F2/F4, and F-C3-2/3/4 identify inconsistent retained evidence accepted by these readers.
3. **Existing behavior affected? Yes.** Gated and ungated retained inspection/status, synthetic packet fixtures, support-package reading, and PMOS callers may reject packets lacking coherent attempts or genuine receipt bindings; this isolated inspection branch owns the change.
4. **Executable RED-before/GREEN-after check? Yes.** `reviews/r4-inspection/red.txt` records 45 failing new mutation/anchor cases and 44 passing existing controls on unchanged source; source implementation may proceed.
5. **Revert as one unit? Yes.** Reader/CLI changes and direct regression/control fixtures form one logical inspection repair; the shared process validator is a separate integration dependency.
6. **Unrequested setting/dependency/extension? No.** Preserve the public validator signature; `head_anchor` explains the existing optional head argument and adds no authority.

No frozen source, trusted policy, scanner, allowlist, model, deployment, merge, or publication changes. A self-consistent unsigned rewrite remains unauthenticated without an independently retained head.
