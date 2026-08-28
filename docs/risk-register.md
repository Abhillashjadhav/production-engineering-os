# Risk register — PM Production Engineering OS V1

| ID | Risk | Level | Mitigation | Residual |
|---|---|---|---|---|
| R1 | Generated code merges with failing gates | High | Merge gate requires every required gate green + zero blocking findings; merge step refuses otherwise; e2e test plants a failure and asserts NO_MERGE | Low |
| R2 | Pipeline silently makes a product decision | High | Validator escalates missing/contradictory product decisions; planner/architect only consume spec fields, never invent scope; escalations are files a human must approve | Low |
| R3 | Security-sensitive generated code (auth) is wrong | High | Auth template uses `hmac.compare_digest`, token from environment (never hardcoded); security gate (bandit + built-in scanner) runs on every build; policy marks auth work medium-risk with logged justification | Medium — V1 auth is a static bearer token, documented limitation |
| R4 | Deployment verification gives false confidence | Medium | Smoke test exercises the real main user journey over HTTP against the really-running process, not mocks; health check + journey both required | Medium — local deploy ≠ production environment |
| R5 | Workflow state corruption on crash | Medium | State written atomically (tmp+rename) after every step; resume re-enters at first non-done step; failure-recovery test covers it | Low |
| R6 | Reviewer/fixer damages code (bad autofix) | Medium | Fix agent only applies allow-listed, formatting-level fixes; all gates re-run after fixes; anything else escalates | Low |
| R7 | Flaky e2e (port collisions, orphan processes) | Medium | Deployer binds port 0 (OS-assigned), waits on health with timeout, always terminates the process in finally | Low |
| R8 | Untestable acceptance criteria pass validation | Medium | Validator flags vague ACs (no measurable/observable phrasing) as warnings/questions; test architect refuses to map an AC it cannot express as an assertion — that AC becomes an escalation | Medium — heuristics, not proofs |
| R9 | Activity-only NSM accepted | Medium | Validator flags NSMs with activity verbs and no outcome language | Medium — heuristic |
| R10 | Cost/complexity creep in the OS itself | Medium | Module size lint (ruff), no third-party runtime deps beyond PyYAML, CI complexity checks | Low |
| R11 | This repo's own content damaged by the build | High | Additive-only layout; runs/ gitignored; tests never write outside tmp dirs and runs/ | Low |

## Contradictions found in the task (and their resolutions)

1. "Generate tests before implementation" + "run tests" — generated tests necessarily
   fail before implementation. Resolution: an explicit `confirm_red` step runs them and
   *requires* failure, turning the contradiction into evidence of tests-first.
2. "Medium: proceed with logged justification" vs "no merge without passing gates" —
   resolution: risk levels gate *human waiting*, never quality gates. Medium skips the
   wait, never the checks.
3. Repo layout in the task (src/domain/ at root) vs existing pm-agent-os content —
   resolution: single `src/pmpe/` package with the same submodule names (documented in
   ARCHITECTURE.md), everything additive.
