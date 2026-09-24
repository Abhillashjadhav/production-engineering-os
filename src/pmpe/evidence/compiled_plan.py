"""Reconstruct retained acceptance semantics without executing candidate code."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from pmpe.contracts.acceptance import (
    AcceptanceCompileError,
    AcceptanceDiagnostic,
    _id_keyed_collection,
    compile_acceptance_plan,
)
from pmpe.contracts.canonical import canonical_digest
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _relative(value: Any) -> str:
    if not isinstance(value, str):
        raise EvidenceIntegrityError("retained test path is malformed")
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or PureWindowsPath(value).drive
        or path.as_posix() != value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise EvidenceIntegrityError("retained test path is unsafe")
    return value


def validate_compiled_plan(
    ledger: EvidenceLedger,
    contract: Mapping[str, Any],
    plan: Mapping[str, Any],
    candidate_manifest: Mapping[str, Any],
    candidate_blobs: list[str],
) -> None:
    """Use the existing compiler as the sole criterion normalizer.

    Contract action/measure names are normalization inputs, not authentication of
    a runtime registry. Human-test bytes come only from the sealed candidate;
    template proofs must name a retained trusted test digest. No module is run.
    """

    diagnostics: list[AcceptanceDiagnostic] = []
    criteria = _id_keyed_collection(
        contract.get("acceptance_criteria"), collection="criterion", diagnostics=diagnostics
    )
    if (
        diagnostics
        or not criteria
        or any(not isinstance(item, Mapping) for item in criteria.values())
    ):
        raise EvidenceIntegrityError("retained contract criteria are malformed")
    trusted: dict[str, str] = {}
    raw_trusted = plan.get("trusted_test_digests")
    if not isinstance(raw_trusted, list):
        raise EvidenceIntegrityError("retained trusted tests are malformed")
    for pair in raw_trusted:
        if not isinstance(pair, list) or len(pair) != 2:
            raise EvidenceIntegrityError("retained trusted test binding is malformed")
        path = _relative(pair[0])
        digest = pair[1]
        if path in trusted or not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise EvidenceIntegrityError("retained trusted test identity is malformed")
        trusted[path] = digest
    for path, digest in candidate_manifest.items():
        _relative(path)
        if (
            not isinstance(digest, str)
            or not _DIGEST.fullmatch(digest)
            or digest not in candidate_blobs
        ):
            raise EvidenceIntegrityError("retained candidate file is not bound")
    if any(candidate_manifest.get(path) != digest for path, digest in trusted.items()):
        raise EvidenceIntegrityError("retained trusted tests differ from the candidate")
    actions: set[str] = set()
    measures: set[str] = set()
    paths = set(trusted)
    for item in criteria.values():
        when = item.get("when")
        if isinstance(when, Mapping) and isinstance(when.get("action"), str):
            actions.add(when["action"])
        if isinstance(item.get("measure"), str):
            measures.add(item["measure"])
        human = item.get("human_test")
        if isinstance(human, Mapping):
            paths.add(_relative(human.get("path")))
    proofs: dict[str, str] = {}
    versions: set[str] = set()
    for criterion in plan["criteria"]:
        proof = criterion.get("template_proof")
        if proof is None:
            continue
        if not isinstance(proof, Mapping) or any(
            not isinstance(proof.get(key), str)
            for key in ("test_id", "file_digest", "template_version")
        ):
            raise EvidenceIntegrityError("retained template proof is malformed")
        if proof["file_digest"] not in trusted.values():
            raise EvidenceIntegrityError("retained template proof is not bound to trusted bytes")
        if proof["test_id"] in proofs and proofs[proof["test_id"]] != proof["file_digest"]:
            raise EvidenceIntegrityError("retained template proof identity conflicts")
        proofs[proof["test_id"]] = proof["file_digest"]
        versions.add(proof["template_version"])
    if len(versions) > 1:
        raise EvidenceIntegrityError("retained template versions conflict")
    try:
        with tempfile.TemporaryDirectory(prefix="pmpe-retained-tests-") as temporary:
            root = Path(temporary)
            for path in sorted(paths):
                digest = candidate_manifest.get(path)
                if not isinstance(digest, str):
                    raise EvidenceIntegrityError("retained human test is absent from candidate")
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(ledger.read_blob(digest))
            expected = compile_acceptance_plan(
                contract,
                repository_root=root,
                registered_actions=frozenset(actions),
                registered_measures=frozenset(measures),
                template_version=next(iter(versions), ""),
                template_test_digests=proofs,
                trusted_test_digests=trusted,
            ).as_dict()
    except (AcceptanceCompileError, OSError) as exc:
        raise EvidenceIntegrityError(
            "retained contract cannot reconstruct its compiled plan"
        ) from exc
    if canonical_digest(expected) != canonical_digest(plan):
        raise EvidenceIntegrityError("retained compiled plan semantics differ from the contract")
