# R3 admission and retained-gate evidence repair

Assigned scope: F-R3-03 misplaced/empty gate declarations and F-R3-05 bounded
inspection/support-package binding checks, at base
`f18395a3edb53d7c450fc87660e55b1dc1ce073b`. Read the supplied implementation
review R3, CLAUDE.md, CONTRIBUTING.md and existing compiler/inspection paths.
No applicable AGENTS.md exists in this worktree or its parent directories.
Work only in this worktree; no publication, paid calls, security-policy changes
or edits to historical approvals. Maximum two repair attempts per failed gate.

BAR before implementation:

1. Reuse the gate compiler, content-addressed ledger and existing expected-head
   trust-anchor mechanism. Do not create another evaluator or signing scheme.
2. Reproduced blockers are specified in F-R3-03 and F-R3-05: misplaced keys and
   empty collections disappear; readers do not inspect a gate-evidence binding.
3. Preserve truly absent gate contracts. Restrict key checks to contract grammar
   contexts, not arbitrary recursive text searches or application argument data.
4. Commit failing tests first, including a valid gate plus another misplaced
   gate, an M3 candidate mismatch with an otherwise valid chain, and positives.
5. Keep declaration admission and evidence inspection independently reviewable
   through logical commits; coordinate the compiler seam with typed-gate work.
6. No dependencies, allowlist changes, policy changes or root-forgery claims.
   A self-consistent rewritten chain remains unauthenticated unless the caller
   supplies a trusted external expected head digest.
