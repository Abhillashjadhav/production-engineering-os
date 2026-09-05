import json

import pytest
from test_monitoring_production import _run

from pm_evals_monitoring.binding import EnvelopeBinder
from pm_evals_monitoring.models import canonical_run_digest
from pm_evals_monitoring.outbox import (
    PermanentDeliveryError,
    canonical_outbox_identity,
    enqueue,
    flush_resilient,
)
from pm_evals_monitoring.worker import collect_linkedin


def test_selected_linkedin_folder_rejects_outside_and_missing_dashboard(tmp_path):
    repo = tmp_path / "native"
    private = repo / "data/private"
    private.mkdir(parents=True)
    context = tmp_path / "context.json"
    context.write_text("{}")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "eval-dashboard.html").write_text("completed")
    with pytest.raises(ValueError, match="beneath"):
        collect_linkedin(
            repo, context, tmp_path / "settings", tmp_path / "queue", run_folder=outside
        )
    alias = private / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="beneath"):
        collect_linkedin(
            repo, context, tmp_path / "settings", tmp_path / "queue", run_folder=alias
        )
    with pytest.raises(ValueError, match="completed dashboard"):
        collect_linkedin(
            repo, context, tmp_path / "settings", tmp_path / "queue", run_folder=private
        )
    assert not (tmp_path / "queue").exists()


def test_invalid_item_does_not_block_valid_delivery(tmp_path):
    root = tmp_path / "queue"
    bad = enqueue(root, route="/api/monitoring/runs", identity="bad", payload={"run_id": "bad"})
    good = enqueue(root, route="/api/monitoring/runs", identity="good", payload={"run_id": "good"})
    seen = []

    def sender(route, payload):
        if payload["run_id"] == "bad":
            raise PermanentDeliveryError("HTTP 422")
        seen.append(payload["run_id"])

    result = flush_resilient(root, sender=sender)
    assert result["sent"] == 1 and result["quarantined"] == 1
    assert seen == ["good"]
    assert not good.exists()
    assert bad.with_name(bad.name.replace(".pending.json", ".quarantined.json")).exists()


def test_transient_failures_are_retained_and_duplicates_are_idempotent(tmp_path):
    root = tmp_path / "queue"
    identity = canonical_outbox_identity("run", "p", "local", "r")
    target = enqueue(
        root, route="/api/monitoring/runs", identity=identity, payload={"run_id": "r"}
    )

    def unavailable(route, payload):
        raise RuntimeError("offline")

    assert flush_resilient(root, sender=unavailable)["pending"] == 1
    assert target.exists()
    assert flush_resilient(root, sender=lambda *args: None)["sent"] == 1
    enqueue(root, route="/api/monitoring/runs", identity=identity, payload={"run_id": "r"})
    assert flush_resilient(root, sender=lambda *args: None)["sent"] == 0


def test_quarantine_remains_visible_and_is_not_retried_by_collection(tmp_path):
    root = tmp_path / "queue"
    payload = {"run_id": "rejected"}
    pending = enqueue(root, route="/api/monitoring/runs", identity="same", payload=payload)

    def rejected(route, payload):
        raise PermanentDeliveryError("HTTP 422")

    assert flush_resilient(root, sender=rejected) == {"sent": 0, "pending": 0, "quarantined": 1}
    quarantined = enqueue(root, route="/api/monitoring/runs", identity="same", payload=payload)
    assert quarantined.name.endswith(".quarantined.json")
    assert not pending.exists()
    attempted = []
    assert flush_resilient(root, sender=lambda *args: attempted.append(args)) == {
        "sent": 0,
        "pending": 0,
        "quarantined": 1,
    }
    assert attempted == []
    with pytest.raises(ValueError, match="different evidence"):
        enqueue(root, route="/api/monitoring/runs", identity="same", payload={"run_id": "changed"})


def test_explicit_baseline_cycle_is_rejected_without_partial_cache(tmp_path):
    first = _run()
    first.run_id = "first"
    first.comparison.run_id = "second"
    second = first.model_copy(deep=True)
    second.run_id = "second"
    second.comparison.run_id = "first"
    runs = {run.run_id: run for run in (first, second)}
    binder = EnvelopeBinder(tmp_path / "queue", runs.get)
    with pytest.raises(ValueError, match="cycle"):
        binder.bind(first)
    assert binder.resolving == set()
    assert not list(binder.directory.glob("*.json"))


