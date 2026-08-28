# Exact Phase B template selection

Issue [#183](https://github.com/Abhillashjadhav/production-engineering-os/issues/183)
implements the architecture-approved schema/compiler slice from issue
[#175](https://github.com/Abhillashjadhav/production-engineering-os/issues/175).
Selection happens before any provider, model, tool, candidate, or deployment
execution.

## Admitted identities

Only two exact pairs exist:

| Type | Version | Runtime model mode | Purpose |
| --- | --- | --- | --- |
| `barebones_e1` | `1.0.0` | `recorded` | Existing frozen E1 candidate skeleton |
| `recorded_tool_agent` | `1.0.0` | `recorded` | Phase C's bounded two-tool replay target |

The compiler uses two explicit conditional branches. It has no template registry,
alias, discovery mechanism, compatibility fallback, best-match routing, or LLM
classification. `latest`, unknown versions, and content-digest drift halt.

## Contract extension

An approved contract supplies `implementation_selection` using
[`phase_b_template_selection.schema.json`](../schemas/phase_b_template_selection.schema.json).
The extension binds:

- exact type, version, and immutable content digest;
- one closed capability vocabulary and the requested capability IDs;
- an existing acceptance criterion and admitted verifier for every capability;
- `runtime_model_mode: recorded`;
- flat, named, non-secret configuration;
- exact tool IDs and repository-relative resource scopes;
- attempt, byte, step, tool-call, and wall-time budgets; and
- exact recorded-fixture identity and digest.

Unknown fields are never ignored. Configuration rejects secret-named keys,
credential-shaped values, and nested structures. Tool scope rejects wildcards,
traversal, dynamic identities, and undeclared tools.

## Approval and evidence binding

The separate `phase-b-template-approval/v1` receipt is checked against a named
expected approver and trusted clock. Its immutable subject directly binds the
canonical contract and selection digests, schema version, template identity,
capabilities, runtime mode, configuration, tools, budgets, and fixture. Mutation,
expiry, future approval time, or a different approver halts compilation.

Successful compilation emits canonical bytes containing:

- the exact contract, selection, approval, template, fixture, and plan digests;
- the normalized budgets, configuration, tools, and verifier set; and
- one immutable evidence subject per declared capability, binding its acceptance
  criteria and automated verifier.

Three compilations of either admitted fixture are byte-identical.

## Claim boundary

This proves deterministic selection and validation for two concrete identities.
It does not implement the second runtime, prove a reusable template protocol,
provide live-model access, generalize tools, mutate infrastructure, deploy a
candidate, or make a production-readiness claim. Phase C may begin only after a
fresh review approves this exact schema/compiler output.
