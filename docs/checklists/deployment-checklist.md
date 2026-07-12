# Deployment checklist (per build)

- [ ] Merge gate said MERGE (never deploy a NO_MERGE build)
- [ ] `deployment_result.json`: `healthy: true` and `journey_passed: true`
- [ ] Journey covered the main user path (create → list → complete → read-back for
      the CRUD stack) and the negative auth check (401 without token)
- [ ] `verification.json`: all checks true
- [ ] Deployable artifact complete in workspace `deploy/`: `run.sh`, `Dockerfile`,
      `DEPLOYMENT.md`, `ROLLBACK.md`
- [ ] Rollback instructions read and understood BEFORE promoting the artifact anywhere
- [ ] Token generated fresh for the target environment (never reuse the verify token)
- [ ] SQLite data file location (`APP_DB`) is on persistent, backed-up storage
- [ ] For any non-local target: the `deployment.production_target` escalation was
      approved by a named human (V1 has no cloud adapter — the artifact is promoted
      manually)
