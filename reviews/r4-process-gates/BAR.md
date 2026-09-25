# R4 process repair BAR

1. Existing path? Yes: extend typed process bindings, collectors and evaluators; no parallel runner.
2. Required blocker? Yes: R4 F-C6-1..8, N-1/N4 and C7-02 reproduced/source findings require these changes.
3. Existing behavior changes? Yes: old unbound mutants and attestation-derived PASS become inadmissible/nonpassing; isolated feat/r4-process branch and focused regressions retain the compatibility boundary.
4. Failing check first? Yes: task-tracker observer crashes, duplicated mutant slots, class spoof, stateful report, freshness and cache admission RED are committed before implementation.
5. Single reversible unit? Yes: process correctness repair plus required evidence; pure inspection helper is a separate commit for reuse by #211.
6. New unapproved setting/dependency/surface? No: strengthen existing gate inputs; new snapshot binding identities remain unapproved DRAFT and no runtime dependency is added.
