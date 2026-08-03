# Setup — PM Production Engineering OS

## Requirements

- Python ≥ 3.11
- git (used for the per-run build workspaces)
- Optional but recommended: `ruff` (format/lint gates on generated code run when it
  is present and are recorded as skipped when it is not)

## Install

```bash
git clone https://github.com/Abhillashjadhav/production-engineering-os
cd production-engineering-os
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"     # runtime-only: pip install -e .
```

Verify the install:

```bash
pmpe validate examples/taskflow_mvp_spec.yaml
# -> specification OK: TaskFlow (7 requirements)
pytest tests/unit           # fast sanity (~10s); full suite: pytest (~2 min)
```

## Legacy compatibility verification

```bash
pytest tests/e2e/test_full_pipeline.py
```

This invokes the explicit `tests.legacy_v1` harness. The harness is not included
in the wheel and has no installed CLI or production entry point. Historical run
directories remain readable with `pmpe status` and `pmpe report`.

## Historical run inspection configuration

Read-only `pmpe status` and `pmpe report` accept a YAML config containing:

```yaml
runs_dir: runs              # where run directories are created
required_gates: [compile, unit, integration, security]
deploy_timeout_s: 15.0
```

Unknown keys are rejected. `--runs-dir` overrides the config file.
