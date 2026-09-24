# Exact-SHA secret gate follow-up

The unchanged repository secret gate reproduced two findings at local head
`6a9a1ec73ce9248040956d1b5b0f86ddbfc97cc8`: the existing synthetic fixtures in
`tests/unit/test_support_package_v1.py`, lines 564 and 567. The protected
allowlist binds the original fixture locations at lines 563 and 566. A new
module-level import for the portable-proof regression shifted these lines.
There were no findings in review logs, so no log values were redacted.
`secret-followup-before.json` contains only the scanner's redacted findings.

Parent-approved correction: move the new portable-proof regression into its
own test module and restore the original large fixture module byte-for-byte to
base `f18395a3edb53d7c450fc87660e55b1dc1ce073b`. The new regression still scans
the generated proof and runs both positive and deliberately broken behavior.
This preserves fixture bytes, avoids padding or obfuscation, and leaves source,
scanner, policy, allowlist and CI unchanged. Existing shared test assembly is
reused rather than copied. This is test organization; no product behavior or
acceptance criterion changes. The CI secret failure is the retained RED gate;
this is its first repair attempt.

The standalone regression passes: generated proof scanning is clean, the
reference package runs two passing unittest cases, and the broken app runs the
same two cases as assertion failures. Both test modules pass Ruff lint and
format checks. The unchanged original module matches its base Git blob.
