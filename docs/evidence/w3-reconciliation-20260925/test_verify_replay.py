"""Regression tests for verify-replay.py over the retained W3 replay archive.

Usage (from a PEOS checkout):
    python -B docs/evidence/w3-reconciliation-20260925/test_verify_replay.py -v
"""

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
VERIFIER = HERE / "verify-replay.py"
ARCHIVE = HERE / "retained-replay.tar.gz"


class VerifyReplayRegression(unittest.TestCase):
    def run_verifier(self, change=None):
        with tempfile.TemporaryDirectory() as temporary:
            with tarfile.open(ARCHIVE) as archive:
                archive.extractall(temporary, filter="data")
            (replay,) = Path(temporary).iterdir()
            if change is not None:
                change(replay)
            environment = dict(os.environ, PYTHONPATH=str(REPO / "src"))
            return subprocess.run(
                [sys.executable, "-B", str(VERIFIER), str(replay)],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )

    def refused(self, change, message):
        result = self.run_verifier(change)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(message, result.stdout)

    @staticmethod
    def change_json(path, change):
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def test_retained_replay_verifies(self):
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK:", result.stdout)

    def test_approval_claims_in_the_summary_rejected(self):
        """The no-approval verdict rests on status and approval; both must match (Codex #231)."""

        def approve(value):
            value["status"] = "RELEASE_READY"

        def approval(value):
            value["approval"] = {"status": "APPROVED"}

        for name, change in {"status": approve, "approval": approval}.items():
            with self.subTest(field=name):
                self.refused(
                    lambda replay, change=change: self.change_json(
                        replay / "replay-summary.json", change
                    ),
                    "replay-summary.json differs from the recorded summary",
                )

    def test_substituted_source_manifest_rejected(self):
        """The exported manifest must be the one the ledger and migration record bind."""

        def empty(replay):
            (replay / "source-manifest.json").write_text("{}")

        def appended(replay):
            path = replay / "source-manifest.json"
            path.write_bytes(path.read_bytes() + b"\n")

        for name, change in {"empty": empty, "one-byte": appended}.items():
            with self.subTest(change=name):
                self.refused(change, "source-manifest.json")


if __name__ == "__main__":
    unittest.main()
