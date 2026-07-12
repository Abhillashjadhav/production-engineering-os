"""Pipeline configuration with validation.

Chaos fields exist for the test suite only: they let the e2e tests plant failures
(injected files, simulated crashes) without patching internals. They are documented,
explicit, and default to off.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from pmpe.domain.errors import ConfigError


@dataclass
class PipelineConfig:
    runs_dir: Path = Path("runs")
    schema_path: Path = Path("schemas/mvp_spec.schema.json")
    required_gates: list[str] = field(
        default_factory=lambda: ["compile", "unit", "integration", "security"]
    )
    lint_generated: bool = True  # run ruff over generated code when ruff is available
    deploy_timeout_s: float = 15.0
    # --- test/chaos hooks (off by default; see module docstring) ---
    chaos_inject_files: dict[str, str] = field(default_factory=dict)
    chaos_fail_at_step: str | None = None

    def __post_init__(self) -> None:
        self.runs_dir = Path(self.runs_dir)
        self.schema_path = Path(self.schema_path)
        if self.deploy_timeout_s <= 0:
            raise ConfigError("deploy_timeout_s must be positive")
        if not isinstance(self.chaos_inject_files, dict):
            raise ConfigError("chaos_inject_files must be a mapping of path -> content")

    @classmethod
    def load(cls, path: Path | None = None) -> PipelineConfig:
        """Load configuration from a YAML file; unknown keys are rejected."""
        if path is None:
            return cls()
        try:
            raw: Any = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"cannot read config {path}: {exc}") from exc
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ConfigError(f"config {path} must be a mapping")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ConfigError(f"unknown config keys: {', '.join(unknown)}")
        return cls(**raw)
