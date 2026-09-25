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

    def test_summary_digests_must_match_the_ledger_evidence(self):
        """Source-bound digests may differ between runs, never from their own ledger (Codex)."""
        for field in ("contract_digest", "plan_digest"):
            with self.subTest(field=field):
                self.refused(
                    lambda replay, field=field: self.change_json(
                        replay / "replay-summary.json",
                        lambda value: value.update({field: "sha256:" + "0" * 64}),
                    ),
                    "replay-summary.json",
                )

    def test_recorded_verdicts_name_a_file_in_the_retained_archive(self):
        recorded = json.loads((HERE / "verdicts.json").read_text())
        archive_name, _, member = recorded["source"].partition(" :: ")
        self.assertEqual(archive_name, ARCHIVE.name)
        with tarfile.open(ARCHIVE) as archive:
            self.assertIn(member, archive.getnames())

    def test_exported_contract_and_plan_must_hash_to_the_bound_digests(self):
        """The exports behind the 14/14 result are the ones the ledger binds (Codex #231)."""
        for name in ("contract.draft.json", "compiled-plan.proposed.json"):
            with self.subTest(export=name):
                self.refused(
                    lambda replay, name=name: (replay / name).write_text("{}"),
                    name,
                )

    def test_retained_no_approval_claims_must_hold(self):
        """Approval, receipt and model-call claims in the exports must match the verdicts."""
        cases = {
            "migration-status": ("migration.json", {"status": "APPROVED"}),
            "migration-receipt": ("migration.json", {"approval_receipt_created": True}),
            "migration-model-calls": ("migration.json", {"fresh_model_calls": 1}),
            "publisher-approval": ("publisher-result.json", {"approval": "APPROVED"}),
        }
        for label, (name, change) in cases.items():
            with self.subTest(change=label):
                self.refused(
                    lambda replay, name=name, change=change: self.change_json(
                        replay / name, lambda value: value.update(change)
                    ),
                    name,
                )

    def test_exported_candidate_and_mutants_must_match_the_ledger(self):
        """The product and negative controls behind the verdicts are the bound ones (Codex)."""
        cases = {
            "candidate": (
                lambda replay: (replay / "candidate/product.py").write_text("# replaced\n"),
                "candidate",
            ),
            "mutant-manifest": (
                lambda replay: (replay / "mutants/filtering.manifest.json").write_text("{}"),
                "mutant",
            ),
            "extra-mutant": (
                lambda replay: (replay / "mutants/extra.manifest.json").write_text("{}"),
                "mutant",
            ),
        }
        for name, (change, message) in cases.items():
            with self.subTest(change=name):
                self.refused(change, message)


if __name__ == "__main__":
    unittest.main()
