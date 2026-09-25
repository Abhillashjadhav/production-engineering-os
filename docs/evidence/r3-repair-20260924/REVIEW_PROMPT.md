Review the R3 repairs from source. All changes are draft and unmerged. Do not
interpret test counts, this packet, or author dispositions as proof of readiness.

Use final-publication.json and published-sources.json (plus the admission
follow-up mapping) to resolve exact public commits/trees; do not treat
unavailable historical local hashes as reproducible source. The historical
346-test combined tree is separately pinned by combined-source.json and is not
the current repaired engine. Inspect source before forming a verdict. You may
run bounded offline tests; do not call paid/live providers, change policy, mutate
frozen v1 artifacts, merge, deploy, or assert owner approval from an unsigned hash.

For each claim, report REPRODUCED, SOURCE-ONLY, AUTHOR-REPORTED or UNVERIFIED.
List exact commits, commands, exit codes and files inspected. Explain failures
and skipped checks; an aggregate passing count does not close a finding.

1. Reproduce replay completeness across all three cases. Independently derive
   the 30 required boundaries and 14 process records, check retained stdout
   against the unchanged 14 criteria, and verify freeze/evaluator identities.
2. Confirm gate declarations cannot vanish through misspelling, misplacement or
   empty containers at supported contract metadata boundaries. Ensure legitimate
   application data is not interpreted as a gate declaration.
3. Challenge retained inspection: missing/failed gates, stripped or malformed
   compiled criteria, mismatched contract/plan/candidate identities, and later
   verification failure after an earlier PASS must not establish eligibility.
4. Distinguish an internally inconsistent evidence substitution from a fully
   self-consistent rewrite. Check an independently supplied expected head rejects
   rewrites; do not claim unsigned hashes authenticate an owner or defeat root.
5. Check PDC digest syntax and explicit unverified provenance/approval flags,
   including fabricated but correctly formatted values and package tampering.
6. For the separately pinned typed-process-gate migration, preserve the meaning
   of every original gate and criterion. Test missing controls, unrelated crashes,
   reordered/missing observations, modified protected source, exact full-snapshot
   provenance across attempts, unknown sandbox implementations, and replay mode.
   A replay must not pass the fresh-generation obligation. A test provider does
   not prove live-model generation; record attestation limitations explicitly.
7. Ensure source manifest and outer freeze avoid a digest cycle. Revised contract,
   plan and receipt require their own exact identities; no original approval is
   silently reused. No fresh run can be inferred from a draft or fixture.

Accepted review: incomplete evidence, unpublished source, ignored declarations,
provenance/authority limitations, current-engine task-store gap, and F-09's
incorrect deferral explanation. Rejected proposal detail: putting a final freeze
inside the contract that it hashes is circular. Replace with an immutable source
manifest plus a later outer freeze. Process obligations cannot be replaced by
criterion conjunctions merely to obtain PASS.

F-09 remains an owner system-of-record decision. Keep both monitoring systems;
no source deletion is part of this repair. Career-assistant requirements belong
to a separate product brief.

Output: verdict; findings ordered by severity with exact paths and reproduction;
which prior findings are fixed/open; smallest necessary remaining changes; and
separate statements for source correctness, replay proof, fresh approved delivery,
and merge status. Never combine those four conclusions into one readiness label.
