import json

import pytest

from pm_evals_monitoring.outbox import canonical_outbox_identity, enqueue, flush_resilient, PermanentDeliveryError


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
    target = enqueue(root, route="/api/monitoring/runs", identity=identity, payload={"run_id": "r"})
    def unavailable(route, payload):
        raise RuntimeError("offline")
    assert flush_resilient(root, sender=unavailable)["pending"] == 1
    assert target.exists()
    assert flush_resilient(root, sender=lambda *args: None)["sent"] == 1
    enqueue(root, route="/api/monitoring/runs", identity=identity, payload={"run_id": "r"})
    assert flush_resilient(root, sender=lambda *args: None)["sent"] == 0
