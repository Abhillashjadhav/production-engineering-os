"""Exact-candidate package inspection; clean installation needs protected adapters.

SYS-xx / issue #255: a sealed source candidate is distinct from a cleanly verified
package and from a delivered product. The current profiles do not declare complete
locked installation and customer-journey adapters, so this consumer fails closed.
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pmpe.barebones import (
    BubblewrapCandidateSandbox,
    CandidateSandbox,
    ContractInvalidError,
    default_template,
)
from pmpe.contracts.canonical import (
    CanonicalInputError,
    canonical_digest,
    canonical_json_bytes,
    strict_loads,
)
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger
from pmpe.product_package_io import (
    _MAX_FILE_BYTES,
    _MAX_PATH_DEPTH,
    _MAX_TOTAL_BYTES,
    _read_bundle_files,
)
from pmpe.product_package_io import (
    ProductPackageError as ProductPackageError,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_FILES = 500
_SENSITIVE_NAMES = frozenset({".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"})
_CREDENTIAL = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}"
)
_BASE_BLOCKERS = (
    "BUILD_TOOL_IDENTITY_UNVERIFIED",
    "SETUP_START_STOP_UNVERIFIED",
    "CLEAN_INSTALL_ADAPTER_UNAVAILABLE",
    "CUSTOMER_JOURNEY_ADAPTER_UNAVAILABLE",
)
_SYNTAX_RUNNER = (
    "import ast,pathlib,sys\n"
    "root=pathlib.Path('/workspace')\n"
    "files=sorted(root.rglob('*.py'))\n"
    "for path in files: ast.parse(path.read_bytes(),filename=str(path))\n"
)


@dataclass(frozen=True)
class ProductPackageResult:
    bundle: Path
    manifest_digest: str
    status: str
    blockers: tuple[str, ...]


def _safe_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    return (
        bool(relative)
        and "\\" not in relative
        and not path.is_absolute()
        and path.as_posix() == relative
        and all(part not in {"", ".", ".."} for part in path.parts)
        and len(path.parts) <= _MAX_PATH_DEPTH
        and not any(part in _SENSITIVE_NAMES or part.startswith(".git") for part in path.parts)
    )


def _admitted_source(
    repository_root: Path, run_id: str, expected_head_digest: str
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if _DIGEST.fullmatch(expected_head_digest) is None:
        raise ProductPackageError("expected head digest is malformed")
    try:
        ledger = EvidenceLedger.open_existing(
            repository_root,
            run_id,
            max_read_bytes=_MAX_TOTAL_BYTES,
            max_total_read_bytes=4 * _MAX_TOTAL_BYTES,
        )
        events = tuple(ledger.verify())
        terminal = events[-1]
        if terminal["event_digest"] != expected_head_digest:
            raise ProductPackageError("sealed ledger head changed")
        if terminal["state"] != "RELEASE_READY" or terminal["event_type"] != "release_ready":
            raise ProductPackageError("run has no sealed RELEASE_READY candidate")
        candidate_digest = terminal["payload"].get("candidate_digest")
        if (
            not isinstance(candidate_digest, str)
            or candidate_digest not in terminal["blob_digests"]
        ):
            raise ProductPackageError("release event does not bind a candidate")
        manifest = strict_loads(ledger.read_blob(candidate_digest), "application/json")
        if not isinstance(manifest, dict) or not manifest or len(manifest) > _MAX_FILES:
            raise ProductPackageError("candidate manifest is empty or unbounded")
        files: dict[str, bytes] = {}
        total = 0
        for relative, digest in sorted(manifest.items()):
            if not isinstance(relative, str) or not _safe_path(relative):
                raise ProductPackageError("candidate path is unsafe")
            if not isinstance(digest, str) or digest not in terminal["blob_digests"]:
                raise ProductPackageError("candidate file is not bound to release event")
            content = ledger.read_blob(digest)
            # SEC_PACKAGE_CREDENTIAL: do not publish known credential material
            # merely because it was included in a content-addressed candidate.
            if _CREDENTIAL.search(content):
                raise ProductPackageError("candidate source contains credential material")
            total += len(content)
            if len(content) > _MAX_FILE_BYTES or total > _MAX_TOTAL_BYTES:
                raise ProductPackageError("candidate source exceeds package size limit")
            files[relative] = content
        validation = [event for event in events if event["event_type"] == "contract_validated"]
        bound_profile = (
            validation[0]["payload"].get("product_profile") if len(validation) == 1 else None
        )
        profile: dict[str, Any] | None = None
        if isinstance(bound_profile, dict):
            profile_id = bound_profile.get("profile_id")
            digest = bound_profile.get("manifest_digest")
            if (
                isinstance(profile_id, str)
                and isinstance(digest, str)
                and digest in validation[0]["blob_digests"]
            ):
                profile_blob = ledger.read_blob(digest)
                decoded = strict_loads(profile_blob, "application/json")
                if isinstance(decoded, dict) and decoded.get("profile_id") == profile_id:
                    profile = {
                        "profile_id": profile_id,
                        "manifest_digest": digest,
                        "recompiled": False,
                    }
                    if profile_id == "barebones-health-v1":
                        contract_digest = validation[0]["payload"].get("contract_digest")
                        if (
                            isinstance(contract_digest, str)
                            and contract_digest in validation[0]["blob_digests"]
                        ):
                            contract = strict_loads(
                                ledger.read_blob(contract_digest), "application/json"
                            )
                            if (
                                isinstance(contract, dict)
                                and canonical_digest(contract) == terminal["subject_digest"]
                            ):
                                try:
                                    profile_module = importlib.import_module("pmpe.product_profile")
                                except ModuleNotFoundError as exc:
                                    if exc.name != "pmpe.product_profile":
                                        raise
                                    # The protected profile lands in the integration packet.
                                    pass
                                else:
                                    try:
                                        compiled = profile_module.compile_product_profile(
                                            profile_id,
                                            contract=contract,
                                            template=default_template(),
                                            harness_plan=None,
                                        )
                                    except ValueError:
                                        pass
                                    else:
                                        if (
                                            compiled.manifest_digest == digest
                                            and compiled.manifest == decoded
                                            and validation[0]["payload"].get("template_digest")
                                            == compiled.template_digest
                                        ):
                                            profile["recompiled"] = True
        source = {
            "repository_run_id": run_id,
            "head_event_digest": expected_head_digest,
            "candidate_digest": candidate_digest,
            "files": manifest,
            "profile": profile,
        }
        return source, files
    except (EvidenceIntegrityError, CanonicalInputError, IndexError, KeyError, OSError) as exc:
        raise ProductPackageError("sealed ledger candidate cannot be verified") from exc


def _clean_syntax(files: dict[str, bytes], sandbox: CandidateSandbox) -> dict[str, str]:
    """Run one fixed static adapter on an otherwise empty source directory."""

    identity = canonical_digest(
        {
            "runner": _SYNTAX_RUNNER,
            "python": sys.version,
            "sandbox_adapter": f"{type(sandbox).__module__}.{type(sandbox).__qualname__}",
        }
    )

    def result(status: str, reason: str) -> dict[str, str]:
        return {
            "id": "python-syntax",
            "status": status,
            "reason": reason,
            "tool_identity_digest": identity,
        }

    with tempfile.TemporaryDirectory(prefix="peos-clean-package-") as temporary:
        workspace = Path(temporary)
        for relative, content in files.items():
            destination = workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        try:
            outcome = sandbox.run(
                workspace,
                (sys.executable, "-I", "-B", "-c", _SYNTAX_RUNNER),
                timeout_seconds=20,
                environment={
                    "HOME": "/tmp/home",
                    "LC_ALL": "C",
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONNOUSERSITE": "1",
                    "TMPDIR": "/tmp",
                },
            )
        except (ContractInvalidError, OSError):
            return result("BLOCKED", "CLEAN_SANDBOX_UNAVAILABLE")
        if outcome.returncode != 0:
            return result("FAIL", "PYTHON_SYNTAX_FAILED")
        if type(sandbox) is not BubblewrapCandidateSandbox:
            return result("BLOCKED", "TEST_ADAPTER_NOT_TRUSTED")
        return result("PASS", "CLEAN_SANDBOX_AST_PARSE")


def _blockers(source: dict[str, Any], syntax: dict[str, str]) -> tuple[str, ...]:
    blockers = list(_BASE_BLOCKERS)
    if syntax["status"] != "PASS":
        blockers.insert(0, syntax["reason"])
    if source["profile"] is None:
        blockers.insert(0, "PROFILE_NOT_BOUND")
    elif source["profile"].get("recompiled") is not True:
        # A ledger digest alone cannot authorize an arbitrary profile. The fixed
        # task-tracker harness mapping is not yet retained for clean recompile.
        blockers.insert(0, "PROFILE_RECOMPILE_UNAVAILABLE")
    if source["profile"] is None or source["profile"].get("recompiled") is not True:
        blockers.insert(0, "DEPENDENCY_AND_CONFIG_DECLARATIONS_UNVERIFIED")
    return tuple(blockers)


def _manifest(source: dict[str, Any], syntax: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "peos-product-package/v1",
        "source": source,
        "required_clean_checks": [
            syntax,
            {
                "id": "clean-install",
                "status": "BLOCKED",
                "reason": "CLEAN_INSTALL_ADAPTER_UNAVAILABLE",
            },
            {
                "id": "customer-journeys",
                "status": "BLOCKED",
                "reason": "CUSTOMER_JOURNEY_ADAPTER_UNAVAILABLE",
            },
        ],
        "blockers": list(_blockers(source, syntax)),
        "claims": {"package_verified": False, "customer_delivery_verified": False},
    }


def assemble_product_package(
    repository_root: Path,
    run_id: str,
    expected_head_digest: str,
    output: Path,
    *,
    sandbox: CandidateSandbox | None = None,
) -> ProductPackageResult:
    """Assemble ledger-bound bytes in a new bundle; never infer clean verification."""

    source, files = _admitted_source(repository_root, run_id, expected_head_digest)
    syntax = _clean_syntax(files, sandbox or BubblewrapCandidateSandbox())
    if output.exists() or output.is_symlink():
        raise ProductPackageError("package output must not exist")
    if output.resolve().is_relative_to((repository_root / ".pmpe").resolve()):
        raise ProductPackageError("package output overlaps evidence storage")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".product-package-", dir=output.parent))
    try:
        for relative, content in files.items():
            destination = staged / "source" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        manifest = _manifest(source, syntax)
        (staged / "product-package.json").write_bytes(canonical_json_bytes(manifest) + b"\n")
        os.rename(staged, output)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return ProductPackageResult(
        output, canonical_digest(manifest), "BLOCKED", _blockers(source, syntax)
    )


def verify_product_package(
    bundle: Path,
    repository_root: Path,
    run_id: str,
    expected_head_digest: str,
    expected_manifest_digest: str,
    *,
    sandbox: CandidateSandbox | None = None,
) -> ProductPackageResult:
    """Recheck each source byte against the ledger, never trusting bundle verdicts."""

    source, files = _admitted_source(repository_root, run_id, expected_head_digest)
    syntax = _clean_syntax(files, sandbox or BubblewrapCandidateSandbox())
    expected = _manifest(source, syntax)
    files_on_disk = _read_bundle_files(bundle)
    try:
        raw = files_on_disk["product-package.json"]
        observed = strict_loads(raw, "application/json")
    except (KeyError, CanonicalInputError) as exc:
        raise ProductPackageError("package manifest cannot be verified") from exc
    digest = canonical_digest(expected)
    if observed != expected or digest != expected_manifest_digest:
        raise ProductPackageError("package manifest does not match sealed candidate")
    expected_paths = {"product-package.json", *("source/" + name for name in files)}
    if set(files_on_disk) != expected_paths:
        raise ProductPackageError("package source file set differs from sealed candidate")
    for relative, content in files.items():
        if files_on_disk["source/" + relative] != content:
            raise ProductPackageError("package source differs from sealed candidate")
    return ProductPackageResult(bundle, digest, "BLOCKED", _blockers(source, syntax))
