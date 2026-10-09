# W4 — PMOS checks and publisher pins (2026-10-09)
(Report text transcribed by the integration owner from W4's hand-back; raw logs in logs/, exit ledger logs/exit-codes.txt.)

Result: every configured PMOS check at cafe8b4 passes except the by-design freeze RED
(`test_task_tracker_freeze` 3 ok / 1 FAIL: decision-to-contract/SKILL.md frozen ad0978c8… != current f14623cb…).
audit 40/3/7, handoff 6/6, beacon 7/7, validation regressions 9/9, lint 47/47 files (423/423 checks),
validate_contract.py @5c0f9e3a PASS, py_compile 0, PR gate PASS (3.12 and 3.13), public-smoke 5/5 (3.11).
Undocumented full discover: 33 run, 32 ok, 1 FAIL (same RED). In Actions the audit job stops at the RED step,
so lint/install/validate/py_compile would be skipped there.

Pins (kept distinct):
- 297a11d7 (generic current-authoring, exact workflow `pip install git+https://…@297a11d7`): HANDOFF_SETUP_OK, test_current_authoring 7/7.
  Compiling the frozen PMOS-TASK-TRACKER-001 contract at 297a11d7: AcceptanceCompileError RELEASE_GATE_UNBOUND:GATE-001..GATE-005.
- e8a929d (task-tracker baseline, worktree install): test_current_authoring 5/7 — both failures
  `AssertionError: AcceptanceCompileError not raised` (test_description_only_gate_is_rejected_by_current_compiler line 154;
  test_historical_fixture_is_unbound_at_documented_pin line 135). For its purpose: frozen contract compiles to 14 criteria,
  canonical_digest(plan) == frozen sha256:4d552932…, plan_digest == sha256:1dad520e…; validate_contract PASS.
- Unapplied pin patch (stage-a/pmos-pin-e8a929d.patch), disposable copy only: changes 4 files; with git+https e8a929d install:
  HANDOFF_SETUP_OK, test_handoff_setup 6/6, test_current_authoring 5/7; leaves stale RELEASE_GATE_UNBOUND prose in HANDOFF.md,
  docs/VALIDATION.md §3, fixtures.md lines 34/66.
- Bound PEOS bytes (204): e8a929d = 204/204 vs candidate; f7669c2 = 204/204 vs active; 297a11d 197/6 mismatch/1 missing vs candidate.
- Conclusion: no single pin satisfies both jobs; the generic test requires rejecting ref-less gates, the approved contract's gates are ref-less.

Incident (environment, caused by W4): `pip install git+file://$W/peos@e8a929d` made pip do a --filter=blob:none clone of a shallow
local clone → infinite promisor lazy-fetch loop (~6.6k git, ~4.4k upload-pack, ~13 GB) → OOM kills (W2 full suite exit 137;
TT1 attempts exit 137). W4's targeted cleanup killed 4,324 matching processes at 14:58:18Z (logs/runaway-cleanup.log).
Final scan: 0 processes referencing $W. Host repositories untouched.
