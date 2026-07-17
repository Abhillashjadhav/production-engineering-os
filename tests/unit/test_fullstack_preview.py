"""PD-V3-06/14: a preview claim is only believable when the served artifacts
are bound to the exact reviewed source tree — record/verify must fail closed
on missing records, digest mismatches, cloud claims, and failed journeys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmpe.fullstack.preview import (
    ALLOWED_PREVIEW_KINDS,
    PreviewViolation,
    record_preview,
    verify_preview,
)

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


def _record(path: Path, **overrides):  # noqa: ANN003, ANN202
    payload = {
        "source_digest": DIGEST,
        "deployment_kind": "local_preview",
        "artifacts": {"frontend-build-id": "abc123", "backend-source": DIGEST},
        "journeys": {"a11y": "passed", "keyboard": "passed", "journeys": "passed"},
        "recorded_at": "2026-07-17T00:00:00Z",
    }
    payload.update(overrides)
    return record_preview(path, **payload)


def test_record_and_verify_roundtrip(tmp_path: Path) -> None:
    evidence = _record(tmp_path / "preview-evidence.json")
    assert evidence.source_digest == DIGEST
    assert verify_preview(tmp_path / "preview-evidence.json", expected_source_digest=DIGEST) == []


def test_missing_record_fails_closed(tmp_path: Path) -> None:
    problems = verify_preview(tmp_path / "absent.json", expected_source_digest=DIGEST)
    assert problems and "no preview evidence" in problems[0]


def test_corrupt_record_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "preview-evidence.json"
    path.write_text("{broken")
    problems = verify_preview(path, expected_source_digest=DIGEST)
    assert problems and "unreadable" in problems[0]


def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "preview-evidence.json"
    _record(path)
    problems = verify_preview(path, expected_source_digest=OTHER)
    assert problems and "does not match" in problems[0]


def test_cloud_claims_are_refused_at_record_time(tmp_path: Path) -> None:
    with pytest.raises(PreviewViolation, match="cloud"):
        _record(tmp_path / "preview-evidence.json", deployment_kind="cloud")


def test_unknown_kind_in_a_hand_written_record_fails_verify(tmp_path: Path) -> None:
    path = tmp_path / "preview-evidence.json"
    _record(path)
    data = json.loads(path.read_text())
    data["deployment_kind"] = "cloud"
    path.write_text(json.dumps(data))
    problems = verify_preview(path, expected_source_digest=DIGEST)
    assert problems and any("cloud" in p for p in problems)


def test_empty_artifacts_are_refused_at_record_time(tmp_path: Path) -> None:
    with pytest.raises(PreviewViolation, match="artifact"):
        _record(tmp_path / "preview-evidence.json", artifacts={})


def test_blank_artifact_fingerprint_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PreviewViolation, match="fingerprint"):
        _record(tmp_path / "preview-evidence.json", artifacts={"frontend": ""})


def test_recording_a_failed_journey_is_honest_but_verify_refuses_it(tmp_path: Path) -> None:
    path = tmp_path / "preview-evidence.json"
    _record(path, journeys={"a11y": "passed", "keyboard": "failed"})
    problems = verify_preview(path, expected_source_digest=DIGEST)
    assert problems and any("keyboard" in p for p in problems)


def test_journey_results_outside_the_vocabulary_are_refused(tmp_path: Path) -> None:
    with pytest.raises(PreviewViolation, match="passed"):
        _record(tmp_path / "preview-evidence.json", journeys={"a11y": "mostly-ok"})


def test_empty_journeys_are_refused_at_record_time(tmp_path: Path) -> None:
    with pytest.raises(PreviewViolation, match="journey"):
        _record(tmp_path / "preview-evidence.json", journeys={})


def test_blank_source_digest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PreviewViolation, match="digest"):
        _record(tmp_path / "preview-evidence.json", source_digest="")


def test_nothing_is_written_on_refusal(tmp_path: Path) -> None:
    path = tmp_path / "preview-evidence.json"
    with pytest.raises(PreviewViolation):
        _record(path, deployment_kind="cloud")
    assert not path.exists()


def test_allowed_kinds_are_exactly_the_two_preview_kinds() -> None:
    assert set(ALLOWED_PREVIEW_KINDS) == {"local_preview", "containerized_preview"}
