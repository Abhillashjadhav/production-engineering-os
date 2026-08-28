# ADR-005: Local process deployment with real smoke verification

Status: Accepted · Date: 2026-07-12 · Risk: medium · Reversibility: reversible (adapter seam)

## Context
The lifecycle ends in deployment + production validation. V1 has no cloud target and
must verify without one, yet "verification" must not be a mock.

## Decision
`DeploymentAdapter` is an interface. V1's `LocalProcessDeployer` starts the generated
app as a real subprocess on an OS-assigned port, waits for `/health`, executes the main
user journey over real HTTP (create → list → complete), writes rollback instructions,
and records a typed `DeploymentResult`. It also emits a deployable artifact: run
script, Dockerfile, and deployment instructions.

## Consequences
+ "Deployed and verified" means a real process answered real requests.
− Local deploy is not production; the result is labeled `environment: local`. Cloud
  adapters are V2. Production-target requests are high-risk escalations by policy.
