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
# examples/barebones/contract-file.py as published with the historical engine at c1ab2def;
# it is outside the 218-artifact freeze, so it is pinned here independently.
ADAPTER = "sha256:08d590186663d48a1ecfd34cb169240d07c9d65e132e4791c6816171f7ccf387"
# The candidate trees the pinned launch record names, as published with the historical
# engine at c1ab2def: raw digest of the sorted {relative path: raw file digest} map.
CANDIDATES = {
    "retained": "sha256:7ea438807695bfeaed854941913373380f34853e215389e38a59cb4aff5457a4",
    "persistence": "sha256:c0bec7f90556b77533044ff3aa5bd0b29ed748da548e08bb9f5ae28240ef8ff0",
    "filtering": "sha256:ea6eda80e8564e1a2e41355620be8a98fde19ec85704f5de3d0f0edbe0883486",
}
# tests/acceptance/task_tracker.py inside the frozen template; the measure-domain facts in
# check_measure_domain are read from exactly this source.
EVALUATOR = "sha256:7a5a3064d8ec07ae1d941aaa2145330076c8acf62bbbc7cc65e158b9f9cf4d66"
PRODUCT_EXIT_CODES = frozenset({0, 1, 2})
INTERPRETER = re.compile(r"python3?(\.[0-9]+)?")
# The exact sys.version the adapter recorded in the published compatibility reports.
RUNTIME = "3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]"
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
    """Each row exactly as the adapter's append() writes it: sorted json.dumps plus "\\n"."""
    text = path.read_bytes().decode("utf-8")
    require(text == "" or text.endswith("\n"), path.name + " is not newline-terminated JSONL")
    values = []
    for line in text.split("\n")[:-1]:
        value = decode(line)
        require(
            json.dumps(value, sort_keys=True) == line,
            path.name + " row differs from the adapter's serialization",
        )
        values.append(value)
    return values


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


def returned_fields(module_source, function):
    """The one key set that ``function`` returns as a literal dict in the frozen module."""
    shapes = {
        frozenset(key.value for key in node.value.keys)
        for definition in ast.walk(ast.parse(module_source))
        if isinstance(definition, ast.FunctionDef) and definition.name == function
        for node in ast.walk(definition)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Dict)
        and all(isinstance(key, ast.Constant) for key in node.value.keys)
    }
    require(len(shapes) == 1, f"frozen evaluator {function} has no single return shape")
    return next(iter(shapes))


def returned_call_lists(module_source, function):
    """How ``function`` builds the lists it returns, read from the frozen evaluator's AST.

    Returns ``(lists, counts, defaults)``: ``lists`` maps each returned key built as
    ``[callee(...) for _ in <iterable>]`` to ``(callee, iterable)``; ``counts`` maps each
    returned key computed as ``len(a) + len(b) + ...`` over those lists to their keys; and
    ``defaults`` holds the function's literal parameter defaults.
    """
    tree = ast.parse(module_source)
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    (definition,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function
    ]
    parameters = definition.args.args
    defaults = {
        parameter.arg: ast.literal_eval(default)
        for parameter, default in zip(
            parameters[len(parameters) - len(definition.args.defaults) :],
            definition.args.defaults,
            strict=True,
        )
    }
    built = {
        target.id: (node.value.elt.func.id, node.value.generators)
        for node in ast.walk(definition)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.ListComp)
        and isinstance(node.value.elt, ast.Call)
        and isinstance(node.value.elt.func, ast.Name)
        and node.value.elt.func.id in defined
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    def summed_lengths(node):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = summed_lengths(node.left), summed_lengths(node.right)
            return None if left is None or right is None else left + right
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in built
        ):
            return [node.args[0].id]
        return None

    lists, counts = {}, {}
    for node in ast.walk(definition):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            names = {}
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(value, ast.Name)
                    and value.id in built
                ):
                    callee, generators = built[value.id]
                    require(
                        len(generators) == 1 and not generators[0].ifs,
                        f"frozen evaluator list {key.value} is not one filter-free loop",
                    )
                    lists[key.value] = (callee, generators[0].iter)
                    names[value.id] = key.value
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                summed = summed_lengths(value)
                if isinstance(key, ast.Constant) and summed:
                    counts[key.value] = [names[name] for name in summed]
    return lists, counts, defaults


