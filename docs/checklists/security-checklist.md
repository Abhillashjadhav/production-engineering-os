# Security checklist (per build)

Enforced automatically by the pipeline; listed here for human audit of any run.

- [ ] `runs/<id>/artifacts/gate_results_retest.json`: `security` gate passed
- [ ] No `SEC_*` findings in `review_report_final.json`
- [ ] Generated `app/auth.py` (when auth is in scope): token from env only,
      `hmac.compare_digest`, no logging of the token
- [ ] Generated `app/server.py` refuses to start without `APP_TOKEN` (auth builds)
- [ ] Generated storage: every runtime value bound with `?` placeholders
- [ ] Spec entity/field names passed `INVALID_IDENTIFIER` validation
- [ ] No secrets in any artifact: `grep -ri "token.*=" runs/<id>/artifacts/` is clean
      of literal values (names of env vars are fine)
- [ ] Security-sensitive escalations (if any) carry a named approver and reason
- [ ] `deploy/Dockerfile` does not bake a token (APP_TOKEN provided at runtime only)
