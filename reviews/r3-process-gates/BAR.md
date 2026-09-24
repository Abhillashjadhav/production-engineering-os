# BAR — typed process gates (DRAFT migration)

1. **Yes, restructured.** Extend existing compiler, release-gate event and run_to_release_ready; reuse _verify_snapshot for mutants. Historical adapter has guard/recording concepts but no core process-gate evaluator.
2. **Yes.** Original task-store GATE-002–005 and R3 migration request require runtime-bound evidence; approved v1 remains blocked and unchanged.
3. **Yes.** New typed bindings and optional runtime input change declared process-gate behavior on isolated feat/r3-process-gates. Criteria-only and no-gate bytes are compatibility controls.
4. **Yes.** Commit regression tests and capture RED before implementation: four bindings currently unsupported; no runtime inputs/collectors/evaluators exist.
5. **Yes.** Tests, implementation and retained evidence form one reviewable migration concern, independently revertible from admission/inspection fixes.
6. **No.** Typed process inputs implement explicitly authorized gates. All proposed task-store bindings remain DRAFT, with no approval or fresh call implied.
