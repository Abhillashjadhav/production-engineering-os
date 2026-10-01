"""Selected real-host proof for the offline outer-provider Bubblewrap launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pmpe.cli import main
from pmpe.evidence.ledger import EvidenceLedger

ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(
    os.environ.get("PMPE_TEST_REAL_SANDBOX") != "true",
    reason="requires the dedicated CI namespace runtime and protected system Python",
)
def test_real_offline_provider_cannot_write_host_or_forge_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the actual CLI -> provider launcher -> engine path, with no credentials."""
    bundle = tmp_path / "provider-bundle"
    bundle.mkdir()
    evidence = tmp_path / "evidence"
    workspace = tmp_path / "candidate"
    marker = tmp_path / "trusted-marker"
    marker.write_text("unchanged")
    contract = ROOT / "examples/barebones/e1-contract.json"
    receipt = ROOT / "examples/barebones/e1-approval-receipt.json"
    verifier = ROOT / "src/pmpe/barebones.py"
    originals = {path: path.read_bytes() for path in (marker, contract, receipt, verifier)}
    targets = (marker, verifier, contract, receipt, evidence / ".pmpe")
    host_pid = os.getpid()
    monkeypatch.setenv("PEOS_PLANTED_SECRET", "must-not-cross")
    adapter = (
        "import json,os,signal,socket,subprocess,sys\n"
        "from pathlib import Path\n"
        "incoming=json.loads(sys.stdin.buffer.read())\n"
        "request=incoming['request']\n"
        "probe={}\n"
        f"targets={[str(path) for path in targets]!r}\n"
        "for target in targets:\n"
        " path=Path(target)\n"
        " for operation in ('write','chmod','rename'):\n"
        "  try:\n"
        "   if operation=='write': path.write_text('tampered')\n"
        "   elif operation=='chmod': path.chmod(0o777)\n"
        "   else: path.rename(path.with_name(path.name+'-moved'))\n"
        "   probe[target+':'+operation]=True\n"
        "  except OSError:\n"
        "   probe[target+':'+operation]=False\n"
        f"host_pid={host_pid}\n"
        "try:\n"
        " os.kill(host_pid,signal.SIGWINCH)\n"
        " probe['host_signal']=True\n"
        "except OSError:\n"
        " probe['host_signal']=False\n"
        "probe['fds']=[]\n"
        "for fd in os.listdir('/proc/self/fd'):\n"
        " try: probe['fds'].append(os.readlink('/proc/self/fd/'+fd))\n"
        " except OSError: pass\n"
        "probe['ambient_secret']=os.environ.get('PEOS_PLANTED_SECRET')\n"
        "try:\n"
        " socket.create_connection(('1.1.1.1',53),timeout=0.1)\n"
        " probe['network']=True\n"
        "except OSError:\n"
        " probe['network']=False\n"
        "child='from pathlib import Path; Path('+repr(str(targets[0]))+')'\n"
        "child+='.write_text(\"child\")'\n"
        "descendant=subprocess.run([sys.executable,'-I','-c',child],capture_output=True)\n"
        "probe['descendant_write']=descendant.returncode==0\n"
        "product=\"def health():\\n    return {'status': 'ok'}\\n\"\n"
        "print(json.dumps({'request_digest':request['request_digest'],"
        "'files':{'product.py':product},'probe':probe},sort_keys=True))\n"
    )
    compile(adapter, "adapter.py", "exec")
    (bundle / "adapter.py").write_text(adapter)

    exit_code = main(
        [
            "barebones",
            "run",
            str(contract),
            "--workspace",
            str(workspace),
            "--run-id",
            "offline-provider-attack",
            "--repository-root",
            str(evidence),
            "--approval-receipt",
            str(receipt),
            "--expected-approver",
            "fixture-human",
            "--provider-offline-bundle",
            str(bundle),
            "--provider-offline-entry",
            "adapter.py",
            "--provider-timeout",
            "20",
        ]
    )
    assert exit_code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    assert output["release_eligible"] is False
    assert output["annotation"]["candidate_response_verified"] is True
    assert not any(
        event["event_type"] == "release_ready"
        for event in EvidenceLedger.open_existing(evidence, "offline-provider-attack").verify()
    )
    events = tuple(EvidenceLedger.open_existing(evidence, "offline-provider-attack").verify())
    coder = next(event for event in events if event["event_type"] == "coder_completed")
    response_digest = coder["payload"]["response_blob_digest"]
    response = json.loads(
        (evidence / ".pmpe/blobs" / response_digest.removeprefix("sha256:")).read_text()
    )
    probe = response["probe"]
    assert all(
        probe[f"{target}:{operation}"] is False
        for target in map(str, targets)
        for operation in ("write", "chmod", "rename")
    )
    assert probe["ambient_secret"] is None
    assert probe["network"] is False
    assert probe["host_signal"] is False
    assert probe["descendant_write"] is False
    assert not any(".pmpe" in fd or "e1-approval" in fd for fd in probe["fds"])
    assert all(path.read_bytes() == original for path, original in originals.items())


def test_provider_modes_cannot_be_combined(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = ROOT / "examples/barebones/e1-contract.json"
    receipt = ROOT / "examples/barebones/e1-approval-receipt.json"
    assert (
        main(
            [
                "barebones",
                "run",
                str(contract),
                "--workspace",
                str(tmp_path / "candidate"),
                "--run-id",
                "ambiguous-provider",
                "--repository-root",
                str(tmp_path),
                "--approval-receipt",
                str(receipt),
                "--expected-approver",
                "fixture-human",
                "--provider-command",
                "python legacy.py",
                "--provider-offline-bundle",
                str(tmp_path / "bundle"),
                "--provider-offline-entry",
                "adapter.py",
            ]
        )
        == 3
    )
    output = json.loads(capsys.readouterr().out)
    assert output["cause"] == "CONTRACT_INVALID"
    assert not (tmp_path / "candidate").exists()
