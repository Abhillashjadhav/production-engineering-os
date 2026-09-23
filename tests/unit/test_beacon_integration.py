"""Optional observer failures must never change or replay business execution."""
import argparse
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "beacon_integration",
    Path(__file__).resolve().parents[2] / "src/pmpe/beacon_integration.py",
)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class ObservationTests(unittest.TestCase):
    def test_missing_or_broken_adapter_runs_work_once(self):
        calls = []
        with patch.object(bridge, "import_module", side_effect=ImportError):
            with bridge.observe_command(argparse.Namespace()) as recorder:
                calls.append("business")
                bridge.record_result(recorder, 7)
        self.assertEqual(calls, ["business"])

    def test_nonzero_return_recorded_and_cleanup_failure_isolated(self):
        seen = []

        class Recorder:
            def __enter__(self):
                return self

            def set_result(self, result):
                seen.append(result)

            def __exit__(self, *failure):
                raise OSError("recorder unavailable")

        fake = types.SimpleNamespace(capture=lambda *a, **kw: Recorder())
        with patch.object(bridge, "import_module", return_value=fake):
            with bridge.observe_command(argparse.Namespace(repository_root="/tmp/project")) as run:
                bridge.record_result(run, 7)
        self.assertEqual(seen, [7])

    def test_observer_cannot_suppress_task_error(self):
        class Recorder:
            def __enter__(self):
                return self

            def __exit__(self, *failure):
                return True

        fake = types.SimpleNamespace(capture=lambda *a, **kw: Recorder())
        with patch.object(bridge, "import_module", return_value=fake):
            with self.assertRaisesRegex(ValueError, "original task failure"):
                with bridge.observe_command(argparse.Namespace()):
                    raise ValueError("original task failure")


if __name__ == "__main__":
    unittest.main()
