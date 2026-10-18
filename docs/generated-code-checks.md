# Generated code checks inside PEOS

The normal pmpe barebones run path now requires the
python-stdlib-quality/v1 profile. Install PEOS with its documented [dev]
dependencies; missing Ruff or mypy halts before model work rather than skipping
checks. No external model call or deployment is added by these checks.

## Stages and their evidence

| Stage | Mechanism | Evidence required |
| --- | --- | --- |
| Prepare | Existing pinned Python template and approved contract | Runnable baseline and valid receipt |
| Specify | Existing deterministic contract compiler and protected tests | Every declared requirement maps to an executable criterion |
| Generate and repair | Generation policy plus acceptance, syntax, format, lint, strict typing, static import and security checks | Exact candidate passes every applicable check within the attempt budget |
| Deliver | Exact verified sources, quality report, use guidance and integrity manifest | Source package verifies against the separately retained manifest digest |

These are four workflow stages, not four individual tests.
The generated-code profile adds six static checks:

- Syntax: parse generated Python sources without importing them; excessive
  parser recursion fails as a recorded finding.
- Dependencies: reject statically declared imports outside Python's standard
  library and candidate-local modules.
- Verification integrity: reject inline Ruff/mypy/type-ignore suppression comments
  and typing.no_type_check imports/decorators.
- Formatting: ruff format --isolated --check.
- Lint: ruff check --isolated --select E9,F.
- Types: mypy --strict with an explicit empty configuration and no installed
  third-party packages.

Tools inspect disposable source copies. Candidate tool configuration is not
loaded. The builder receives the same profile rules, and failures return as
repair findings. The review invocation receives the actual source and contract;
its model verdict remains advisory and is not substituted for executable checks.
Verifier-owned acceptance tests stay in the candidate identity and retain their
execution/integrity checks; their own formatting, typing, and pytest imports are
not imposed on the generated-code profile.

## Delivery

A successful approved CLI run returns delivery.directory and
delivery.manifest_digest. Retain that digest outside the delivered directory.
Verify a transferred copy with:

    pmpe barebones verify-delivery /path/to/delivery \
      --expected-manifest-digest sha256:<digest-returned-by-the-build>

Changed, missing, extra, and symlink files fail verification. Export reads sealed
evidence blobs, not potentially changed workspace files. A blocked export returns
a nonzero CLI exit status even if the core candidate reached RELEASE_READY.

## Boundaries

This implementation supports the existing Python/standard-library core. It does
not add a general architecture planner, JavaScript templates, third-party
dependency auditing, hosting, or customer authentication. Unsupported generated
code stacks fail this profile. Static import analysis is not a sandbox or a proof
against dynamic imports. The existing sandbox and security controls still apply.

VERIFIED_SOURCE_PACKAGE means verified source delivery and NOT_DEPLOYED means
no hosted link exists. A customer-facing deployment still needs its declared
target, authorized credentials, release decision, and live journey evidence.

Direct Python callers retain enforce_quality=False for compatibility; their
evidence explicitly records that quality was not requested and they cannot use
the new delivery path to claim this profile passed. The public CLI has no
quality-skip flag.
