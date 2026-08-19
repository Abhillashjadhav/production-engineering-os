"""Configuration defaults and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.config import PipelineConfig, packaged_schema_path
from pmpe.domain.errors import ConfigError


def test_default_schema_is_packaged_and_exists() -> None:
    config = PipelineConfig()
    assert config.schema_path == packaged_schema_path()
    assert config.schema_path.exists()


def test_packaged_schema_stays_in_sync_with_repo_contract(repo_root: Path) -> None:
    """schemas/ files are the documented contracts; the packaged copies must be
    byte-identical so `pmpe` behaves the same from any directory."""
    from pmpe.config import packaged_schema_dir

    for name in (
        "mvp_spec.schema.json",
        "product_decision_contract.schema.json",
        "fullstack_product_contract.schema.json",
        "pmos_contract_bundle.schema.json",
        "pmos_contract_manifest.schema.json",
        "personal_workflow_request.schema.json",
    ):
        contract = (repo_root / "schemas" / name).read_bytes()
        assert (packaged_schema_dir() / name).read_bytes() == contract, name
    assert packaged_schema_path().exists()


def test_unknown_config_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "pmpe.yaml"
    path.write_text("runs_dir: runs\ntypo_key: true\n")
    with pytest.raises(ConfigError, match="typo_key"):
        PipelineConfig.load(path)


def test_chaos_keys_are_rejected_in_config_files(tmp_path: Path) -> None:
    """Test-only hooks must not be reachable from user-facing config (injection risk)."""
    path = tmp_path / "pmpe.yaml"
    path.write_text('chaos_inject_files:\n  app/evil.py: "x = 1"\n')
    with pytest.raises(ConfigError, match="test-only"):
        PipelineConfig.load(path)


def test_invalid_timeout_is_rejected() -> None:
    with pytest.raises(ConfigError):
        PipelineConfig(deploy_timeout_s=0)


def test_config_loads_overrides(tmp_path: Path) -> None:
    path = tmp_path / "pmpe.yaml"
    path.write_text("runs_dir: /tmp/other-runs\ndeploy_timeout_s: 30\n")
    config = PipelineConfig.load(path)
    assert config.runs_dir == Path("/tmp/other-runs")
    assert config.deploy_timeout_s == 30
