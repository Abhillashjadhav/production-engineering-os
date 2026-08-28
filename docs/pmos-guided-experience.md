# PMOS guided local experience

Issue #120 adds a non-technical, mobile-first surface over the existing PMOS
contract APIs. It does not add a second approval or ProductChangeRequest rule
engine: the server delegates those decisions to `pmpe.contracts.authoring` and
`pmpe.contracts.change_request`.

## Run it

```bash
pmpe guided serve --workspace /tmp/pmos-guided
```

Open `http://127.0.0.1:8765`. The default server binds only to loopback, loads
no remote assets, and has no connector or model integration.

The authoring path asks one blocking question at a time. When product truth is
complete, the backend produces a schema-valid draft and an approval card bound
to its exact digest. The card always shows impact, reversibility, evidence,
cost, and permissions. Approval persists the approved contract and receipt.
Subsequent product changes are recorded through `ProductChangeRequest`; the
approved artifact is never edited.

The import path accepts the repository's canonical bundle and manifest as raw
JSON, preserving duplicate-key detection. It validates both schemas and checks
bundle, approval, manifest, identity, version, and provenance bindings.
Schema- and binding-valid artifacts are stored as validated pending governed
admission; this local surface never claims authoritative admission. Ambiguous,
lossy, or mismatched artifacts are held in a permission-isolated local
quarantine with named diagnostics.

## Local-mode boundary

This surface is a developer/personal quickstart. Its quarantine is protected by
local file permissions, not by the production intake encryption provider. The
server refuses non-loopback binding. Production deployments must add
authenticated sessions, CSRF protection, and the governed intake providers
documented by the canonical pipeline.
