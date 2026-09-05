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
    first.comparison.run_id = "no-baseline"
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
