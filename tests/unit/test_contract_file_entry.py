"""Focused infrastructure checks; fixture behavior is not live model evidence."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pmpe.contracts.canonical import canonical_digest

ENTRY = Path(__file__).resolve().parents[2] / "examples/barebones/contract-file.py"


class ContractFileEntryTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ENTRY.is_file(), "owner-approved file loader/guard is absent")
        spec = importlib.util.spec_from_file_location("contract_file_entry", ENTRY)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.artifact = self.root / "criterion.json"
        self.artifact.write_text('{"expected":1}\n')
        self.manifest = self.root / "freeze.json"
        data = {
            "artifacts": [
                {
                    "repository": "fixture",
                    "path": self.artifact.name,
                    "sha256": "sha256:" + hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
                }
            ]
        }
        self.manifest.write_text(json.dumps(data))
        self.guard = self.module.DigestGuard(
            self.manifest,
            {"fixture": self.root},
            canonical_digest(data),
            self.root / "checks.jsonl",
        )

    def test_changed_approved_artifact_rejected(self):
        self.artifact.write_text('{"expected":2}\n')
        with self.assertRaises(self.module.TamperDetectedError):
            self.guard.check("before")

    def test_changed_manifest_rejected(self):
        self.manifest.write_text('{"artifacts":[]}')
        with self.assertRaises(self.module.TamperDetectedError):
            self.guard.check("before")

    def test_after_check_runs_on_execution_exception(self):
        with self.assertRaises(self.module.TamperDetectedError), self.guard.boundary("fixture"):
            self.artifact.write_text('{"expected":2}\n')
            raise subprocess.TimeoutExpired("fixture", 1)
        records = [json.loads(line) for line in self.guard.log.read_text().splitlines()]
        self.assertEqual([row["stage"] for row in records], ["before", "after"])
        self.assertTrue(records[-1]["mismatches"])

    def test_unsafe_template_path_rejected(self):
        path = self.root / "bindings.json"
        path.write_text(
            json.dumps(
                {"version": "test", "files": {"../escape.py": "x"}, "actions": {}, "context": {}}
            )
        )
        with self.assertRaises(ValueError):
            self.module.load_template(path)

    def test_nonprotected_evaluator_binding_rejected(self):
        path = self.root / "bindings.json"
        path.write_text(
            json.dumps(
                {
                    "version": "test",
                    "files": {"product.py": "def observe(): return 1"},
                    "actions": {"new.action": "product:observe"},
                    "context": {},
                }
            )
        )
        with self.assertRaises(ValueError):
            self.module.load_template(path)

    def test_evaluator_replacement_rejected(self):
        source = "def observe(): return 1\n"
        template = self.module.Template(
            version="test",
            files={"tests/check.py": source},
            actions={"new.action": "tests.check:observe"},
            context={},
        )
        work = self.root / "candidate"
        (work / "tests").mkdir(parents=True)
        (work / "tests/check.py").write_text("def observe(): return 2\n")
        execution = self.module.HostExecution(
            self.guard, template, {}, [], self.root / "processes.jsonl"
        )
        with self.assertRaises(self.module.TamperDetectedError):
            execution.run(
                work,
                [sys.executable, "-c", "raise SystemExit(0)"],
                timeout_seconds=1,
                environment={},
            )


if __name__ == "__main__":
    unittest.main()
