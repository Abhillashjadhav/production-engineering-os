# Setup — PM Production Engineering OS

## Requirements

- Python ≥ 3.11
- git (used for the per-run build workspaces)
- Linux `bubblewrap` and `prlimit` for the bare-bones contract runner. Generated
  code is never executed without this local OS isolation boundary.
- Optional but recommended: `ruff` (format/lint gates on generated code run when it
  is present and are recorded as skipped when it is not)

## Install

```bash
git clone https://github.com/Abhillashjadhav/production-engineering-os
cd production-engineering-os
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"     # runtime-only: pip install -e .
```

On Debian/Ubuntu, install the isolation runtime with:

```bash
sudo apt-get install bubblewrap util-linux
```

Ubuntu 24.04 restricts unprivileged user namespaces through AppArmor. Give only
Bubblewrap permission to create the namespace used by the runner:

```bash
sudo tee /etc/apparmor.d/pmpe-bwrap >/dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>
/usr/bin/bwrap flags=(unconfined) {
  userns,
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/pmpe-bwrap
```

Verify the install:

```bash
pmpe legacy validate examples/taskflow_mvp_spec.yaml
# -> specification OK: TaskFlow (7 requirements)
pytest tests/unit           # fast sanity (~10s); full suite: pytest (~2 min)
```

Virtual environments whose active Python executable is a symlink to a managed
Python installation are supported. The candidate sandbox validates that
interpreter's canonical target against the independently reported Python
base/prefix roots, which are bound read-only. It preserves the original path
when that path is inside a bound root so Python retains virtual-environment
identity; an alias outside those roots is replaced with the validated canonical
path. It does not trust a root derived from the executable target or resolve
candidate-selected command links.

## Legacy compatibility verification

```bash
pytest tests/e2e/test_full_pipeline.py
```

This invokes the explicit `tests.legacy_v1` harness. The harness is not included
in the wheel and has no installed CLI or production entry point. Historical run
directories remain readable with `pmpe legacy status` and `pmpe legacy report`.

## Historical run inspection configuration

Read-only `pmpe legacy status` and `pmpe legacy report` accept a YAML config containing:

```yaml
runs_dir: runs              # where run directories are created
required_gates: [compile, unit, integration, security]
deploy_timeout_s: 15.0
```

Unknown keys are rejected. `--runs-dir` overrides the config file.
