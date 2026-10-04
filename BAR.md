# BAR — local frontend loopback default

Unit: SEC-LOCAL-001, isolated on `fix/peos-loopback-preview-20260924` from
`dd4271b70fcb9cb5b9dd279fe516c2fe50806751`. Scope is the existing Vite dev/preview
launch path, its regression contract, and explicit sharing instructions.

1. **Does this already exist? Yes, restructured to reuse it.** Extend the existing
   npm scripts, Vite configuration and toolchain tests; add no parallel server.
2. **Is there an approved criterion or reproduced blocker? Yes.** The authorized
   local-access review reproduced wildcard defaults in npm dev/start and both
   Vite modes; the root authorized this bounded fix as SEC-LOCAL-001.
3. **Does this change behavior with a caller or test? Yes.** Network peers will
   no longer reach a directly started local preview by default. Existing local
   Playwright and preview.sh callers use loopback. Docker serves static assets
   through nginx and retains its existing loopback host-port publication.
   Deliberate shared previews retain Vite's explicit `--host` CLI option.
4. **Is there a failing-before/passing-after check? Yes, test first.** The new
   regression checks both configured hosts and npm CLI overrides for loopback
   defaults. Run and record its failure on unmodified production files before
   changing them, then run the full existing toolchain regression file.
5. **Can this be reverted as one unit? Yes.** The test-first and fix commits on
   this concern-only branch can be reverted together without touching other work.
6. **Does this add unrequested settings, dependencies or extension surfaces?
   No.** Reuse Vite's existing CLI override; add no setting or dependency.

Prompt: Make the existing local frontend default to loopback, preserve explicit
CLI sharing and the Docker nginx/Compose behavior, record RED before the fix,
commit locally only, and hand off for independent review before remote actions.

Verification: the new regression failed on the unmodified wildcard default
before test commit `d151a5e`. After the fix, all six existing/new toolchain tests
pass. Temporary-copy mutations restoring a wildcard in each of the two npm
scripts and the two Vite modes were all rejected. Ruff check, Ruff format check
and `git diff --check` pass. No server was started and no network or laptop probe
was run. Frontend build/browser E2E were not run for this configuration-only
change. Independent root review passed; its check and the retained RED/GREEN
evidence are in `docs/evidence/github-local-access-20260924/`. Remote publication
is reported separately in the PR.
