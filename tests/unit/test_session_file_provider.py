"""Transport checks use test-authored responses; they are not live-model evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROVIDER = Path(__file__).resolve().parents[2] / "examples/barebones/session-file-provider.py"
DIGEST = "sha256:" + "a" * 64


class SessionFileProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def start(self, timeout: str = "5") -> subprocess.Popen[str]:
        self.assertTrue(PROVIDER.is_file(), "owner-approved session-file provider is absent")
        process = subprocess.Popen(
            [sys.executable, str(PROVIDER), "--handoff-dir", str(self.root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PMPE_PROVIDER_TIMEOUT_SECONDS": timeout},
        )
        self.addCleanup(self.cleanup_process, process)
        assert process.stdin is not None
        process.stdin.write(json.dumps({"purpose": "code", "request": {"request_digest": DIGEST}}))
        process.stdin.close()
        process.stdin = None
        return process

    @staticmethod
    def cleanup_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=3)

    def request_path(self, process: subprocess.Popen[str]) -> Path:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            paths = list(self.root.glob("call-*/request.json"))
            if paths:
                return paths[0]
            if process.poll() is not None:
                _, stderr = process.communicate()
                self.fail(f"provider exited before handoff: {stderr}")
            time.sleep(0.01)
        raise self.failureException("request file was not published")

    @staticmethod
    def write_response(request_path: Path, payload: object) -> None:
        temporary = request_path.with_name("response.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(request_path.with_name("response.json"))

    def test_round_trip_retains_request_response_and_elapsed_time(self) -> None:
        process = self.start()
        request_path = self.request_path(process)
        request = json.loads(request_path.read_text())
        self.assertEqual(request["request"]["request_digest"], DIGEST)
        reply = {"request_digest": DIGEST, "files": {"product.py": "print('transport test')\n"}}
        self.write_response(request_path, reply)
        stdout, stderr = process.communicate(timeout=3)
        self.assertEqual(process.returncode, 0, stderr)
        output = json.loads(stdout)
        self.assertEqual(output["files"], reply["files"])
        self.assertEqual(output["request_digest"], DIGEST)
        self.assertEqual(output["provider_metadata"]["provider"], "in-session-file-handoff")
        self.assertEqual(json.loads(request_path.with_name("response.json").read_text()), reply)
        self.assertEqual(json.loads(request_path.with_name("output.json").read_text()), output)
        record = json.loads(request_path.with_name("call.json").read_text())
        self.assertEqual(record["status"], "completed")
        self.assertGreaterEqual(record["elapsed_ms"], 0)

    def test_wrong_digest_is_rejected_and_retained(self) -> None:
        process = self.start()
        request_path = self.request_path(process)
        self.write_response(request_path, {"request_digest": "sha256:" + "b" * 64})
        stdout, stderr = process.communicate(timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(stdout, "")
        self.assertIn("RESPONSE_DIGEST_MISMATCH", stderr)
        self.assertTrue(request_path.with_name("response.json").is_file())
        record = json.loads(request_path.with_name("call.json").read_text())
        self.assertEqual(record["status"], "failed")

    def test_missing_response_times_out(self) -> None:
        process = self.start("1")
        request_path = self.request_path(process)
        stdout, stderr = process.communicate(timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(stdout, "")
        self.assertIn("RESPONSE_TIMEOUT", stderr)
        self.assertTrue(request_path.is_file())

    def test_malformed_response_is_rejected(self) -> None:
        process = self.start()
        request_path = self.request_path(process)
        request_path.with_name("response.json").write_text("{broken")
        stdout, stderr = process.communicate(timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(stdout, "")
        self.assertIn("RESPONSE_INVALID", stderr)

    def test_response_symlink_is_rejected(self) -> None:
        process = self.start()
        request_path = self.request_path(process)
        other = self.root / "elsewhere.json"
        other.write_text(json.dumps({"request_digest": DIGEST}))
        request_path.with_name("response.json").symlink_to(other)
        stdout, stderr = process.communicate(timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(stdout, "")
        self.assertIn("RESPONSE_INVALID", stderr)

    def test_old_response_is_not_reused_for_another_call(self) -> None:
        old = self.root / "call-old"
        old.mkdir()
        (old / "response.json").write_text(json.dumps({"request_digest": DIGEST}))
        process = self.start("1")
        self.request_path(process)
        stdout, stderr = process.communicate(timeout=3)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(stdout, "")
        self.assertIn("RESPONSE_TIMEOUT", stderr)


if __name__ == "__main__":
    unittest.main()
