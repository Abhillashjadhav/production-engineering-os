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

    def test_nested_signal_exit_code_rejected(self):
        """A killed observer subprocess (137) inside an already-failing criterion."""

        def change(rows):
            # AC-002 already fails in the persistence case, so its status is unchanged.
            row = next(item for item in rows if item["criterion_id"] == "AC-002")
            value = json.loads(row["stdout"])
            value["observations"][-1]["exit_code"] = 137
            row["stdout"] = json.dumps(value)

        self.mutate("persistence", lambda root: self.change_rows(root, "processes.jsonl", change))

    def test_duplicate_or_altered_findings_rejected(self):
        def duplicate(root):
            path = root / "result.json"
            value = json.loads(path.read_text())
            value["findings"].append(dict(value["findings"][0]))
            path.write_text(json.dumps(value))

        def alter(root):
            path = root / "result.json"
            value = json.loads(path.read_text())
            value["findings"][0]["message"] = "edited after the run"
            value["findings"][0]["files"] = ["product.py"]
            path.write_text(json.dumps(value))

        for mutation in (duplicate, alter):
            with self.subTest(mutation=mutation.__name__):
                self.mutate("persistence", mutation)

    def test_replaced_runner_program_rejected(self):
        """A fabricated -c program that only prints the recorded stdout."""

        def change(rows):
            argv = rows[0]["argv"]
            workspace = argv[-5].split("sys.path.insert(0,", 1)[1].split(");", 1)[0]
            argv[-5] = (
                f"import sys;sys.path.insert(0,{workspace});print({rows[0]['stdout'].strip()!r})"
            )

        self.mutate("retained", lambda root: self.change_rows(root, "processes.jsonl", change))


if __name__ == "__main__":
    unittest.main()
