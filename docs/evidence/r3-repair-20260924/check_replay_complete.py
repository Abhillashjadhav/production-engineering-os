"""Check retained v1 observations against pinned sources; never run the candidate.

Supply the historical PMOS packet and PEOS source tree explicitly. Paths recorded
in the evidence are labels for reconstructing inventory hashes, never read paths.
This checks consistency of retained data, not historical runtime authentication.
"""

import argparse
import ast
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

import rfc8785

FREEZE = "sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2"
# replay-commands.json as published with the historical engine at c1ab2def (#210).
LAUNCH_RECORD = "sha256:b7f352715dcb194067147d16da7ba2b99c574f369f0fa5d0dbb9114d9c5ad99c"
PRODUCT_EXIT_CODES = frozenset({0, 1, 2})
INTERPRETER = re.compile(r"python3?(\.[0-9]+)?")
EXPECTED_FAILURES = {
    "retained": [],
    "persistence": [
        "AC-002",
        "AC-003",
        "AC-004",
        "AC-005",
        "AC-006",
        "AC-007",
        "AC-009",
        "AC-010",
        "AC-013",
        "AC-014",
    ],
    "filtering": ["AC-004", "AC-005"],
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(content):
    return "sha256:" + hashlib.sha256(content).hexdigest()


def canonical(value):
    return raw(rfc8785.dumps(value))


def pairs(items):
    value = {}
    for key, child in items:
        require(key not in value, "duplicate JSON key")
        value[key] = child
    return value


def reject_constant(token):
    # The frozen engine refuses NaN and infinities before producing any result.
    raise ValueError("non-JSON constant " + token)


def decode(value):
    return json.loads(value, object_pairs_hook=pairs, parse_constant=reject_constant)


def read(path):
    return decode(path.read_bytes())


def rows(path):
    return [decode(row) for row in path.read_text().splitlines()]


def safe_file(root, relative):
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "unsafe manifest path")
    target = root / path
    require(
        not target.is_symlink() and target.resolve().is_relative_to(root),
        "manifest file escapes root or is a symlink",
    )
    return target


def recorded_paths(argv):
    roots = {}
    packet = None
    for index, value in enumerate(argv[:-1]):
        if value == "--root":
            name, path = argv[index + 1].split("=", 1)
            require(name not in roots and Path(path).is_absolute(), "recorded roots invalid")
            roots[name] = path
        elif value == "--packet":
            require(packet is None, "duplicate recorded packet")
            packet = argv[index + 1]
    require(
        set(roots) == {"PM-agent-OS", "production-engineering-os"} and packet,
        "recorded source roots incomplete",
    )
    return roots, packet


def crash_marker(value):
    if isinstance(value, dict):
        if value.get("invalid_json") is True:
            return True
        # The frozen task tracker exits only 0, 1 or 2. Any other code (a timeout
        # label, 127 command-not-found, a signal such as 137, a non-int) is a crash.
        if "exit_code" in value:
            code = value["exit_code"]
            if type(code) is not int or code not in PRODUCT_EXIT_CODES:
                return True
        return any(crash_marker(child) for child in value.values())
    return isinstance(value, list) and any(crash_marker(child) for child in value)