def test_recursive_baseline_digest_survives_restart_and_rejects_changed_input(tmp_path):
    first = _run()
    first.run_id = "first"
    first.comparison.run_id = "NO_BASELINE"
    first.comparison.sha256 = None
    second = first.model_copy(deep=True)
    second.run_id = "second"
    second.comparison.run_id = "first"
    third = first.model_copy(deep=True)
    third.run_id = "third"
    third.comparison.run_id = "second"
    runs = {run.run_id: run for run in (first, second, third)}
    root = tmp_path / "queue"
    binder = EnvelopeBinder(root, runs.get)
    bound_third = binder.bind(third)
    bound_second = binder.bind(second)
    assert bound_second.comparison.sha256 == canonical_run_digest(first)
    assert bound_third.comparison.sha256 == canonical_run_digest(bound_second)
    assert bound_third.comparison.sha256 != canonical_run_digest(second)
    restarted = EnvelopeBinder(root, runs.get)
    assert canonical_run_digest(restarted.bind(third)) == canonical_run_digest(bound_third)
    third.product.version = "changed-input"
    with pytest.raises(ValueError, match="inputs changed"):
        restarted.bind(third)


@pytest.mark.parametrize("declared_digest", [None, "sha256:" + "a" * 64])
def test_missing_selected_baseline_waits_without_freezing_candidate(tmp_path, declared_digest):
    baseline = _run()
    baseline.run_id = "baseline"
    baseline.comparison.run_id = "NO_BASELINE"
    baseline.comparison.sha256 = None
    candidate = baseline.model_copy(deep=True)
    candidate.run_id = "candidate"
    candidate.comparison.run_id = baseline.run_id
    candidate.comparison.sha256 = declared_digest
    source_digest = canonical_run_digest(candidate)
    runs = {}
    binder = EnvelopeBinder(tmp_path / "queue", runs.get)
    with pytest.raises(ValueError, match="retry after export"):
        binder.bind(candidate)
    assert binder.resolving == set()
    assert not list(binder.directory.glob("*.json"))
    assert not list((tmp_path / "queue").glob("*.pending.json"))
    runs[baseline.run_id] = baseline
    bound = EnvelopeBinder(tmp_path / "queue", runs.get).bind(candidate)
    assert bound.run_id == candidate.run_id
    assert bound.comparison.sha256 == (declared_digest or canonical_run_digest(baseline))
    assert canonical_run_digest(candidate) == source_digest


@pytest.mark.parametrize("unresolved", [False, True])
def test_legacy_baseline_cache_requires_verification_without_rewriting(tmp_path, unresolved):
    baseline = _run()
    baseline.run_id = "baseline"
    baseline.comparison.run_id = "NO_BASELINE"
    baseline.comparison.sha256 = None
    candidate = baseline.model_copy(deep=True)
    candidate.run_id = "candidate"
    candidate.comparison.run_id = baseline.run_id
    runs = {baseline.run_id: baseline}
    root = tmp_path / "queue"
    binder = EnvelopeBinder(root, runs.get)
    binder.bind(candidate)
    target = next(
        path
        for path in binder.directory.glob("*.json")
        if json.loads(path.read_bytes())["envelope"]["run_id"] == "candidate"
    )
    cached = json.loads(target.read_bytes())
    cached.pop("binding_version")
    if unresolved:
        cached["envelope"] = candidate.model_dump(mode="json")
        cached["envelope_sha256"] = canonical_run_digest(candidate)
    target.write_text(json.dumps(cached))
    previous = target.read_bytes()
    restarted = EnvelopeBinder(root, runs.get)
    if unresolved:
        with pytest.raises(ValueError, match="resolution is unverified"):
            restarted.bind(candidate)
    else:
        assert restarted.bind(candidate).comparison.sha256 == canonical_run_digest(baseline)
    assert target.read_bytes() == previous
