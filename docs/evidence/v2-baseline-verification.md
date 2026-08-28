# V2 baseline verification (V1 head, pre-modification)

Date: 2026-07-16 · Branch point: `6d7977e` (head of PR #1, `claude/pm-production-engineering-os-ggzl9x`)
V2 branch: `claude/production-engineering-os-v2` created from this commit.

All commands run from the repo root against the untouched V1 head, using the
project venv (`.venv`, Python 3.11.15).

| # | Command | Result |
|---|---|---|
| 1 | `.venv/bin/python -m pytest` | **151 passed** in 162.10s |
| 2 | `.venv/bin/ruff format --check src tests/unit tests/integration tests/e2e tests/conftest.py` | 79 files already formatted |
| 3 | `.venv/bin/ruff check src tests/unit tests/integration tests/e2e tests/conftest.py` | All checks passed! |
| 4 | `.venv/bin/mypy` (strict, per pyproject) | Success: no issues found in 56 source files |
| 5 | `.venv/bin/bandit -r src -q --severity-level high` | 0 high-severity issues |
| 6 | `.venv/bin/python -m build --wheel` | Successfully built pmpe-0.1.1-py3-none-any.whl |
| 7 | `pmpe validate examples/taskflow_mvp_spec.yaml` | `specification OK: TaskFlow (7 requirements)` |
| 8 | `pmpe run examples/taskflow_mvp_spec.yaml --runs-dir <tmp>` (from a foreign cwd) | `{"status": "success"}` — full 18-step lifecycle incl. verified local deploy |

Conclusion: the V1 baseline is green on every gate V2 must preserve. Any V2
regression against these commands is a V2 defect, not a pre-existing one.
