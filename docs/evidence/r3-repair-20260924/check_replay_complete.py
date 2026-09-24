"""Check full retained replay coverage, not merely zero mismatches in a prefix."""

import json
import sys
from pathlib import Path


def check(directory):
    root = Path(directory)
    result = json.loads((root / "result.json").read_text())
    ids = sorted(result["criteria"])
    assert ids == [f"AC-{i:03d}" for i in range(1, 15)], "criterion coverage"
    observations = [json.loads(row) for row in (root / "digest-checks.jsonl").read_text().splitlines()]
    expected = [("before", "command")]
    expected += [(stage, cid) for cid in ids for stage in ("before", "after")]
    expected += [("after", "command")]
    assert [(o["stage"], o["subject"]) for o in observations] == expected, "boundary sequence incomplete"
    assert all(not o["mismatches"] and o["checked"] > 0 for o in observations), "integrity failed"
    assert all(o["expected_inventory_digest"] == o["observed_inventory_digest"] for o in observations), "inventory mismatch"
    processes = [json.loads(row) for row in (root / "processes.jsonl").read_text().splitlines()]
    assert [p["criterion_id"] for p in processes] == ids, "process coverage incomplete"
    assert all(p["argv"] and "exit_code" in p and "stdout" in p and "stderr" in p for p in processes), "process fields missing"
    return {"digest_observations": len(observations), "process_records": len(processes), "digest_mismatches": 0}


if __name__ == "__main__":
    print(json.dumps(check(sys.argv[1]), sort_keys=True))
