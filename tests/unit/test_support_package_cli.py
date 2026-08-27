from __future__ import annotations

import json
from pathlib import Path

from pmpe.cli import main


def test_package_support_build_and_verify_cli(tmp_path: Path) -> None:
    contract = Path("examples/support-package/contract.json")
    bundle = tmp_path / "bundle"

    assert (
        main(
            [
                "barebones",
                "package",
                "build",
                "--contract",
                str(contract),
                "--output",
                str(bundle),
            ]
        )
        == 0
    )
    assert main(["barebones", "package", "verify", "--bundle", str(bundle)]) == 0
    assert json.loads((bundle / "manifest.json").read_text())["state"] == "PACKAGE_READY"


def test_package_support_cli_rejects_tampered_bundle(tmp_path: Path) -> None:
    contract = Path("examples/support-package/contract.json")
    bundle = tmp_path / "bundle"
    assert (
        main(
            [
                "barebones",
                "package",
                "build",
                "--contract",
                str(contract),
                "--output",
                str(bundle),
            ]
        )
        == 0
    )
    (bundle / "app.py").write_text("tampered\n")

    assert main(["barebones", "package", "verify", "--bundle", str(bundle)]) == 2
