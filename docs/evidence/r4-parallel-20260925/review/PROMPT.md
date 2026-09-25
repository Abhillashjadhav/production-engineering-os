# Independent evidence-review workstream

The owner asked to split independent tasks across parallel agents while keeping dependent tasks sequential. The coordinator assigned this workstream to inspect the existing R4 resume evidence, produce a concise acceptance matrix, and prepare permitted final checks after the architecture workstream finishes.

Review inputs are the packet at `docs/evidence/r4-repair-20260924`, its raw retained replay and PMOS handoff outputs, exact archived process/historical/packet source, and the prior independent review. The original reports and frozen v1 artifacts must remain unchanged.

Two final adversarial rechecks were stopped by automatic security screening: planted-bytecode execution and forged/re-chained release-ledger context checks. They remain UNVERIFIED. This workstream must not rerun, rephrase, relocate, delegate, or use CI for them. Ordinary retained baseline and original functional-mutant checks, source inspection, static scanners, and data-only consistency checks are allowed.

Production code changes, workflow changes, remote writes, merges, deployments, approval fabrication and paid model calls are outside this workstream. Root owns integration and publication. Follow-up independent source review occurs only after a final architecture commit exists.
