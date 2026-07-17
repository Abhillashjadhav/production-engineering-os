"""TRAJ-FS: full-stack trajectory rules over the run ledger. Twelve planted
failure classes must each be caught by exactly their intended rule, and the
good full-stack run must be clean — a planted failure nobody catches is a
broken gate, not a passing suite."""

from __future__ import annotations

import json
from pathlib import Path

from pmpe.evals.trajectory_fullstack import evaluate_fullstack_trajectory

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "trajectory-fullstack"

PLANTED = {
    "planted_frontend_before_journey.jsonl": "TRAJ-FS-01",
    "planted_missing_journey_validation.jsonl": "TRAJ-FS-01",
    "planted_journey_digest_mismatch.jsonl": "TRAJ-FS-02",
    "planted_missing_browser_verification.jsonl": "TRAJ-FS-03",
    "planted_mocked_browser_verification.jsonl": "TRAJ-FS-03",
    "planted_preview_digest_mismatch.jsonl": "TRAJ-FS-04",
    "planted_cloud_preview_claim.jsonl": "TRAJ-FS-04",
    "planted_missing_lens_review.jsonl": "TRAJ-FS-05",
    "planted_nonroster_lens_review.jsonl": "TRAJ-FS-05",
    "planted_v3_reviewer_wrote.jsonl": "TRAJ-FS-06",
    "planted_missing_a11y_suite.jsonl": "TRAJ-FS-07",
    "planted_api_contract_drift.jsonl": "TRAJ-FS-08",
}


def _load(name: str) -> list[dict[str, object]]:
    path = FIXTURES / name
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _checks(name: str) -> set[str]:
    return {v.check_id for v in evaluate_fullstack_trajectory(_load(name))}


def test_the_good_fullstack_run_is_clean() -> None:
    assert evaluate_fullstack_trajectory(_load("good_fullstack_run.jsonl")) == []


def test_every_planted_fixture_exists_and_is_caught_by_its_intended_rule() -> None:
    for name, rule in PLANTED.items():
        assert (FIXTURES / name).exists(), f"missing fixture {name}"
        caught = _checks(name)
        assert rule in caught, f"{name}: expected {rule}, caught {caught or 'nothing'}"


def test_there_are_exactly_twelve_planted_fixtures() -> None:
    planted_on_disk = {p.name for p in FIXTURES.glob("planted_*.jsonl")}
    assert planted_on_disk == set(PLANTED), (
        "planted fixtures on disk must match the tested set exactly — an "
        "untested planted fixture is a silent hole"
    )
    assert len(PLANTED) == 12


def test_every_rule_id_is_exercised_by_at_least_one_fixture() -> None:
    assert set(PLANTED.values()) == {
        "TRAJ-FS-01",
        "TRAJ-FS-02",
        "TRAJ-FS-03",
        "TRAJ-FS-04",
        "TRAJ-FS-05",
        "TRAJ-FS-06",
        "TRAJ-FS-07",
        "TRAJ-FS-08",
    }


def test_a_run_with_no_fullstack_stages_is_not_judged() -> None:
    """A V2-only ledger (no journey/browser/preview stages and no frontend
    surface) is out of TRAJ-FS scope — the V2 rules own it."""
    events = _load("good_fullstack_run.jsonl")
    v2_only = [
        e
        for e in events
        if e.get("stage")
        not in {"journey_validation", "browser_verification", "preview", "api_contract"}
        and "surface=frontend" not in str(e.get("detail", ""))
        and not str(e.get("agent", "")).startswith("v3-")
    ]
    assert evaluate_fullstack_trajectory(v2_only) == []


def test_a_digestless_lock_cannot_disable_the_journey_binding() -> None:
    """Reviewer finding: a contract_lock with empty output_digests silently
    skipped FS-02, and no V2 rule owns that case — it must fail closed."""
    events = _load("good_fullstack_run.jsonl")
    for event in events:
        if event.get("stage") == "contract_lock":
            event["output_digests"] = {}
    checks = {v.check_id for v in evaluate_fullstack_trajectory(events)}
    assert "TRAJ-FS-02" in checks


def test_mocked_flag_variants_are_caught() -> None:
    events = _load("good_fullstack_run.jsonl")
    for event in events:
        if event.get("stage") == "browser_verification":
            event["detail"] = str(event["detail"]).replace("mocked=false", "mocked=true")
    checks = {v.check_id for v in evaluate_fullstack_trajectory(events)}
    assert "TRAJ-FS-03" in checks
