"""Mutate retained evidence, never execute or edit the frozen candidate/runner."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHECKER = REPO / "docs/evidence/r3-repair-20260924/check_replay_complete.py"
EVIDENCE = REPO / "docs/evidence/integration-review-20260924"
PACKET = Path(os.environ["R4_REPLAY_PACKET"])
SOURCE = Path(os.environ.get("R4_REPLAY_SOURCE", str(REPO)))


class ReplayCheckerRegression(unittest.TestCase):
    def run_check(self, root, optimized=False):
        return subprocess.run(
            [
                sys.executable,
                "-O" if optimized else "-B",
                str(CHECKER),
                str(root),
                "--packet",
                str(PACKET),
                "--peos-source",
                str(SOURCE),
                "--case",
                root.name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_original_cases_pass(self):
        for name in ("retained", "persistence", "filtering"):
            with self.subTest(case=name):
                result = self.run_check(EVIDENCE / name)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def mutate(self, name, mutation, optimized=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / name
            shutil.copytree(EVIDENCE / name, root)
            mutation(root)
            result = self.run_check(root, optimized)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def change_rows(self, root, filename, change):
        path = root / filename
        rows = [json.loads(row) for row in path.read_text().splitlines()]
        change(rows)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_optimized_interpreter_rejects_missing_boundary(self):
        self.mutate(
            "retained",
            lambda root: self.change_rows(root, "digest-checks.jsonl", lambda rows: rows.pop()),
            True,
        )

    def test_process_crash_rejected(self):
        self.mutate(
            "retained",
            lambda root: self.change_rows(
                root, "processes.jsonl", lambda rows: rows[0].update(exit_code=137)
            ),
        )

    def test_fake_matching_inventories_rejected(self):
        def fake(rows):
            for row in rows:
                row.update(
                    expected_inventory_digest="sha256:" + "0" * 64,
                    observed_inventory_digest="sha256:" + "0" * 64,
                )

        self.mutate("retained", lambda root: self.change_rows(root, "digest-checks.jsonl", fake))

    def test_swapped_stdout_rejected(self):
        def swap(rows):
            rows[0]["stdout"], rows[1]["stdout"] = rows[1]["stdout"], rows[0]["stdout"]

        self.mutate("retained", lambda root: self.change_rows(root, "processes.jsonl", swap))

    def test_forged_summary_rejected(self):
        def change(root):
            path = root / "result.json"
            value = json.loads(path.read_text())
            value["criteria"]["AC-001"] = "FAIL"
            path.write_text(json.dumps(value))

        self.mutate("retained", change)

    def test_observer_markers_rejected(self):
        def change(rows):
            value = json.loads(rows[0]["stdout"])
            value["observations"][0]["output"]["invalid_json"] = True
            rows[0]["stdout"] = json.dumps(value)

        self.mutate("retained", lambda root: self.change_rows(root, "processes.jsonl", change))


if __name__ == "__main__":
    unittest.main()