def frozen_runner(source):
    """The action runner literal inside the frozen engine's ``_run_action``."""
    tree = ast.parse((source / "src/pmpe/barebones.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_action":
            for item in ast.walk(node):
                if isinstance(item, ast.Assign) and [
                    getattr(t, "id", None) for t in item.targets
                ] == ["runner"]:
                    value = ast.literal_eval(item.value)
                    require(isinstance(value, str), "frozen runner is not a string")
                    return value
    raise ValueError("frozen engine action runner not found")


def frozen_environment(source):
    """The literal ``environment=`` mapping of ``sandbox.run`` in the frozen ``_run_action``.

    Module-level string constants it names (``_SANDBOX_PATH``) are resolved from the same
    digest-checked file.
    """
    tree = ast.parse((source / "src/pmpe/barebones.py").read_text())
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                constants[target.id] = node.value.value
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_action":
            for call in ast.walk(node):
                for keyword in getattr(call, "keywords", []):
                    if keyword.arg == "environment" and isinstance(keyword.value, ast.Dict):
                        environment = {}
                        for key, value in zip(
                            keyword.value.keys, keyword.value.values, strict=True
                        ):
                            require(isinstance(key, ast.Constant), "frozen environment key")
                            if isinstance(value, ast.Name):
                                require(value.id in constants, "frozen environment constant")
                                environment[key.value] = constants[value.id]
                            else:
                                environment[key.value] = ast.literal_eval(value)
                        return environment
    raise ValueError("frozen engine action environment not found")


def frozen_timeout(source):
    """``_ACTION_TIMEOUT_SECONDS`` of the frozen engine."""
    for node in ast.parse((source / "src/pmpe/barebones.py").read_text()).body:
        if (
            isinstance(node, ast.Assign)
            and [getattr(t, "id", None) for t in node.targets] == ["_ACTION_TIMEOUT_SECONDS"]
            and isinstance(node.value, ast.Constant)
        ):
            return node.value.value
    raise ValueError("frozen engine action timeout not found")


def frozen_output_limit(source, entry_relative):
    """The digest-bound adapter's ``LIMIT`` on captured stdout/stderr bytes."""
    for node in ast.parse((source / entry_relative).read_text()).body:
        if (
            isinstance(node, ast.Assign)
            and [getattr(t, "id", None) for t in node.targets] == ["LIMIT"]
            and isinstance(node.value, ast.Constant)
            and type(node.value.value) is int
        ):
            return node.value.value
    raise ValueError("frozen adapter output limit not found")


def min_captured_bytes(text):
    """Fewest raw bytes that decode (errors="replace") to ``text``.

    Every character re-encodes to its own UTF-8 bytes, except that U+FFFD may stand
    for a single invalid byte, so each one can account for as little as one byte.
    """
    return len(text.encode("utf-8")) - 2 * text.count("\ufffd")


# HostExecution.run adds exit_code/stdout/stderr only after success and "error" only
# from its exception branch, so a successful record has exactly these keys.
SUCCESS_RECORD_KEYS = frozenset(
    {
        "check_index",
        "criterion_id",
        "mode",
        "argv",
        "timeout_seconds",
        "environment",
        "exit_code",
        "stdout",
        "stderr",
        "elapsed_ms",
    }
)


def frozen_mode(source, entry_relative):
    """The one ``"mode"`` literal the digest-bound adapter records for each process."""
    modes = {
        value.value
        for node in ast.walk(ast.parse((source / entry_relative).read_text()))
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == "mode" and isinstance(value, ast.Constant)
    }
    require(len(modes) == 1, "frozen adapter execution mode is ambiguous")
    return next(iter(modes))


def check(directory, packet, source, case):
    root, packet, source = Path(directory), Path(packet).resolve(), Path(source).resolve()
    local_roots = {"PM-agent-OS": packet.parents[1], "production-engineering-os": source}
    freeze = read(packet / "freeze-manifest.json")
    require(canonical(freeze) == FREEZE, "unexpected historical freeze identity")
    require(
        (packet / "freeze-bundle.sha256").read_text().strip() == FREEZE,
        "historical freeze anchor mismatch",
    )
    require(len(freeze["artifacts"]) == 218, "frozen inventory incomplete")
    source_mismatches = []
    for item in freeze["artifacts"]:
        actual = raw(safe_file(local_roots[item["repository"]], item["path"]).read_bytes())
        if actual != item["sha256"]:
            source_mismatches.append(item["path"])
    require(not source_mismatches, "frozen source digest mismatches: " + str(source_mismatches))
    # The command entry is a later adapter, outside the original freeze.
    entry_relative = "examples/barebones/contract-file.py"
    entry_hash = raw((source / entry_relative).read_bytes())
    execution = read(root / "execution-source.json")
    require(
        execution["entry_digest"] == entry_hash and execution["freeze_digest"] == FREEZE,
        "execution source binding mismatch",
    )
    recorded_roots, recorded_packet = recorded_paths(execution["argv"])
    base = [
        (str(Path(recorded_roots[x["repository"]]) / x["path"]), x["sha256"])
        for x in freeze["artifacts"]
    ]
    base.append(
        (
            str(Path(recorded_packet) / "freeze-manifest.json"),
            raw((packet / "freeze-manifest.json").read_bytes()),
        )
    )
    entry_label = str(Path(recorded_roots["production-engineering-os"]) / entry_relative)
    sys.path.insert(0, str(source / "src"))
    # A new empty prefix prevents Python from reading local stale bytecode. -B
    # alone only prevents writes and is not sufficient for this purpose.
    with tempfile.TemporaryDirectory(prefix="replay-checker-pycache-") as pycache:
        sys.pycache_prefix = pycache
        import pmpe
        from pmpe.barebones import Template, _assertion_passes, compile_barebones_plan
        from pmpe.contracts.acceptance import PropertyAssertion
        from pmpe.contracts.authoring import verify_contract_approval

        require(
            Path(pmpe.__file__).resolve() == source / "src/pmpe/__init__.py",
            "checker imported a different PEOS engine",
        )
        contract, receipt = (
            read(packet / "contract.approved.json"),
            read(packet / "approval-receipt.json"),
        )
        require(
            verify_contract_approval(contract, receipt, expected_approver=freeze["owner"])
            == receipt["receipt_digest"],
            "historical receipt inconsistent",
        )
        template = Template(**read(packet / "bindings.json"))
        require(
            template.files["tests/acceptance/task_tracker.py"].encode()
            == (packet / "evaluator.py").read_bytes(),
            "observer binding differs",
        )
        plan = compile_barebones_plan(contract=contract, repository_root=source, template=template)
        require(
            canonical(plan.as_dict()) == canonical(read(packet / "compiled-plan.json")),
            "historical plan differs",
        )
        # The adapter aborts before any execution unless the report is compatible with
        # the frozen profile, so a run with records cannot carry any other report.
        compatibility = read(root / "compatibility.json")
        require(compatibility["plan_digest"] == plan.plan_digest, "recorded plan differs")
        # Every field is fixed by the adapter's compatibility(): the frozen profile, the
        # CPython 3.12 constraint it enforces, and its literal scope statement.
        profile = read(packet / "execution-profile.json")
        require(
            set(compatibility)
            == {
                "compatible",
                "reasons",
                "plan_digest",
                "runtime",
                "dependencies",
                "profile_digest",
                "missing_isolations",
                "scope",
            }
            and compatibility["compatible"] is True
            and compatibility["reasons"] == []
            and compatibility["profile_digest"]
            == raw((packet / "execution-profile.json").read_bytes())
            and compatibility["dependencies"] == profile["candidate_dependencies"] == []
            and compatibility["missing_isolations"]
            == profile["authorized_fallback"]["unavailable_additional_protections"]
            and compatibility["scope"] == "can attempt and evaluate; not a delivery guarantee"
            and isinstance(compatibility["runtime"], str)
            and compatibility["runtime"].startswith("3.12."),
            "compatibility report is not the frozen profile's compatible report",
        )
        result = read(root / "result.json")
        # contract-file.py's verify flow writes exactly these two fields.
        require(
            isinstance(result, dict) and set(result) == {"criteria", "findings"},
            "result.json has fields the adapter does not write",
        )
        ids = [c.criterion_id for c in plan.criteria]
        require(ids == [f"AC-{i:03d}" for i in range(1, 15)], "criterion coverage")
        observations, processes = rows(root / "digest-checks.jsonl"), rows(root / "processes.jsonl")
        expected = [("before", "command")]
        expected += [(stage, cid) for cid in ids for stage in ("before", "after")]
        expected += [("after", "command")]
        require(
            [(o["stage"], o["subject"]) for o in observations] == expected,
            "boundary sequence incomplete",
        )
        require([p["criterion_id"] for p in processes] == ids, "process coverage incomplete")
        # DigestGuard.check writes exactly these fields, with a list of mismatches.
        require(
            all(
                isinstance(o, dict)
                and set(o)
                == {
                    "stage",
                    "subject",
                    "checked",
                    "expected_inventory_digest",
                    "observed_inventory_digest",
                    "mismatches",
                }
                and isinstance(o["mismatches"], list)
                for o in observations
            ),
            "digest observation is not one DigestGuard.check writes",
        )
        mismatch_count = sum(len(o["mismatches"]) for o in observations)
        require(mismatch_count == 0, "recorded digest mismatches")
        inventory_mismatches = 0

        def inventory(record, entries):
            nonlocal inventory_mismatches
            expected_digest = canonical(entries)
            matches = (
                type(record["checked"]) is int
                and record["checked"] == len(entries)
                and record["expected_inventory_digest"] == expected_digest
                and record["observed_inventory_digest"] == expected_digest
            )
            inventory_mismatches += int(not matches)

        inventory(observations[0], base + [(entry_label, entry_hash)])
        inventory(observations[-1], base + [(entry_label, entry_hash)])
        semantic = {}
        expected_findings = []
        runner = frozen_runner(source)
        environment = frozen_environment(source)
        timeout = frozen_timeout(source)
        mode = frozen_mode(source, entry_relative)
        limit = frozen_output_limit(source, entry_relative)
        caps = read(packet / "execution-profile.json")["resource_caps"]
        # The historical host fallback's exact prlimit prefix, from the frozen profile.
        limits = [
            "prlimit",
            f"--as={caps['address_space_bytes']}",
            f"--cpu={caps['action_cpu_seconds']}",
            f"--fsize={caps['file_size_bytes']}",
            f"--nofile={caps['open_files']}",
            f"--nproc={caps['processes']}",
            "--",
        ]
        interpreters = {p["argv"][7] for p in processes if isinstance(p.get("argv"), list)}
        require(len(interpreters) == 1, "observer interpreter differs between processes")
        interpreter = next(iter(interpreters))
        require(
            isinstance(interpreter, str)
            and Path(interpreter).is_absolute()
            and INTERPRETER.fullmatch(Path(interpreter).name) is not None,
            "observer interpreter is not an absolute Python executable",
        )
        # The operator's launch record beside the case directories is written by the
        # outer replay driver, not by the observed engine. Its bytes are pinned to the
        # copy published at c1ab2def, so it cannot be re-paired with edited records.
        # This still does not authenticate the interpreter binary itself.
        launch_bytes = (root.parent / "replay-commands.json").read_bytes()
        require(raw(launch_bytes) == LAUNCH_RECORD, "replay launch record differs from pin")
        launches = decode(launch_bytes)
        require(isinstance(launches, list), "replay launch record is not a list")
        matching = [
            item for item in launches if isinstance(item, dict) and item.get("case") == case
        ]
        require(len(matching) == 1, "replay launch record must name this case exactly once")
        launch = matching[0]
        require(
            type(launch.get("exit_code")) is int
            and launch["exit_code"] == launch.get("expected_exit_code")
            and launch.get("passed") is True,
            "operator launch record reports a failed or crashed replay",
        )
        command = launch.get("command")
        require(
            isinstance(command, list) and bool(command) and command[0] == interpreter,
            "observer interpreter differs from the operator's replay launch record",
        )
        require(
            command[1:] == execution["argv"],
            "recorded invocation differs from the operator's replay launch record",
        )
        for index, (criterion, process) in enumerate(zip(plan.criteria, processes, strict=True)):
            require(
                type(process["check_index"]) is int and process["check_index"] == index,
                "process index mismatch",
            )
            require(
                type(process["exit_code"]) is int
                and process["exit_code"] == 0
                and process["stderr"] == "",
                "observer process failed",
            )
            argv = process["argv"]
            require(isinstance(argv, list) and len(argv) >= 5, "process argv missing")
            snippets = [x for x in argv if isinstance(x, str) and "sys.path.insert(0," in x]
            require(len(snippets) == 1, "observer launch context ambiguous")
            match = re.search(r"sys.path.insert\(0,(.*?)\);", snippets[0])
            require(match is not None, "observer workspace missing")
            workspace = ast.literal_eval(match.group(1))
            require(
                isinstance(workspace, str) and Path(workspace).is_absolute(),
                "workspace label invalid",
            )
            protected = [
                (str(Path(workspace) / relative), raw(content.encode()))
                for relative, content in template.files.items()
                if relative.startswith("tests/")
            ]
            entries = base + protected + [(entry_label, entry_hash)]
            for record in observations[1 + 2 * index : 3 + 2 * index]:
                inventory(record, entries)
            # The frozen runner is launched with exactly this environment (no PATH or
            # PYTHONPATH of the operator's choosing), then canonicalizes the value it read.
            require(
                process.get("environment") == environment,
                "observer environment differs from the frozen engine",
            )
            require(
                process.get("timeout_seconds") == timeout and process.get("mode") == mode,
                "observer timeout or execution mode differs from the frozen engine",
            )
            # The adapter caps captured bytes; min_captured_bytes is a lower bound on them.
            elapsed = process.get("elapsed_ms")
            require(
                set(process) == SUCCESS_RECORD_KEYS
                and type(elapsed) is float
                and 0.0 <= elapsed < float("inf")
                and isinstance(process["stdout"], str)
                and min_captured_bytes(process["stdout"]) <= limit
                and isinstance(process["stderr"], str)
                and min_captured_bytes(process["stderr"]) <= limit,
                "process record is not one the adapter's success path emits",
            )
            value = decode(process["stdout"])
            canonical(value)
            # The frozen runner prints json.dumps(v, sort_keys=True, separators=(",", ":"))
            # once, so a successful record's stdout is exactly that line.
            require(
                process["stdout"]
                == json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
                "observer stdout is not the frozen runner's serialization",
            )
            require(not crash_marker(value), "observer crash/timeout marker")
            if criterion.form == "measure":
                target = template.measures[criterion.measure]
                arguments = {}
                # The frozen engine aborts (ContractInvalidError) on these; they never FAIL.
                require(isinstance(value, dict), "measure did not return a JSON object")
                require(
                    type(value.get("sample_size")) is int,
                    "measure did not return an integer sample_size",
                )
                passed = value["sample_size"] >= criterion.minimum_sample and _assertion_passes(
                    PropertyAssertion("value", criterion.operator, criterion.value), value
                )
            else:
                target = template.actions[criterion.when.action]
                arguments = dict(criterion.when.arguments)
                passed = all(
                    _assertion_passes(x, template.context) for x in criterion.given
                ) and all(_assertion_passes(x, {"result": value}) for x in criterion.then)
            require(
                argv[-3:-1] == target.split(":")
                # _run_action passes json.dumps(arguments) verbatim as the last argument.
                and argv[-1] == json.dumps(arguments),
                "observer target or arguments differ",
            )
            # The host fallback rewrites only the '/workspace' constant of the engine runner.
            require(
                len(argv) == 16 and argv[:7] == limits and argv[7] == interpreter,
                "observer command prefix differs from the frozen host fallback",
            )
            require(
                argv[-8:-3]
                == [
                    "-I",
                    "-B",
                    "-c",
                    runner.replace("'/workspace'", repr(workspace)),
                    "unused-workspace-argument",
                ],
                "observer runner differs from the frozen engine runner",
            )
            semantic[criterion.criterion_id] = "PASS" if passed else "FAIL"
            if not passed:
                expected_findings.append(
                    {
                        "code": "ASSERTION_FAILED",
                        "files": [target.split(":", 1)[0].replace(".", "/") + ".py"],
                        "message": (
                            "compiled measure assertion failed"
                            if criterion.form == "measure"
                            else "compiled acceptance assertion failed"
                        ),
                        "subject_id": criterion.criterion_id,
                    }
                )
        require(
            inventory_mismatches == 0, f"{inventory_mismatches} reconstructed inventories differ"
        )
        require(semantic == result["criteria"], "recorded criterion statuses disagree with stdout")
        failed = [cid for cid, status in semantic.items() if status == "FAIL"]
        require(failed == EXPECTED_FAILURES[case], "case has unexpected criterion outcomes")
        require(
            canonical(result["findings"]) == canonical(expected_findings),
            "findings differ from one canonical finding per failed criterion",
        )
        return {
            "digest_observations": len(observations),
            "process_records": len(processes),
            "digest_mismatches": mismatch_count + inventory_mismatches + len(source_mismatches),
            "frozen_source_entries": len(freeze["artifacts"]),
            "pass_count": 14 - len(failed),
            "fail_ids": failed,
            "checker_engine_file": str(Path(pmpe.__file__).resolve()),
            "checker_engine_file_digest": raw(Path(pmpe.__file__).read_bytes()),
            "historical_engine_authentication": "NOT_ESTABLISHED_BY_RETAINED_PACKET",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--peos-source", type=Path, required=True)
    parser.add_argument("--case", choices=tuple(EXPECTED_FAILURES), required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                check(args.directory, args.packet, args.peos_source, args.case), sort_keys=True
            )
        )
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError) as exc:
        print(json.dumps({"status": "FAIL", "detail": str(exc)}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
