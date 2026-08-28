# Contributing

This repo hosts two systems: **pm-agent-os** (Markdown skills under `.claude/`) and
**PM Production Engineering OS** (`src/pmpe`). Rules common to both are in CLAUDE.md:
no direct pushes to main, every change lands through a PR, `/pr-review` before merge,
one concern per PR.

## Working on `src/pmpe`

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                      # full suite (unit + integration + e2e, ~2 min)
ruff format --check src tests/unit tests/integration tests/e2e tests/conftest.py
ruff check src tests/unit tests/integration tests/e2e tests/conftest.py
mypy                        # --strict, configured in pyproject.toml
bandit -r src -q
```

### Non-negotiables

1. **Tests before implementation.** New behavior lands as a failing test first; the
   commit order in the PR is the evidence (same discipline the pipeline itself enforces
   on generated products via `confirm_red`).
2. **Conventional commits** (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `ci:`),
   small and logically complete.
3. **mypy --strict and ruff must be clean**; no file over ~400 lines.
4. **Every automated decision needs a named rule** — new policy behavior goes through
   `pmpe/policies/engine.py` with a `POL-xxx` id, new review checks carry a `REV_*`
   rule id, new scanner rules a `SEC_*` id.
5. **No new runtime dependencies** without an ADR under `docs/adr/`.
6. **Traceability**: reference the requirement (SYS-xx from docs/technical-requirements.md)
   or issue in the PR description.

## Working on skills (`.claude/skills`)

Follow the three-gate harness in CLAUDE.md: fixtures before instructions,
`python3 tests/lint_skill.py` clean, PR-review record.

## PR checklist

Use the template (.github/pull_request_template.md): requirement reference,
architecture impact, tests added, risk level, rollback plan, evidence.