def returned_value_rules(module_source, function):
    """Values fixed by ``function``'s one literal-dict return, read from the frozen AST.

    Returns ``(constants, comparisons, lengths, ordered)``: keys returning a literal,
    keys returning a comparison (always a bool), and keys returning ``len(name)`` or
    ``sorted(name)``, each mapped to that local name. A function with more than one
    literal-dict return yields no rules.
    """
    tree = ast.parse(module_source)
    returns = [
        node.value
        for definition in ast.walk(tree)
        if isinstance(definition, ast.FunctionDef) and definition.name == function
        for node in ast.walk(definition)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    ]
    constants, comparisons, lengths, ordered = {}, set(), {}, {}
    if len(returns) != 1:
        return constants, comparisons, lengths, ordered
    for key, value in zip(returns[0].keys, returns[0].values, strict=True):
        if not isinstance(key, ast.Constant):
            continue
        if isinstance(value, ast.Constant):
            constants[key.value] = value.value
        elif isinstance(value, ast.Compare):
            comparisons.add(key.value)
        elif (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"len", "sorted"}
            and len(value.args) == 1
            and not value.keywords
            and isinstance(value.args[0], ast.Name)
        ):
            (lengths if value.func.id == "len" else ordered)[key.value] = value.args[0].id
    return constants, comparisons, lengths, ordered


def check_returned_values(value, module_source, function):
    """Refuse values the frozen function's literal return could not have produced."""
    constants, comparisons, lengths, ordered = returned_value_rules(module_source, function)
    for key, literal in constants.items():
        require(
            type(value[key]) is type(literal) and value[key] == literal,
            f"observer {key} differs from the frozen evaluator's literal",
        )
    for key in comparisons:
        require(type(value[key]) is bool, f"observer {key} is not the comparison's bool")
    for key in ordered:
        items = value[key]
        try:
            in_order = isinstance(items, list) and items == sorted(items)
        except TypeError:
            in_order = False
        require(in_order, f"observer {key} is not the sorted list the evaluator returns")
    for key, name in lengths.items():
        require(
            type(value[key]) is int and value[key] >= 0,
            f"observer {key} is not the length the evaluator returns",
        )
        for other, other_name in ordered.items():
            if other_name == name:
                require(
                    value[key] == len(value[other]),
                    f"observer {key} is not len({other}) as the evaluator returns",
                )


def tree_digest(root):
    """Raw digest of the sorted {relative path: raw digest} map of a regular-file tree."""
    require(root.is_dir() and not root.is_symlink(), "candidate is not a directory")
    files = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "candidate tree contains a symlink")
        if path.is_dir():
            continue
        require(path.is_file(), "candidate tree contains a non-regular file")
        files[path.relative_to(root).as_posix()] = raw(path.read_bytes())
    return raw(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())


def check_measure_domain(value, module_source, function):
    """Facts about the pinned measure that no single return expression states.

    ``missing_acknowledged_records`` (source pinned by EVALUATOR) loops ``range(N)`` once,
    stores at most one acknowledged ID per iteration as a dict key, admits only IDs with
    ``type(id) is int and id > 0``, and collects ``missing`` from those keys. So
    ``sample_size <= N``, ``value <= sample_size``, and ``missing_ids`` are distinct
    positive integers.
    """
    if function != "missing_acknowledged_records":
        return
    require(raw(module_source.encode()) == EVALUATOR, "measure source differs from the pin")
    (definition,) = [
        node
        for node in ast.walk(ast.parse(module_source))
        if isinstance(node, ast.FunctionDef) and node.name == function
    ]
    loops = [
        node.iter.args[0].value
        for node in ast.walk(definition)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Call)
        and isinstance(node.iter.func, ast.Name)
        and node.iter.func.id == "range"
        and len(node.iter.args) == 1
        and isinstance(node.iter.args[0], ast.Constant)
    ]
    require(len(loops) == 1 and type(loops[0]) is int, "measure loop bound is ambiguous")
    ids = value["missing_ids"]
    require(
        type(value["sample_size"]) is int
        and 0 <= value["value"] <= value["sample_size"] <= loops[0]
        and all(type(item) is int and item > 0 for item in ids)
        and len(set(ids)) == len(ids),
        "measure result is outside the frozen evaluator's domain",
    )


