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

## First full run

```bash
pmpe run examples/taskflow_mvp_spec.yaml
# -> {"run_id": "run-...", "status": "success", "run_dir": "runs/run-..."}
pmpe report <run_id>        # the final traceability/build report
```

Everything a run produces lives under `runs/<run_id>/` (gitignored):
`state.json`, `events.jsonl`, `artifacts/`, `escalations/`, `approvals/`, and
`workspace/` — the generated product as its own git repository.

## Configuration (optional)

`pmpe run spec.yaml --config pmpe.yaml` — YAML with any of:

```yaml
runs_dir: runs              # where run directories are created
required_gates: [compile, unit, integration, security]
deploy_timeout_s: 15.0
```

Unknown keys are rejected. `--runs-dir` overrides the config file.
