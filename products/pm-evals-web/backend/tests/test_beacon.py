"""Offline ASGI seam check; does not run models, upload data, or use a collector."""

import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "beacon",
    Path(__file__).resolve().parents[1] / "src/pm_evals_monitoring/beacon.py",
)
beacon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(beacon)


class BeaconHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_unchanged_recording_optional_and_reads_excluded(self):
        events = []

        class Recorder:
            def __init__(self, *args, **kwargs):
                pass

            def event(self, action, **kwargs):
                events.append((action, kwargs))

        fake = types.SimpleNamespace(Run=Recorder)
        messages = [
            {"type": "http.response.start", "status": 422, "headers": []},
            {"type": "http.response.body", "body": b"PRIVATE_SENTINEL"},
        ]

        async def app(scope, receive, send):
            for message in messages:
                await send(message)

        async def receive():
            raise AssertionError("recorder must not read the body")

        for method, path, installed in [
            ("POST", "/api/compare", True),
            ("GET", "/api/health", True),
            ("POST", "/api/compare", False),
        ]:
            sent = []

            async def send(message):
                sent.append(message)

            events.clear()
            replacement = {"return_value": fake} if installed else {"side_effect": ImportError}
            with patch.object(beacon, "import_module", **replacement):
                await beacon.BeaconWorkflowMiddleware(app)(
                    {"type": "http", "method": method, "path": path}, receive, send
                )
            self.assertEqual(sent, messages)
            self.assertNotIn("PRIVATE_SENTINEL", repr(events))
            self.assertEqual(len(events), 2 if method == "POST" and installed else 0)
            if events:
                self.assertEqual(events[-1][1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