def iterated(node, bound):
    """The value a frozen comprehension iterates over: a parameter, or ``parameter or []``."""
    if isinstance(node, ast.Name):
        require(node.id in bound, f"frozen evaluator iterates unbound {node.id}")
        return bound[node.id]
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        # Python's `a or b`: the first truthy operand, else the last one.
        for operand in node.values:
            value = (
                iterated(operand, bound)
                if isinstance(operand, ast.Name)
                else ast.literal_eval(operand)
            )
            if value:
                break
        return value
    require(False, "frozen evaluator iterates an unsupported expression")
    return None


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
    require(entry_hash == ADAPTER, "supplied adapter differs from the pinned historical adapter")
    execution = read(root / "execution-source.json")
    kinds = {
        value.value
        for node in ast.walk(ast.parse((source / entry_relative).read_text()))
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == "kind" and isinstance(value, ast.Constant)
    }
    require(len(kinds) == 1, "pinned adapter execution-source kind is ambiguous")
    require(
        isinstance(execution, dict)
        and set(execution) == {"argv", "entry_digest", "freeze_digest", "kind"}
        and execution["kind"] in kinds
        and execution["entry_digest"] == entry_hash
        and execution["freeze_digest"] == FREEZE,
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
        # exact recorded CPython 3.12 runtime, and its literal scope statement.
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
            and compatibility["runtime"] == RUNTIME,
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
        # The observations belong to the candidate this pinned launch names; bind its bytes.
        require(
            command.count("--candidate") == 1 and command.index("--candidate") + 1 < len(command),
            "replay launch record names no single candidate",
        )
        candidate = safe_file(source, command[command.index("--candidate") + 1])
        require(
            tree_digest(candidate) == CANDIDATES.get(case),
            "replayed candidate differs from the pinned historical candidate",
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
            # The frozen evaluator (digest-bound in the template) returns exactly these
            # fields, so any other top-level field cannot come from it.
            module, function = target.split(":")
            require(
                isinstance(value, dict)
                and set(value)
                == returned_fields(template.files[module.replace(".", "/") + ".py"], function),
                "observer output has fields the frozen evaluator does not return",
            )
            # Lists the evaluator fills with one helper's records (observe() builds
            # observations and setup_observations from _call) carry only that helper's fields.
            # Each list holds one record per item it iterates over (the runner calls the
            # function with **arguments), and a len()-sum field counts exactly those records.
            module_source = template.files[module.replace(".", "/") + ".py"]
            # Literal, comparison, len() and sorted() return values are fixed by the source.
            check_returned_values(value, module_source, function)
            check_measure_domain(value, module_source, function)
            lists, counts, defaults = returned_call_lists(module_source, function)
            bound = {**defaults, **arguments}
            for key, (callee, iterable) in lists.items():
                shape = returned_fields(module_source, callee)
                require(
                    isinstance(value[key], list)
                    and all(isinstance(item, dict) and set(item) == shape for item in value[key]),
                    f"observer {key} records have fields {callee} does not return",
                )
                items = iterated(iterable, bound)
                require(
                    isinstance(items, list) and len(value[key]) == len(items),
                    f"observer {key} has a record count its arguments cannot produce",
                )
            for key, summed in counts.items():
                require(
                    type(value[key]) is int
                    and value[key] == sum(len(value[name]) for name in summed),
                    f"observer {key} differs from the records it counts",
                )
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
