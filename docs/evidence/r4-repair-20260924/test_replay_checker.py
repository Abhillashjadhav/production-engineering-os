"""Mutate retained evidence, never execute or edit the frozen candidate/runner."""

import hashlib
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
            # The operator's independent launch record sits beside the case directories.
            shutil.copyfile(EVIDENCE / "replay-commands.json", root.parent / "replay-commands.json")
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

    def test_non_signal_abnormal_exit_rejected(self):
        """127 (command not found) is outside the frozen task tracker's 0/1/2 exits."""

        def change(rows):
            row = next(item for item in rows if item["criterion_id"] == "AC-002")
            value = json.loads(row["stdout"])
            value["observations"][-1]["exit_code"] = 127
            row["stdout"] = json.dumps(value)

        self.mutate("persistence", lambda root: self.change_rows(root, "processes.jsonl", change))

    def test_replaced_interpreter_or_limits_rejected(self):
        def one_interpreter(rows):
            rows[0]["argv"][7] = "/usr/bin/python3"

        def every_interpreter(rows):
            for row in rows:
                row["argv"][7] = "/tmp/fabricated-runner"

        def limits(rows):
            for row in rows:
                row["argv"][2] = "--cpu=9999"

        for change in (one_interpreter, every_interpreter, limits):
            with self.subTest(change=change.__name__):
                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_rows(root, "processes.jsonl", change),
                )

    def test_python_named_fake_interpreter_rejected(self):
        """A fake path with an accepted basename must not match the operator's launcher."""

        def change(rows):
            for row in rows:
                row["argv"][7] = "/tmp/python3"

        self.mutate("retained", lambda root: self.change_rows(root, "processes.jsonl", change))

    def change_launch(self, root, change):
        path = root.parent / "replay-commands.json"
        launches = json.loads(path.read_text())
        change(next(item for item in launches if item["case"] == root.name))
        path.write_text(json.dumps(launches, indent=2) + "\n")

    def test_paired_interpreter_and_launch_record_rejected(self):
        """Editing the records and the launch record together must still fail."""

        def change(root):
            def rows(items):
                for row in items:
                    row["argv"][7] = "/tmp/python3"

            self.change_rows(root, "processes.jsonl", rows)
            self.change_launch(root, lambda item: item["command"].__setitem__(0, "/tmp/python3"))

        self.mutate("retained", change)

    def test_failed_outer_launch_rejected(self):
        for field, value in (("exit_code", 137), ("passed", False)):
            with self.subTest(field=field):
                self.mutate(
                    "retained",
                    lambda root, field=field, value=value: self.change_launch(
                        root, lambda item: item.__setitem__(field, value)
                    ),
                )

    def test_invalid_measure_sample_type_rejected(self):
        """The frozen engine aborts on a non-integer sample_size; it never yields FAIL."""
        for sample in (True, "1"):
            with self.subTest(sample=sample):

                def change(rows, sample=sample):
                    value = json.loads(rows[12]["stdout"])
                    value["sample_size"] = sample
                    rows[12]["stdout"] = json.dumps(value)

                self.mutate(
                    "persistence",
                    lambda root, change=change: self.change_rows(root, "processes.jsonl", change),
                )

    def test_non_json_constant_in_stdout_rejected(self):
        """The frozen engine rejects NaN and infinities before producing a result."""
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):

                def change(rows, constant=constant):
                    text = rows[0]["stdout"].rstrip()
                    rows[0]["stdout"] = text[:-1] + ', "extra": ' + constant + "}\n"

                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_rows(root, "processes.jsonl", change),
                )

    def test_replaced_execution_environment_rejected(self):
        """A PATH naming a fake prlimit keeps argv intact; the frozen environment is fixed."""
        for key, value in (("PATH", "/tmp/fake-bin:/usr/bin:/bin"), ("PYTHONPATH", "/tmp/x")):
            with self.subTest(key=key):

                def change(rows, key=key, value=value):
                    for row in rows:
                        row["environment"][key] = value

                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_rows(root, "processes.jsonl", change),
                )

    def test_integer_outside_canonical_domain_rejected(self):
        """The frozen engine canonicalizes every action value; 2**53 cannot be produced."""

        def change(rows):
            text = rows[0]["stdout"].rstrip()
            rows[0]["stdout"] = text[:-1] + ', "extra": 9007199254740992}\n'

        self.mutate("retained", lambda root: self.change_rows(root, "processes.jsonl", change))

    def change_json(self, root, filename, change):
        path = root / filename
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value, indent=2) + "\n")

    def test_incompatible_or_reprofiled_report_rejected(self):
        """The adapter aborts before any execution when compatibility is false."""
        changes = {
            "incompatible": lambda value: value.update(compatible=False),
            "reasons": lambda value: value.update(reasons=["runtime changed"]),
            "profile": lambda value: value.update(profile_digest="sha256:" + "0" * 64),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_json(
                        root, "compatibility.json", change
                    ),
                )

    def test_recorded_invocation_differs_from_launch_rejected(self):
        """execution-source.json must repeat the pinned launch command after the interpreter."""
        changes = {
            "build": lambda value: value["argv"].__setitem__(1, "build"),
            "no-fallback": lambda value: value["argv"].remove("--authorized-host-fallback"),
            "other-candidate": lambda value: value["argv"].__setitem__(
                value["argv"].index("--candidate") + 1, "elsewhere/candidate"
            ),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_json(
                        root, "execution-source.json", change
                    ),
                )

    def test_compatibility_report_fields_rejected(self):
        """Every field of the adapter's report is fixed by the frozen profile and runtime."""
        changes = {
            "runtime": lambda value: value.update(runtime="3.11.9 (main) [GCC]"),
            "dependencies": lambda value: value.update(dependencies=["requests"]),
            "isolations": lambda value: value.update(missing_isolations=[]),
            "scope": lambda value: value.update(scope="delivery guaranteed"),
            "extra": lambda value: value.update(sandbox="full"),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_json(
                        root, "compatibility.json", change
                    ),
                )

    def test_process_timeout_or_mode_rejected(self):
        """Each record states the frozen 10 s timeout and the host-fallback mode."""
        for key, value in (("timeout_seconds", 30.0), ("mode", "FULL_ISOLATION")):
            with self.subTest(key=key):

                def change(rows, key=key, value=value):
                    rows[0][key] = value

                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_rows(root, "processes.jsonl", change),
                )

    def test_record_the_adapter_cannot_emit_rejected(self):
        """Success records have a fixed key set, a non-negative elapsed time and bounded output."""
        changes = {
            "error-key": lambda row: row.update(error="TimeoutExpired: fabricated"),
            "negative-elapsed": lambda row: row.update(elapsed_ms=-1.0),
            "string-elapsed": lambda row: row.update(elapsed_ms="120"),
            "stdout-over-limit": lambda row: row.update(
                stdout=row["stdout"].rstrip("\n") + " " * 1_000_001 + "\n"
            ),
            "stderr-over-limit": lambda row: row.update(stderr="x" * 1_000_001),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_rows(
                        root, "processes.jsonl", lambda rows: change(rows[0])
                    ),
                )

    def test_multibyte_output_over_byte_limit_rejected(self):
        """The adapter limits captured bytes, not decoded characters."""

        def change(rows):
            text = rows[0]["stdout"].rstrip()
            rows[0]["stdout"] = text[:-1] + ', "extra": "' + "\u00e9" * 500_001 + '"}\n'

        self.mutate("retained", lambda root: self.change_rows(root, "processes.jsonl", change))

    def test_extra_result_field_rejected(self):
        """The adapter's verify flow writes result.json with exactly criteria and findings."""
        self.mutate(
            "persistence",
            lambda root: self.change_json(root, "result.json", lambda v: v.update(cause="PASS")),
        )

    def test_malformed_digest_observation_rejected(self):
        """DigestGuard.check writes six fields with a list of mismatches."""
        changes = {
            "mismatches-object": lambda row: row.update(mismatches={}),
            "mismatches-string": lambda row: row.update(mismatches=""),
            "extra-field": lambda row: row.update(verdict="clean"),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_rows(
                        root, "digest-checks.jsonl", lambda rows: change(rows[0])
                    ),
                )

    def test_reformatted_observer_output_rejected(self):
        """The frozen runner prints one compact, key-sorted JSON line."""
        changes = {
            "leading-spaces": lambda row: row.update(stdout="   " + row["stdout"]),
            "trailing-blank-lines": lambda row: row.update(stdout=row["stdout"] + "\n\n"),
            "spaced-separators": lambda row: row.update(
                stdout=json.dumps(json.loads(row["stdout"]), sort_keys=True) + "\n"
            ),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_rows(
                        root, "processes.jsonl", lambda rows: change(rows[0])
                    ),
                )

    def test_reformatted_action_argument_rejected(self):
        """The frozen engine passes arguments as the exact output of json.dumps(arguments)."""

        def change(rows):
            for row in rows:
                if row["argv"][-1] != "{}":
                    value = json.loads(row["argv"][-1])
                    row["argv"][-1] = json.dumps(value, separators=(",", ":"))
                    return
            raise AssertionError("no record with non-empty arguments")

        self.mutate("retained", lambda root: self.change_rows(root, "processes.jsonl", change))

    def test_substituted_adapter_rejected(self):
        """A different adapter in the supplied source cannot be paired with matching records."""
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            shutil.copytree(SOURCE, source, symlinks=True, ignore=shutil.ignore_patterns(".git"))
            adapter = source / "examples/barebones/contract-file.py"
            adapter.write_bytes(adapter.read_bytes() + b"\n# substituted adapter\n")
            digest = "sha256:" + hashlib.sha256(adapter.read_bytes()).hexdigest()
            root = Path(temporary) / "cases" / "retained"
            shutil.copytree(EVIDENCE / "retained", root)
            shutil.copyfile(EVIDENCE / "replay-commands.json", root.parent / "replay-commands.json")
            self.change_json(
                root, "execution-source.json", lambda value: value.update(entry_digest=digest)
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(CHECKER),
                    str(root),
                    "--packet",
                    str(PACKET),
                    "--peos-source",
                    str(source),
                    "--case",
                    "retained",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("adapter", result.stdout)

    def test_execution_source_fields_rejected(self):
        """contract-file.py writes exactly four execution-source fields and a literal kind."""
        changes = {
            "kind": lambda value: value.update(kind="authenticated historical runtime"),
            "extra": lambda value: value.update(runtime_authenticated=True),
        }
        for name, change in changes.items():
            with self.subTest(change=name):
                self.mutate(
                    "retained",
                    lambda root, change=change: self.change_json(
                        root, "execution-source.json", change
                    ),
                )

    def test_fields_the_frozen_evaluator_cannot_return_rejected(self):
        """observe(), the measure and _call() each return a fixed set of fields."""

        def extra_top(row):
            value = json.loads(row["stdout"])
            value["extra"] = 1
            row["stdout"] = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"

        def extra_nested(row):
            value = json.loads(row["stdout"])
            value["observations"][0]["extra"] = 1
            row["stdout"] = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"

        cases = {
            "action-top-level": ("retained", 0, extra_top),
            "action-observation": ("retained", 0, extra_nested),
            "measure-top-level": ("persistence", 12, extra_top),
        }
        for name, (case, index, change) in cases.items():
            with self.subTest(change=name):
                self.mutate(
                    case,
                    lambda root, index=index, change=change: self.change_rows(
                        root, "processes.jsonl", lambda rows: change(rows[index])
                    ),
                )


if __name__ == "__main__":
    unittest.main()
