---
name: decision-contract-builder
description: "Turn a product brief and gated PMOS outputs into a complete ProductDecisionContract, ask only blocking product questions, obtain explicit approval bound to the exact draft digest, and hand the approved contract to Production Engineering OS. Use this skill when the user asks to build, approve, publish, or hand off a product decision for engineering. Do NOT invent product truth, approve on the user's behalf, or use it for implementation after an approved contract is already locked."
---

# Decision Contract Builder

Convert product intent into the immutable boundary PEOS can execute. The user owns the
problem, outcome, scope, metrics, trade-offs, and approval. The skill owns collection,
validation, traceability, and handoff mechanics.

## Workflow

1. Gather the user brief and any gated PMOS outputs.
2. Create one answers JSON object containing every ProductDecisionContract field.
3. Run:

   ```bash
   pmpe contract draft --answers <answers.json> --output <authoring-dir>
   ```

4. If exit code is `3`, read `blocking-questions.json`. Ask only those questions. Do not
   fill missing answers from chat inference, repository code, or an engineering default.
5. Update the answers as user-owned truth and rerun `contract draft`.
6. When a draft is ready, show the user:
   - problem, target user, desired outcome;
   - North Star, leading metrics, and guardrails;
   - scope and explicit exclusions;
   - requirements, acceptance criteria, release gates, risks, and required approvals;
   - the exact `draft_digest` from `draft-summary.json`.
7. Ask the user to choose **approve**, **edit**, or **reject**. Only an explicit approve may
   continue.
8. On approve, run:

   ```bash
   pmpe contract approve \
     --draft <authoring-dir>/contract-draft.json \
     --expected-digest <exact-draft-digest> \
     --approver <named-user> \
     --approved-at <RFC3339-time> \
     --output <approval-dir>
   ```

9. Verify `contract-approved.json` and `approval-receipt.json` exist. Any content change
   after review invalidates the digest and requires a fresh draft and approval.
10. Start engineering only from the approved artifact:

   ```bash
   pmpe contract handoff \
     --contract <approval-dir>/contract-approved.json \
     --receipt <approval-dir>/approval-receipt.json \
     --expected-approver <named-product-owner> \
     --run-dir <run-dir>
   ```

11. Return the locked contract digest and run ID. Do not claim code, a pull request, or
    deployment exists until its own PEOS evidence proves it.

## Required answer fields

Collect: product name; problem; target user; desired outcome; scope; exclusions;
functional requirements; acceptance criteria; binary release gates; scored eval rubric;
golden cases; outcome North Star; leading metrics; guardrails; non-functional requirements;
known risks; approved product decisions; required approvals; contract ID/version when the
user already has a lineage.

## Gates

- No missing required truth.
- Every acceptance criterion references an existing requirement.
- Every requirement has at least one acceptance criterion.
- North Star describes an outcome, not prompts, logins, or tasks generated.
- Draft remains `DRAFT` until a named user approves the exact digest.
- Approval receipt binds both the reviewed draft and resulting approved contract.
- Changed content never reuses an earlier approval.
- PEOS handoff accepts only a runnable approved contract.

## Limitations

- The deterministic builder validates supplied truth; it does not determine whether the
  product strategy is correct.
- V2 is the current PEOS handoff format. Native canonical-bundle intake remains a separate
  runtime evolution.
- External authority and production-release approval remain outside this authoring skill.
