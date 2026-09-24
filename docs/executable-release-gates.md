# Executable release gates

The barebones compiler refuses to silently discard a declared release gate.
Every present gate must bind a non-empty, unique list of existing executable
acceptance criteria through `acceptance_criterion_refs`. The gate passes only
when every referenced criterion has explicit PASS evidence for the candidate
snapshot being considered for release.

Illustrative syntax only; this example is not an approved contract:

```json
{
  "binary_release_gates": [
    {
      "id": "GATE-001",
      "description": "The approved health acceptance check passes.",
      "acceptance_criterion_refs": ["AC-001"]
    }
  ]
}
```

PDC arrays and compiler-native ID maps are accepted under
`binary_release_gates`. Canonical bundles use an ID map under
`quality_assurance.release_gates`, with the same binding field. Supplying both
collections is an error. Description and optional `evidence_expectation` text
remain explanatory; they are never converted into assertions or model judgments.
Unknown fields, unknown criterion references, duplicate IDs and malformed or
unbound gates stop compilation before build or provider execution.

The existing acceptance forms retain their evaluation semantics: structured
actions and assertions, registered measures, bound human tests and pinned
template proofs. Gate bindings name those compiled checks; they do not introduce
a second evaluator or weaken the existing acceptance/security gates.

Each candidate verification emits `release_gates_evaluated` evidence containing
the contract, plan and candidate-manifest digests, attempt number, and every
gate's PASS, FAIL or NOT_EVALUATED result. Each result includes the named
criteria and their explicit outcomes/findings. Interrupted verification or a
security block cannot imply a passing unobserved check. The hash-bound evidence
blob is referenced from a successful `release_ready` event as
`release_gate_evidence_digest`. Any gate without PASS blocks RELEASE_READY.

## Existing contracts and approvals

Contracts that declare no gates retain their existing acceptance-plan digest
and serialized shape. Description-only gate declarations remain valid
historical documents, but the current executable compiler rejects them with
`RELEASE_GATE_UNBOUND`. Schema validity is not proof of executability.

Do not add references to an already approved contract and reuse its approval.
A proposed binding changes contract content and needs a new exact-digest
approval. A product owner must decide whether the named criteria actually prove
the gate. A process, trace, session-evidence or disclosure requirement cannot be
made executable by assigning unrelated product acceptance criteria to it.

The previously approved task-store gates include such unbound process/evidence
requirements. They remain blocked by this compiler until supported, explicitly
approved mechanical bindings exist. This does not rewrite its original
historical DEMONSTRATED result or frozen contract/receipts. The new positive
regression contracts are labeled TEST ONLY and are not replacement approvals.
