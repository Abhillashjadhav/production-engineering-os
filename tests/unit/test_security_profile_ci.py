from __future__ import annotations

import fcntl
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import pmpe.privacy.retention as retention_module
from pmpe.contracts.digest import canonical_digest
from pmpe.engineering.ledger import EvidenceLedger
from pmpe.orchestration.lifecycle import BudgetPolicy, LifecycleControlPlane, LifecycleState
from pmpe.orchestration.state import RunState
from pmpe.privacy.retention import (
    RetentionController,
    purge_retained_runs,
    retention_policy_digest,
    run_state_retention_digest,
    terminal_retention_digest,
)
from pmpe.telemetry.events import EventLog
from scripts.ci.evaluate_security_profile import (
    _dependency_inventory,
    _file_digest,
    _observed_architecture_edges,
    _privacy_evidence_from_artifact,
    _reviewed_policy_config,
)
from scripts.ci.verify_privacy_controls import (
    _finalize_probe,
    _inventory_telemetry_fields,
    _prepare_probe,
    _probe_candidate_runtime,
    _supervise_candidate_runtime,
    _verify,
)

SHA = "d" * 40


def _write_authenticated_lifecycle_run(
    run_dir: Path,
    *,
    target: str,
    retention_days: int = 30,
    completed_at: datetime | None = None,
) -> Path:
    run_dir.mkdir(parents=True)
    completion_time = completed_at or datetime(2030, 1, 1, tzinfo=UTC)
    observed_at = completion_time.isoformat()
    metadata = {"retention_days": retention_days}
    (run_dir / "lifecycle-metadata.json").write_text(json.dumps(metadata))
    initial = {
        "evidence_refs": {"metadata_digest": canonical_digest(metadata)},
        "kind": "STATE_CREATED",
        "observed_at": observed_at,
        "previous_digest": "",
        "sequence": 1,
        "target": "CONTRACT_RECEIVED",
    }
    initial["event_digest"] = canonical_digest(initial)
    events = [initial]
    if target != "CONTRACT_RECEIVED":
        terminal = {
            "evidence_refs": {},
            "kind": "COMPLETION_CLAIMED" if target == "COMPLETED" else "TRANSITION",
            "observed_at": observed_at,
            "outcome": "APPLIED",
            "previous_digest": initial["event_digest"],
            "sequence": 2,
            "target": target,
        }
        terminal["event_digest"] = canonical_digest(terminal)
        events.append(terminal)
    ledger = run_dir / "lifecycle-events.jsonl"
    ledger.write_text("".join(json.dumps(event) + "\n" for event in events))
    return ledger


def _write_authenticated_engineering_run(
    run_dir: Path,
    *,
    stage: str = "complete",
    retention_days: int = 30,
    completed_at: datetime | None = None,
) -> Path:
    run_dir.mkdir(parents=True)
    run_id = f"eng-{run_dir.name}"
    state = run_dir / "run-state.json"
    state.write_text(
        json.dumps(
            {
                "retention_days": retention_days,
                "run_id": run_id,
                "stage": stage,
            }
        )
    )
    ledger = EvidenceLedger(run_dir, run_id=run_id)
    ledger.record(
        stage="contract_lock",
        agent="core",
        action="lock",
        output_digests={"retention_policy": retention_policy_digest(retention_days)},
    )
    if stage == "complete":
        ledger.record(
            stage="release_report",
            agent="core",
            action="report",
            output_digests={
                "terminal_retention": terminal_retention_digest(
                    retention_days,
                    stage="complete",
                )
            },
        )
        events_path = run_dir / "ledger.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        terminal = events[-1]
        terminal["ts"] = (completed_at or datetime(2030, 1, 1, tzinfo=UTC)).isoformat()
        identity = {key: value for key, value in terminal.items() if key not in {"event_id", "ts"}}
        terminal["event_id"] = canonical_digest(
            identity if terminal["idempotency_key"] else {**identity, "ts": terminal["ts"]}
        )
        events_path.write_text("".join(json.dumps(event) + "\n" for event in events))
    return state


def _write_authenticated_run_state(
    run_dir: Path,
    *,
    outcome: str = "success",
    retention_days: int = 30,
    completed_at: datetime | None = None,
) -> Path:
    run_dir.mkdir(parents=True)
    state = RunState.new(
        run_id=run_dir.name,
        run_dir=run_dir,
        spec_digest="sha256:" + "1" * 64,
        retention_days=retention_days,
    )
    state.outcome = outcome
    state.completed_at = (completed_at or datetime(2030, 1, 1, tzinfo=UTC)).isoformat()
    state.save()
    return run_dir / "state.json"


def test_architecture_observer_resolves_relative_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "worker.py").write_text("from ..guided import api\n")

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_resolves_names_imported_from_a_package(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "worker.py").write_text("from pmpe import guided\n")

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_checks_both_repository_planes(tmp_path: Path) -> None:
    os_source = tmp_path / "src" / "pmpe" / "orchestration"
    product_source = tmp_path / "products" / "pm-evals-web" / "backend" / "src" / "pm_evals_reports"
    os_source.mkdir(parents=True)
    product_source.mkdir(parents=True)
    (product_source / "__init__.py").write_text("")
    (os_source / "worker.py").write_text("import pm_evals_reports\n")
    (product_source / "app.py").write_text("from pmpe.contracts import digest\n")

    edges = _observed_architecture_edges(tmp_path)

    assert ("orchestration", "product") in edges
    assert ("product", "core") in edges


def test_architecture_observer_discovers_product_namespace_packages(tmp_path: Path) -> None:
    os_source = tmp_path / "src" / "pmpe" / "orchestration"
    product_source = tmp_path / "products" / "pm-evals-web" / "backend" / "src" / "pm_evals_reports"
    os_source.mkdir(parents=True)
    product_source.mkdir(parents=True)
    (os_source / "worker.py").write_text("import pm_evals_reports.summary\n")
    (product_source / "summary.py").write_text("REPORT = {}\n")

    assert ("orchestration", "product") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_accounts_for_dynamic_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "literal.py").write_text(
        'import importlib\nimportlib.import_module("pmpe.guided.api")\n'
    )
    (source / "unresolved.py").write_text(
        "import importlib\nimportlib.import_module(module_name)\n"
    )

    edges = _observed_architecture_edges(tmp_path)

    assert ("orchestration", "interfaces") in edges
    assert ("orchestration", "unresolved_dynamic") in edges


def test_architecture_observer_does_not_escape_a_resolved_import_result(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "resolved_result.py").write_text(
        "import importlib\n"
        "def inspect(value):\n    return value\n"
        'inspect(importlib.import_module("pmpe.guided.api"))\n'
    )

    edges = _observed_architecture_edges(tmp_path)

    assert ("orchestration", "interfaces") in edges
    assert ("orchestration", "unresolved_dynamic") not in edges


@pytest.mark.parametrize(
    "source_text",
    [
        'import importlib as il\nil.import_module("pmpe.guided.api")\n',
        'from importlib import import_module as load\nload("pmpe.guided.api")\n',
        'import importlib\nloader = importlib.import_module\nloader("pmpe.guided.api")\n',
        'import importlib\nil = importlib\nil.import_module("pmpe.guided.api")\n',
        'import importlib\nil = importlib\nil2 = il\nil2.import_module("pmpe.guided.api")\n',
        'from importlib import import_module\nloader = import_module\nloader("pmpe.guided.api")\n',
        'import builtins\nbuiltins.__import__("pmpe.guided.api")\n',
        'import builtins as bi\nbi.__import__("pmpe.guided.api")\n',
        'from builtins import __import__ as load\nload("pmpe.guided.api")\n',
    ],
)
def test_architecture_observer_resolves_dynamic_import_function_aliases(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "dynamic_alias.py").write_text(source_text)

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


@pytest.mark.parametrize(
    "source_text",
    [
        "import importlib\nloaders = [importlib.import_module]\nloaders[0](module_name)\n",
        "from importlib import import_module\nloaders = {'load': import_module}\n",
        "import importlib\nholder.loader = importlib.import_module\n",
    ],
)
def test_architecture_observer_fails_closed_when_loader_escapes_simple_aliases(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "escaped_loader.py").write_text(source_text)

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_resolves_relative_dynamic_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "relative.py").write_text(
        'import importlib\nimportlib.import_module("..guided.api", __package__)\n'
    )

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_resolves_relative_builtins_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "relative.py").write_text('__import__("guided.api", globals(), locals(), (), 2)\n')

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_resolves_literal_builtins_fromlist(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "fromlist.py").write_text('__import__("pmpe", globals(), locals(), ("guided",), 0)\n')

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_fails_closed_on_dynamic_builtins_fromlist(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "fromlist.py").write_text(
        '__import__("pmpe", globals(), locals(), requested_names, 0)\n'
    )

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


@pytest.mark.parametrize(
    "source_text",
    [
        "from importlib import import_module\n"
        'def load(import_module):\n    import_module("pmpe.guided.api")\n',
        'import importlib\ndef load(importlib):\n    importlib.import_module("pmpe.guided.api")\n',
        'def load(__import__):\n    __import__("pmpe.guided.api")\n',
        "import importlib\n"
        "def bind():\n    loader = importlib.import_module\n"
        'def load(loader):\n    loader("pmpe.guided.api")\n',
    ],
)
def test_architecture_observer_respects_lexically_shadowed_loader_names(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "shadowed.py").write_text(source_text)

    edges = _observed_architecture_edges(tmp_path)

    assert ("orchestration", "interfaces") not in edges
    assert ("orchestration", "unresolved_dynamic") not in edges


def test_architecture_observer_fails_closed_on_unknown_builtins_import_level(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "relative.py").write_text(
        '__import__("guided.api", globals(), locals(), (), level)\n'
    )

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


@pytest.mark.parametrize(
    "source_text",
    [
        'import importlib\ngetattr(importlib, "import_module")("pmpe.guided.api")\n',
        'import importlib\nloader = getattr(importlib, "import_module")\n'
        'loader("pmpe.guided.api")\n',
    ],
)
def test_architecture_observer_resolves_reflective_dynamic_loaders(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "reflective.py").write_text(source_text)

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_fails_closed_on_unknown_reflective_importlib_access(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "reflective.py").write_text(
        "import importlib\ngetattr(importlib, attribute_name)(module_name)\n"
    )

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


@pytest.mark.parametrize(
    "source_text",
    [
        'import importlib\nvars(importlib)["import_module"]("pmpe.guided.api")\n',
        'import importlib\nimportlib.__dict__["import_module"]("pmpe.guided.api")\n',
        'import builtins\nvars(builtins)["__import__"]("pmpe.guided.api")\n',
        'import builtins\nbuiltins.__dict__["__import__"]("pmpe.guided.api")\n',
        '__builtins__["__import__"]("pmpe.guided.api")\n',
        '__builtins__.get("__import__")("pmpe.guided.api")\n',
        '__builtins__.__getitem__("__import__")("pmpe.guided.api")\n',
        'globals()["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        'globals().copy()["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        'dict(globals())["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        '{**globals()}["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        'globals().setdefault("__builtins__")["__import__"]("pmpe.guided.api")\n',
        'dict(globals().items())["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        "namespace = dict(zip(globals().keys(), globals().values()))\n"
        'namespace["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        "def identity(value):\n    return value\n"
        'identity(globals())["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        "def recover():\n    return globals()\n"
        'recover()["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        "def recover():\n    return lambda: globals()\n"
        'recover()()["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        "def recover():\n"
        "    def nested(namespace=globals()):\n        return namespace\n"
        "    return nested\n"
        'recover()()["__builtins__"]["__import__"]("pmpe.guided.api")\n',
        'globals().get("__" + "builtins__")["__import__"]("pmpe.guided.api")\n',
        'namespace = globals()\nkey = "__builtins__"\n'
        'namespace[key]["__import__"]("pmpe.guided.api")\n',
        'getter = globals().get\ngetter("__builtins__")["__import__"]("pmpe.guided.api")\n',
    ],
)
def test_architecture_observer_fails_closed_on_module_dictionary_loaders(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "dictionary_loader.py").write_text(source_text)

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


@pytest.mark.parametrize(
    "source_text",
    [
        'import sys\nsys.modules["builtins"].__import__("pmpe.guided.api")\n',
        'import sys\nsys.modules.copy()["builtins"].__import__("pmpe.guided.api")\n',
        "import sys as runtime\nmods = runtime.modules\n"
        'mods.get("builtins").__import__("pmpe.guided.api")\n',
        "import sys\nmods = sys.modules.copy()\nmodule = mods['builtins']\n"
        'module.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['builtins']\nwrapped = (module,)[0]\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['builtins']\n"
        'vars(module)["__import__"]("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['builtins']\nnamespace = vars(module)\n"
        'namespace["__import__"]("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['builtins']\nnamespace = vars(module)\n"
        "wrapped = (namespace,)[0]\n"
        'wrapped["__import__"]("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['builtins']\n"
        'module.__getattribute__("__import__")("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['importlib']\n"
        'module.__getattribute__("import_module")("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name)\n"
        'module.__getattribute__(loader_name)("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['importlib']\n"
        "loader = module.__dict__.get(loader_name)\n"
        'loader("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['importlib']\nnamespace = module.__dict__\n"
        "loader = namespace.get(loader_name)\n"
        'loader("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['builtins']\n"
        "wrapped = module if flag else object()\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        "import sys\ndef identity(value):\n    return value\n"
        "module = sys.modules['builtins']\nwrapped = identity(module)\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['builtins']\n"
        "def recover():\n    return module\n"
        "wrapped = recover()\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['builtins']\n"
        "def recover(value=module):\n    return value\n"
        "wrapped = recover()\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules['builtins']\nleaked = None\n"
        "def recover():\n    global leaked\n    leaked = module\n"
        "recover()\n"
        'leaked.__import__("pmpe.guided.api")\n',
        'from sys import modules as mods\nmods["importlib"].import_module("pmpe.guided.api")\n',
        "from sys import modules as mods\nsnapshot = mods.copy()\n"
        'snapshot["importlib"].import_module("pmpe.guided.api")\n',
        'import sys\n{**sys.modules}["builtins"].__import__("pmpe.guided.api")\n',
        'import sys\ndict(sys.modules)["builtins"].__import__("pmpe.guided.api")\n',
        "import sys\nmods = {**sys.modules}\nmodule = mods['builtins']\n"
        'module.__import__("pmpe.guided.api")\n',
        "import sys\nmods = dict(sys.modules)\nmodule = mods['importlib']\n"
        'module.import_module("pmpe.guided.api")\n',
        "import sys\n(snapshot := dict(sys.modules))['builtins'].__import__(\"pmpe.guided.api\")\n",
        'import sys\nsys.modules.get(name).__import__("pmpe.guided.api")\n',
        'import sys\nmodule = sys.modules.get(name)\nmodule.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name)\nalias = module\n"
        'alias.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name)\nholder = [module]\n"
        'holder[0].__import__("pmpe.guided.api")\n',
        'import sys\n(module := sys.modules.get(name)).__import__("pmpe.guided.api")\n',
        'import sys\n(module := sys.modules.get(name))\nmodule.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name) if flag else object()\n"
        'module.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name)\n"
        'vars(module)["__import__"]("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name)\n"
        'module.__dict__["import_module"]("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name)\n"
        "loader = vars(module).get(loader_name)\n"
        'loader("pmpe.guided.api")\n',
        "import sys\ndef identity(value):\n    return value\n"
        "module = sys.modules.get(name)\nwrapped = identity(module)\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        "import sys\ndef identity(value):\n    return value\n"
        "module = sys.modules.get(name)\nwrapped = identity(*(module,))\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name)\n"
        "wrapped = next(item for item in (module,))\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name)\n"
        "wrapped = (lambda: module)()\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        "import sys\nmodule = sys.modules.get(name)\n"
        "def recover():\n    return module\n"
        "wrapped = recover()\n"
        'wrapped.__import__("pmpe.guided.api")\n',
        'import sys\nmodule = sys.modules[name]\nmodule.import_module("pmpe.guided.api")\n',
        "import sys\ndef id(registry):\n    return registry['builtins']\n"
        'id(sys.modules).__import__("pmpe.guided.api")\n',
        "import sys\ntype = lambda registry: registry['importlib']\n"
        'type(sys.modules).import_module("pmpe.guided.api")\n',
        "import sys\nclass Leak:\n"
        "    def __getitem__(self, registry):\n"
        "        return registry['builtins']\n"
        'Leak()[sys.modules].__import__("pmpe.guided.api")\n',
    ],
)
def test_architecture_observer_fails_closed_on_sys_modules_import_authority(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "sys_modules_loader.py").write_text(source_text)

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


@pytest.mark.parametrize(
    "operation",
    [
        "sys.modules.items()",
        "sys.modules.get",
        "sys.modules.copy",
        "list(sys.modules)",
        "consume(sys.modules)",
        "sys.modules | {}",
        "sys.modules if condition else {}",
        "(lambda: sys.modules)",
        "sys.modules()",
    ],
)
def test_architecture_observer_fails_closed_on_unmodeled_sys_modules_operation(
    tmp_path: Path,
    operation: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "sys_modules_operation.py").write_text(f"import sys\nregistry_view = {operation}\n")

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_allows_sys_modules_identity_and_dynamic_lookup(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "sys_modules_inspection.py").write_text(
        "import sys\n"
        "registry = sys.modules\n"
        "identity = id(registry)\n"
        "registry_type = type(registry)\n"
        "module = registry.get(module_name)\n"
        "module_type = type(module)\n"
        "namespace = vars(module)\n"
        "module_name_value = namespace.get('__name__')\n"
        "def inspect(module_name):\n"
        "    nested = sys.modules\n"
        "    inspected = nested.get(module_name)\n"
        "    return id(nested), type(nested), type(inspected)\n"
    )

    assert ("orchestration", "unresolved_dynamic") not in _observed_architecture_edges(tmp_path)


@pytest.mark.parametrize(
    "source_text",
    [
        'import importlib\nget = getattr\nget(importlib, "import_module")("pmpe.guided.api")\n',
        'import builtins\nget = getattr\nget(builtins, "__import__")("pmpe.guided.api")\n',
        "import importlib\ninspect = vars\ninspect(importlib)\n",
        'import importlib\nget = getattr\nget(*(importlib, "import_module"))("pmpe.guided.api")\n',
        'import importlib\nget = getattr\nget([importlib][0], "import_module")('
        '"pmpe.guided.api")\n',
        'import builtins\nget = getattr\nget(**{"object": builtins, "name": "__import__"})('
        '"pmpe.guided.api")\n',
    ],
)
def test_architecture_observer_fails_closed_on_aliased_module_reflection(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "aliased_reflection.py").write_text(source_text)

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


@pytest.mark.parametrize(
    "source_text",
    [
        "import importlib\nclass Loaders:\n    load = importlib.import_module\n"
        'Loaders.load("pmpe.guided.api")\n',
        "class Loaders:\n    import importlib\n"
        'Loaders.importlib.import_module("pmpe.guided.api")\n',
    ],
)
def test_architecture_observer_rejects_class_bound_import_authority(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "class_loader.py").write_text(source_text)

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


@pytest.mark.parametrize(
    "source_text",
    [
        "import importlib\nclass Loaders:\n"
        "    @staticmethod\n"
        "    def load(name, loader=importlib.import_module):\n"
        "        return loader(name)\n"
        'Loaders.load("pmpe.guided.api")\n',
        "from builtins import __import__ as load\nclass Loaders:\n"
        "    def resolve(self, name, *, loader=load):\n"
        "        return loader(name)\n",
        "import importlib\nclass Loaders:\n"
        "    def resolve(self, name, loaders=(importlib.import_module,)):\n"
        "        return loaders[0](name)\n",
    ],
)
def test_architecture_observer_rejects_import_authority_in_method_defaults(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "method_default.py").write_text(source_text)

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_uses_parent_binding_for_function_default_import(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "shadowed_default.py").write_text(
        "import importlib\n"
        "def load(value=importlib.import_module('pmpe.guided.api'), importlib=None):\n"
        "    return value\n"
    )

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_rejects_loader_captured_by_lambda_default(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "lambda_default.py").write_text(
        "import importlib\n"
        "def factory():\n"
        "    return lambda name, loader=importlib.import_module: loader(name)\n"
    )

    assert ("orchestration", "unresolved_dynamic") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_uses_parent_binding_for_class_base_import(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "class_base.py").write_text(
        "import importlib\n"
        "class Loaded(importlib.import_module('pmpe.guided.api').Base):\n"
        "    importlib = None\n"
    )

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_resolves_global_loader_from_module_scope(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "global_loader.py").write_text(
        "import importlib\n"
        "def outer(importlib):\n"
        "    def inner():\n"
        "        global importlib\n"
        "        return importlib.import_module('pmpe.guided.api')\n"
        "    return inner\n"
    )

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_dynamic_import_exception_binds_the_complete_target_file(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "evidence"
    source.mkdir(parents=True)
    module = source / "__init__.py"
    module.write_text(
        "from importlib import import_module\n"
        '_EXPORT_MODULES = {"Gate": "pmpe.evidence.gate"}\n'
        "def load(name):\n"
        "    module_name = _EXPORT_MODULES[name]\n"
        "    return import_module(module_name)\n"
    )
    call_line = module.read_text().splitlines()[4]
    allowlist = (
        (
            "src/pmpe/evidence/__init__.py",
            5,
            canonical_digest({"source_line": call_line}),
            _file_digest(module),
        ),
    )

    assert ("verification", "unresolved_dynamic") not in _observed_architecture_edges(
        tmp_path, dynamic_import_allowlist=allowlist
    )

    module.write_text(module.read_text().replace("pmpe.evidence.gate", "pmpe.guided.api"))

    assert ("verification", "unresolved_dynamic") in _observed_architecture_edges(
        tmp_path, dynamic_import_allowlist=allowlist
    )


def test_retention_controller_atomically_deletes_only_expired_completed_runs(
    tmp_path: Path,
) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    completed = tmp_path / "completed-run"
    active = tmp_path / "active-run"
    completed_ledger = _write_authenticated_lifecycle_run(completed, target="COMPLETED")
    completed_artifact = completed / "recent-artifact.json"
    active_ledger = _write_authenticated_lifecycle_run(
        active,
        target="IMPLEMENTATION_IN_PROGRESS",
    )
    active_artifact = active / "old-artifact.json"
    completed_artifact.write_text("recent but owned by an expired completed run")
    active_artifact.write_text("old but owned by an active run")
    old = (now - timedelta(days=31)).timestamp()
    recent = (now - timedelta(days=29)).timestamp()
    os.utime(completed_ledger, (old, old))
    os.utime(completed_artifact, (recent, recent))
    os.utime(active_ledger, (old, old))
    os.utime(active_artifact, (old, old))

    result = RetentionController().purge(tmp_path, now=now)

    assert result.deleted == ("completed-run",)
    assert result.retained == ("active-run",)
    assert not completed.exists()
    assert active_ledger.exists()
    assert active_artifact.exists()


def test_retention_controller_preserves_a_locked_completed_run(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    completed = tmp_path / "completed-run"
    ledger = _write_authenticated_lifecycle_run(completed, target="COMPLETED")
    old = (now - timedelta(days=31)).timestamp()
    os.utime(ledger, (old, old))

    with (completed / "lifecycle.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = RetentionController().purge(tmp_path, now=now)

    assert result.deleted == ()
    assert result.retained == ("completed-run",)
    assert ledger.exists()


def test_retention_controller_deletes_expired_completed_engineering_runs(
    tmp_path: Path,
) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    completed = tmp_path / "completed-engineering-run"
    state = _write_authenticated_engineering_run(completed)
    (completed / "artifact.json").write_text("belongs to the completed run")
    old = (now - timedelta(days=31)).timestamp()
    os.utime(state, (old, old))

    result = RetentionController().purge(tmp_path, now=now)

    assert result.deleted == ("completed-engineering-run",)
    assert not completed.exists()


def test_retention_controller_deletes_expired_completed_run_states(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    completed = tmp_path / "completed-run-state"
    marker = _write_authenticated_run_state(completed)
    (completed / "artifact.json").write_text("belongs to the completed run")
    old = (now - timedelta(days=31)).timestamp()
    os.utime(marker, (old, old))

    result = RetentionController().purge(tmp_path, now=now)

    assert result.deleted == ("completed-run-state",)
    assert not completed.exists()


def test_retention_controller_rejects_tampered_run_state_policy(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    run_dir = tmp_path / "tampered-run-state"
    marker = _write_authenticated_run_state(run_dir)
    state = json.loads(marker.read_text())
    state["retention_days"] = 3650
    marker.write_text(json.dumps(state))

    result = RetentionController().purge(tmp_path, now=now)

    assert result.deleted == ()
    assert result.retained == (run_dir.name,)
    assert run_dir.exists()


def test_retention_policy_rejects_overflowing_duration() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        retention_policy_digest(1_000_000)


@pytest.mark.parametrize(
    ("outcome", "terminal_status"),
    [
        ("success", "done"),
        ("no_merge", "done"),
        ("blocked", "blocked"),
        ("failed", "failed"),
    ],
)
def test_retention_controller_migrates_pre_retention_completed_run_state(
    tmp_path: Path,
    outcome: str,
    terminal_status: str,
) -> None:
    completed_at = datetime(2030, 1, 1, tzinfo=UTC)
    run_dir = tmp_path / f"legacy-{outcome}-run"
    state_path = _write_authenticated_run_state(
        run_dir,
        outcome=outcome,
        completed_at=completed_at,
    )
    state = json.loads(state_path.read_text())
    for field in (
        "completed_at",
        "retention_days",
        "retention_policy_digest",
        "retention_record_digest",
    ):
        state.pop(field)
    terminal_steps = (
        state["steps"].values()
        if outcome in {"no_merge", "success"}
        else (next(iter(state["steps"].values())),)
    )
    for step in terminal_steps:
        step.update(
            {
                "finished_at": completed_at.isoformat(),
                "started_at": completed_at.isoformat(),
                "status": terminal_status,
            }
        )
    state_path.write_text(json.dumps(state))

    retained = RetentionController().purge(
        tmp_path,
        now=completed_at + timedelta(days=29),
    )

    assert retained.retained == (run_dir.name,)
    migrated = json.loads(state_path.read_text())
    assert migrated["retention_days"] == 30
    assert migrated["completed_at"] == completed_at.isoformat()
    assert migrated["retention_policy_digest"] == retention_policy_digest(30)
    assert migrated["retention_record_digest"] == run_state_retention_digest(
        run_id=state["run_id"],
        spec_digest=state["spec_digest"],
        created_at=state["created_at"],
        outcome=state["outcome"],
        completed_at=completed_at.isoformat(),
        retention_days=30,
    )

    deleted = RetentionController().purge(
        tmp_path,
        now=completed_at + timedelta(days=31),
    )

    assert deleted.deleted == (run_dir.name,)
    assert not run_dir.exists()


def test_retention_controller_rejects_legacy_run_without_terminal_step_time(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "legacy-unbound-run"
    state_path = _write_authenticated_run_state(run_dir)
    state = json.loads(state_path.read_text())
    for field in (
        "completed_at",
        "retention_days",
        "retention_policy_digest",
        "retention_record_digest",
    ):
        state.pop(field)
    state_path.write_text(json.dumps(state))

    result = RetentionController().purge(
        tmp_path,
        now=datetime(2031, 1, 1, tzinfo=UTC),
    )

    assert result.deleted == ()
    assert result.retained == (run_dir.name,)
    assert not {
        "completed_at",
        "retention_days",
        "retention_policy_digest",
        "retention_record_digest",
    }.intersection(json.loads(state_path.read_text()))


@pytest.mark.parametrize("run_kind", ["lifecycle", "engineering"])
def test_retention_controller_uses_authenticated_completion_time_not_marker_mtime(
    tmp_path: Path,
    run_kind: str,
) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    expired = tmp_path / f"expired-{run_kind}"
    recent = tmp_path / f"recent-{run_kind}"
    if run_kind == "lifecycle":
        expired_marker = _write_authenticated_lifecycle_run(
            expired,
            target="COMPLETED",
            completed_at=now - timedelta(days=31),
        )
        recent_marker = _write_authenticated_lifecycle_run(
            recent,
            target="COMPLETED",
            completed_at=now - timedelta(days=29),
        )
    else:
        expired_marker = _write_authenticated_engineering_run(
            expired,
            completed_at=now - timedelta(days=31),
        )
        recent_marker = _write_authenticated_engineering_run(
            recent,
            completed_at=now - timedelta(days=29),
        )
    fresh_mtime = now.timestamp()
    old_mtime = (now - timedelta(days=500)).timestamp()
    os.utime(expired_marker, (fresh_mtime, fresh_mtime))
    os.utime(recent_marker, (old_mtime, old_mtime))

    result = RetentionController().purge(tmp_path, now=now)

    assert result.deleted == (f"expired-{run_kind}",)
    assert result.retained == (f"recent-{run_kind}",)
    assert not expired.exists()
    assert recent.exists()


def test_retention_controller_uses_each_runs_immutable_policy(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    short = tmp_path / "short-policy"
    long = tmp_path / "long-policy"
    for run_dir, retention_days in ((short, 30), (long, 365)):
        ledger = _write_authenticated_lifecycle_run(
            run_dir,
            target="COMPLETED",
            retention_days=retention_days,
        )
        old = (now - timedelta(days=31)).timestamp()
        os.utime(ledger, (old, old))

    result = purge_retained_runs(tmp_path, trusted_clock=lambda: now)

    assert result.deleted == ("short-policy",)
    assert result.retained == ("long-policy",)
    assert not short.exists()
    assert long.exists()


def test_retention_controller_fails_closed_on_malformed_bound_policy(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    run_dir = tmp_path / "tampered-policy"
    ledger = _write_authenticated_lifecycle_run(run_dir, target="COMPLETED")
    (run_dir / "lifecycle-metadata.json").write_text('{"retention_days":false}\n')
    old = (now - timedelta(days=500)).timestamp()
    os.utime(ledger, (old, old))

    result = purge_retained_runs(tmp_path, trusted_clock=lambda: now)

    assert result.deleted == ()
    assert result.retained == ("tampered-policy",)
    assert run_dir.exists()


def test_retention_controller_rejects_a_denied_completion_target(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    run_dir = tmp_path / "denied-completion"
    ledger = _write_authenticated_lifecycle_run(run_dir, target="COMPLETED")
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    denied = events[-1]
    denied["kind"] = "TRANSITION"
    denied["outcome"] = "DENIED"
    denied.pop("event_digest")
    denied["event_digest"] = canonical_digest(denied)
    ledger.write_text("".join(json.dumps(event) + "\n" for event in events))
    old = (now - timedelta(days=31)).timestamp()
    os.utime(ledger, (old, old))

    result = purge_retained_runs(tmp_path, trusted_clock=lambda: now)

    assert result.deleted == ()
    assert result.retained == (run_dir.name,)
    assert run_dir.exists()


@pytest.mark.parametrize("run_kind", ["lifecycle", "engineering"])
def test_retention_controller_rejects_valid_but_unauthenticated_policy_mutation(
    tmp_path: Path,
    run_kind: str,
) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    run_dir = tmp_path / f"tampered-{run_kind}"
    if run_kind == "lifecycle":
        marker = _write_authenticated_lifecycle_run(run_dir, target="COMPLETED")
        policy_path = run_dir / "lifecycle-metadata.json"
    else:
        marker = _write_authenticated_engineering_run(run_dir)
        policy_path = marker
    policy = json.loads(policy_path.read_text())
    policy["retention_days"] = 3650
    policy_path.write_text(json.dumps(policy))
    old = (now - timedelta(days=31)).timestamp()
    os.utime(marker, (old, old))

    result = purge_retained_runs(tmp_path, trusted_clock=lambda: now)

    assert result.deleted == ()
    assert result.retained == (run_dir.name,)
    assert run_dir.exists()


def test_retention_controller_never_deletes_the_requested_active_run(
    tmp_path: Path,
) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    requested = tmp_path / "requested-run"
    requested.mkdir()
    state = requested / "run-state.json"
    state.write_text('{"stage":"complete"}\n')
    old = (now - timedelta(days=31)).timestamp()
    os.utime(state, (old, old))

    result = RetentionController().purge(
        tmp_path,
        now=now,
        exclude_run_dir=requested,
    )

    assert result.deleted == ()
    assert result.retained == ("requested-run",)
    assert state.exists()


def test_retention_controller_tolerates_a_concurrently_removed_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tombstone = tmp_path / ".retention-delete-expired-raced"
    tombstone.mkdir()
    real_rmtree = retention_module.shutil.rmtree

    def raced_rmtree(path: Path) -> None:
        real_rmtree(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(retention_module.shutil, "rmtree", raced_rmtree)

    result = RetentionController().purge(
        tmp_path,
        now=datetime(2030, 1, 31, tzinfo=UTC),
    )

    assert result.deleted == ()
    assert result.retained == ()


def test_event_log_enforces_retention_on_the_actual_runs_root(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    expired = tmp_path / "expired-run" / "lifecycle-events.jsonl"
    current_run = tmp_path / "current-run"
    expired = _write_authenticated_lifecycle_run(expired.parent, target="COMPLETED")
    old = (now - timedelta(days=31)).timestamp()
    os.utime(expired, (old, old))

    EventLog(
        current_run,
        retention_days=30,
        trusted_clock=lambda: now,
    )

    assert not expired.exists()


def test_production_retention_entrypoints_reserve_the_tombstone_namespace(
    tmp_path: Path,
) -> None:
    reserved = tmp_path / ".retention-delete-active-run"

    with pytest.raises(ValueError, match="reserved retention tombstone prefix"):
        EventLog(reserved, retention_days=30)

    budget = BudgetPolicy(
        version="budget-v1",
        limits={
            "tokens": 100,
            "credits": 10,
            "elapsed_seconds": 3600,
            "external_compute_seconds": 600,
            "spend_microunits": 1000,
        },
        repair_attempts_per_finding=2,
        repair_attempts_per_stage=3,
        reserved_safety_units=10,
        approved_by="delivery-owner",
    )
    with pytest.raises(ValueError, match="reserved retention tombstone prefix"):
        LifecycleControlPlane.create(
            reserved,
            run_id="reserved-run",
            subject_digest="sha256:" + "1" * 64,
            initial_state=LifecycleState.CONTRACT_RECEIVED,
            budget_policy=budget,
        )


def test_phase_zero_create_enforces_retention_on_shipped_lifecycle_root(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    expired = tmp_path / "expired-run" / "lifecycle-events.jsonl"
    expired = _write_authenticated_lifecycle_run(expired.parent, target="COMPLETED")
    old = (now - timedelta(days=31)).timestamp()
    os.utime(expired, (old, old))
    budget = BudgetPolicy(
        version="budget-v1",
        limits={
            "tokens": 100,
            "credits": 10,
            "elapsed_seconds": 3600,
            "external_compute_seconds": 600,
            "spend_microunits": 1000,
        },
        repair_attempts_per_finding=2,
        repair_attempts_per_stage=3,
        reserved_safety_units=10,
        approved_by="delivery-owner",
    )

    LifecycleControlPlane.create(
        tmp_path / "current-run",
        run_id="privacy-retention-run",
        subject_digest="sha256:" + "1" * 64,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=budget,
        retention_days=30,
        trusted_clock=lambda: now,
    )

    assert not expired.exists()


def test_privacy_verifier_inventories_real_product_telemetry(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        'events.emit("escalation", escalation_id="E", step="build", reason="policy")\n'
    )

    assert _inventory_telemetry_fields(tmp_path) == (
        "escalation_id",
        "reason",
        "step",
    )


def test_privacy_verifier_inventories_product_backend_telemetry(tmp_path: Path) -> None:
    source = tmp_path / "products" / "pm-evals-web" / "backend" / "src" / "pm_evals_reports"
    source.mkdir(parents=True)
    (source / "events.py").write_text(
        'ctx.events.emit("report", email="synthetic@example.invalid")\n'
    )

    assert _inventory_telemetry_fields(tmp_path) == ("email",)


def test_privacy_verifier_tracks_aliased_event_emitters(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        'emit = ctx.events.emit\nemit("result", email="synthetic@example.invalid")\n'
    )

    assert _inventory_telemetry_fields(tmp_path) == ("email",)


def test_privacy_verifier_tracks_attribute_aliased_event_emitters(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        'holder.send = ctx.events.emit\nholder.send("result", email="synthetic@example.invalid")\n'
    )

    assert _inventory_telemetry_fields(tmp_path) == ("email",)


def test_privacy_verifier_scopes_emitter_aliases_to_lexical_bindings(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        "def telemetry(ctx):\n"
        "    emit = ctx.events.emit\n"
        '    emit("result", run_id="run-1")\n\n'
        "def unrelated(emit):\n"
        '    emit("mail", email="not-telemetry")\n'
    )

    assert _inventory_telemetry_fields(tmp_path) == ("run_id",)


def test_privacy_verifier_uses_parent_emitter_binding_for_function_default(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        "emit = ctx.events.emit\n"
        "def record(value=emit('default', email='synthetic@example.invalid'), emit=None):\n"
        "    return value\n"
        "ctx.events.emit('direct', run_id='run-1')\n"
    )

    assert _inventory_telemetry_fields(tmp_path) == ("email", "run_id")


def test_privacy_verifier_does_not_treat_ordinary_events_values_as_emitters(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        "def telemetry(ctx):\n"
        '    ctx.events.emit("result", run_id="run-1")\n\n'
        "def read_records():\n"
        "    events = []\n"
        "    return events\n"
    )

    assert _inventory_telemetry_fields(tmp_path) == ("run_id",)


def test_privacy_verifier_fails_when_emitter_escapes_into_a_container(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        'emitters = [ctx.events.emit]\nemitters[0]("result", email="hidden")\n'
    )

    with pytest.raises(ValueError, match="emitter escapes"):
        _inventory_telemetry_fields(tmp_path)


def test_privacy_verifier_rejects_class_bound_emitter_alias(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        "class Reporters:\n"
        "    report = ctx.events.emit\n\n"
        "def telemetry(ctx):\n"
        '    ctx.events.emit("result", run_id="run-1")\n'
    )

    with pytest.raises(ValueError, match="class namespace"):
        _inventory_telemetry_fields(tmp_path)


@pytest.mark.parametrize(
    "source_text",
    [
        'getattr(ctx.events, "emit")("result", email="hidden")\n',
        'getattr(getattr(ctx, "events"), "emit")("result", secret_payload="hidden")\n',
        'getattr(getattr(runtime, "events"), "emit")("result", secret_payload="hidden")\n',
        'getattr(getattr(runtime, "events", None), "emit", fallback)('
        '"result", secret_payload="hidden")\n',
        'getattr(getattr(runtime, "ev" + "ents"), "em" + "it")('
        '"result", secret_payload="hidden")\n',
        "def telemetry(runtime, owner_name, method_name):\n"
        "    getattr(getattr(runtime, owner_name), method_name)("
        '"result", secret_payload="hidden")\n',
        'getattr(vars(ctx).get("events"), "emit")("result", secret_payload="hidden")\n',
        'ctx.__dict__.__getitem__("events").emit("result", secret_payload="hidden")\n',
        "namespace = vars(ctx)\ngetter = namespace.get\n"
        'getattr(getter("events"), "emit")('
        '"result", secret_payload="hidden")\n',
        'event_name = "events"\n'
        'getattr(vars(ctx).get(event_name), "emit")('
        '"result", secret_payload="hidden")\n',
        "def telemetry(ctx, event_name):\n"
        '    getattr(vars(ctx).get(event_name), "emit")('
        '"result", secret_payload="hidden")\n',
        "def telemetry(ctx, event_name):\n"
        "    namespace = vars(ctx)\n"
        "    emitter = namespace.get(event_name)\n"
        '    emitter("result", secret_payload="hidden")\n',
        "def identity(value):\n"
        "    return value\n\n"
        "def telemetry(ctx, owner_key, method_key, invoke):\n"
        "    namespace = vars(ctx)\n"
        "    wrapped = identity(namespace)\n"
        "    owner = wrapped.get(owner_key)\n"
        "    emitter = object.__getattribute__(owner, method_key)\n"
        "    invoke(emitter)\n",
        "def telemetry(ctx, owner_key, method_key, invoke):\n"
        "    namespace = vars(getattr(ctx, owner_key))\n"
        "    emitter = namespace.get(method_key)\n"
        "    invoke(emitter)\n",
        "def telemetry(ctx, owner_key, method_key, invoke):\n"
        "    owner = vars(ctx).get(owner_key)\n"
        "    emitter = object.__getattribute__(owner, method_key)\n"
        "    invoke(emitter)\n",
        "def telemetry(ctx, owner_key, method_key, invoke):\n"
        "    import operator\n"
        "    owner = vars(ctx).get(owner_key)\n"
        "    emitter = operator.attrgetter(method_key)(owner)\n"
        "    invoke(emitter)\n",
        'emit = getattr(ctx.events, "emit")\nemit("result", email="hidden")\n',
        'getattr(ctx.events, field_name)("result", email="hidden")\n',
        'vars(ctx.events)["emit"]("result", email="hidden")\n',
        'ctx.events.__dict__["emit"]("result", email="hidden")\n',
        'vars(ctx.events)[field_name]("result", email="hidden")\n',
        'get = getattr\nget(ctx.events, "emit")("result", email="hidden")\n',
        'inspect = vars\ninspect(ctx.events)["emit"]("result", email="hidden")\n',
        'get = getattr\nget(*(ctx.events, "emit"))("result", email="hidden")\n',
        'get = getattr\nget([ctx.events][0], "emit")("result", email="hidden")\n',
        'get = getattr\nget(**{"object": ctx.events, "name": "emit"})("result", email="hidden")\n',
        'owners = [ctx.events]\nowners[0].emit("result", email="hidden")\n',
        "namespace = vars(ctx)\nwrapped = (namespace,)[0]\n"
        "owner = wrapped.get(owner_key)\n"
        "emitter = object.__getattribute__(owner, method_key)\n"
        "emitter(secret_payload='hidden')\n",
        "object.__getattribute__(vars(ctx).setdefault('events'), 'emit')"
        "('result', secret_payload='hidden')\n",
        "owner = next(v for k, v in vars(ctx).items() if k == 'events')\n"
        "object.__getattribute__(owner, 'emit')('result', secret_payload='hidden')\n",
        "def recover(ctx):\n    return lambda: vars(ctx)\n"
        "namespace = recover(ctx)()\nowner = namespace.get('events')\n"
        "emitter = object.__getattribute__(owner, 'emit')\n"
        "emitter(secret_payload='hidden')\n",
        "def recover(ctx):\n"
        "    def nested(namespace=vars(ctx)):\n        return namespace\n"
        "    return nested\n"
        "namespace = recover(ctx)()\nowner = namespace.get('events')\n"
        "emitter = object.__getattribute__(owner, 'emit')\n"
        "emitter(secret_payload='hidden')\n",
        "reflect = (lambda value: value)(vars)\nnamespace = reflect(ctx)\n"
        "owner = namespace['events']\n"
        "emitter = object.__getattribute__(owner, 'emit')\n"
        "emitter(secret_payload='hidden')\n",
        "def telemetry(ctx):\n"
        "    import operator, sys\n"
        '    operator.attrgetter("emit")(sys._getframe().f_locals["ctx"].events)'
        '("result", secret_payload="hidden")\n',
    ],
)
def test_privacy_verifier_rejects_reflective_emitter_access(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(source_text)

    with pytest.raises(ValueError, match="reflective access"):
        _inventory_telemetry_fields(tmp_path)


def test_privacy_verifier_rejects_dynamic_event_key_in_isolated_scope(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "ordinary.py").write_text('ctx.events.emit("result", run_id="run-1")\n')
    (source / "reflective.py").write_text(
        'key = "events"\ngetattr(vars(ctx).get(key), "emit")("result", secret_payload="hidden")\n'
    )

    with pytest.raises(ValueError, match="reflective access"):
        _inventory_telemetry_fields(tmp_path)


def test_privacy_verifier_uses_trusted_policy_outside_candidate_root(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    source = candidate / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text('events.emit("result", email="synthetic@example.invalid")\n')
    candidate_policy = candidate / "security" / "security-profile-policy.json"
    candidate_policy.parent.mkdir()
    candidate_policy.write_text(
        json.dumps(
            {
                "privacy": {
                    "classification": "PUBLIC",
                    "retention_days": 3650,
                    "residency": None,
                    "telemetry_allowlist": ["secret"],
                }
            }
        )
    )
    trusted_policy = tmp_path / "protected-base" / "security-profile-policy.json"
    trusted_policy.parent.mkdir()
    trusted_policy.write_text(
        json.dumps(
            {
                "version": "repository-security-profile/v2",
                "privacy": {
                    "approved_by": "repository-security-owner",
                    "classification": "INTERNAL",
                    "deletion_required": True,
                    "expires_at": "2027-08-28T00:00:00Z",
                    "justification": "Reviewed test privacy intent.",
                    "retention_days": 30,
                    "residency": None,
                    "telemetry_allowlist": [
                        {
                            "approved_by": "repository-security-owner",
                            "expires_at": "2027-08-28T00:00:00Z",
                            "field": "email",
                            "justification": "Reviewed test telemetry field.",
                        }
                    ],
                },
            }
        )
    )

    evidence = _verify(SHA, trusted_policy, candidate)

    assert evidence["classification"] == "INTERNAL"
    assert evidence["retention_days"] == 30
    assert evidence["emitted_telemetry"] == ["email"]
    assert evidence["policy_file_digest"] == _file_digest(trusted_policy)


def test_candidate_privacy_probe_is_finalized_by_trusted_process(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    policy_path = root / "security" / "security-profile-policy.json"
    probe_root = tmp_path / "probe"
    challenge_path = tmp_path / "privacy-challenge.json"
    receipt_path = probe_root / "candidate-receipt.json"
    challenge = _prepare_probe(SHA, policy_path, root, probe_root)
    challenge_path.write_text(json.dumps(challenge))
    receipt = _probe_candidate_runtime(SHA, challenge_path, probe_root)
    receipt_path.write_text(json.dumps(receipt))

    evidence = _finalize_probe(
        SHA,
        policy_path,
        root,
        challenge_path,
        probe_root,
        receipt_path,
    )

    assert evidence["deletion_test_passed"] is True
    assert evidence["retention_test_passed"] is True
    assert evidence["telemetry_test_passed"] is True


def test_candidate_privacy_effects_are_attested_by_an_external_supervisor(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    policy_path = root / "security" / "security-profile-policy.json"
    verifier_path = root / "scripts" / "ci" / "verify_privacy_controls.py"
    evidence = _supervise_candidate_runtime(
        SHA,
        policy_path,
        root,
        tmp_path / "probe",
    )
    artifact_path = tmp_path / "privacy-evidence.json"
    artifact_path.write_text(json.dumps(evidence))

    assert evidence["schema_version"] == "candidate-privacy-supervisor-evidence/v1"
    assert evidence["candidate_process_returncode"] == 0
    assert evidence["deletion_test_passed"] is True
    assert evidence["retention_test_passed"] is True
    assert (
        _privacy_evidence_from_artifact(
            artifact_path,
            candidate_sha=SHA,
            policy_path=policy_path,
            verifier_path=verifier_path,
            require_supervised=True,
        ).deletion_test_passed
        is True
    )


def test_supervised_privacy_artifact_rejects_candidate_only_evidence(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    policy_path = root / "security" / "security-profile-policy.json"
    verifier_path = root / "scripts" / "ci" / "verify_privacy_controls.py"
    artifact_path = tmp_path / "privacy-evidence.json"
    artifact_path.write_text(json.dumps(_verify(SHA, policy_path, root)))

    with pytest.raises(ValueError, match="privacy verifier artifact"):
        _privacy_evidence_from_artifact(
            artifact_path,
            candidate_sha=SHA,
            policy_path=policy_path,
            verifier_path=verifier_path,
            require_supervised=True,
        )


def test_supervisor_survives_candidate_import_time_exit_without_evidence(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    candidate = tmp_path / "candidate"
    shutil.copytree(root / "src", candidate / "src")
    digest_module = candidate / "src" / "pmpe" / "contracts" / "digest.py"
    digest_module.write_text(
        digest_module.read_text()
        + """
import json as _json
import os as _os
from pathlib import Path as _Path
_challenge = _json.loads((_Path.cwd() / "privacy-challenge.json").read_text())
_shell = {
    "candidate_sha": _challenge["candidate_sha"],
    "challenge_digest": _challenge["challenge_digest"],
    "quarantine_delete_returned": True,
    "quarantine_existed_before_delete": True,
    "quarantine_exists_after_delete": False,
    "quarantine_read_digest": _challenge["payload_digest"],
    "schema_version": "candidate-privacy-receipt/v1",
}
_receipt = {**_shell, "receipt_digest": canonical_digest(_shell)}
(_Path.cwd() / "probe" / "candidate-receipt.json").write_text(_json.dumps(_receipt))
_os._exit(0)
"""
    )

    with pytest.raises(ValueError, match="candidate privacy subprocess did not complete exactly"):
        _supervise_candidate_runtime(
            SHA,
            root / "security" / "security-profile-policy.json",
            candidate,
            tmp_path / "probe",
        )


def test_supervisor_bypasses_candidate_atexit_probe_forgery(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    candidate = tmp_path / "candidate"
    shutil.copytree(root / "src", candidate / "src")
    intake_module = candidate / "src" / "pmpe" / "contracts" / "intake.py"
    intake_module.write_text(
        intake_module.read_text()
        + """
import atexit as _atexit
import json as _json
from pathlib import Path as _Path
from pmpe.contracts.digest import canonical_digest as _canonical_digest

def _broken_delete(self, handle):
    return False

FileQuarantineStore.delete = _broken_delete

def _forge_probe_at_exit():
    root = _Path.cwd() / "probe"
    quarantine = root / "quarantine"
    if quarantine.is_dir():
        for path in quarantine.iterdir():
            path.unlink()
    challenge = _json.loads((_Path.cwd() / "privacy-challenge.json").read_text())
    shell = {
        "candidate_sha": challenge["candidate_sha"],
        "challenge_digest": challenge["challenge_digest"],
        "quarantine_delete_returned": True,
        "quarantine_existed_before_delete": True,
        "quarantine_exists_after_delete": False,
        "quarantine_read_digest": challenge["payload_digest"],
        "schema_version": "candidate-privacy-receipt/v1",
    }
    receipt = {**shell, "receipt_digest": _canonical_digest(shell)}
    (root / "candidate-receipt.json").write_text(_json.dumps(receipt))

_atexit.register(_forge_probe_at_exit)
"""
    )

    with pytest.raises(ValueError, match="candidate privacy control verification"):
        _supervise_candidate_runtime(
            SHA,
            root / "security" / "security-profile-policy.json",
            candidate,
            tmp_path / "probe",
        )


def test_trusted_privacy_finalizer_rejects_forged_receipt_without_probe_state(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    policy_path = root / "security" / "security-profile-policy.json"
    probe_root = tmp_path / "probe"
    challenge_path = tmp_path / "privacy-challenge.json"
    receipt_path = probe_root / "candidate-receipt.json"
    challenge = _prepare_probe(SHA, policy_path, root, probe_root)
    challenge_path.write_text(json.dumps(challenge))
    shell = {
        "candidate_sha": SHA,
        "challenge_digest": challenge["challenge_digest"],
        "quarantine_delete_returned": True,
        "quarantine_existed_before_delete": True,
        "quarantine_exists_after_delete": False,
        "quarantine_read_digest": challenge["payload_digest"],
        "schema_version": "candidate-privacy-receipt/v1",
    }
    receipt_path.write_text(json.dumps({**shell, "receipt_digest": canonical_digest(shell)}))

    with pytest.raises(ValueError, match="candidate privacy control verification failed"):
        _finalize_probe(
            SHA,
            policy_path,
            root,
            challenge_path,
            probe_root,
            receipt_path,
        )


def test_dependency_inventory_uses_hash_bound_candidate_metadata(tmp_path: Path) -> None:
    digest = "a" * 64
    lock_path = tmp_path / "requirements.lock"
    lock_path.write_text(f"example==2.0.0 \\\n    --hash=sha256:{digest}\n")
    audit_payload = {
        "dependencies": [
            {"name": "example", "version": "2.0.0", "vulns": []},
        ]
    }
    install_report = {
        "version": "1",
        "install": [
            {
                "download_info": {"archive_info": {"hashes": {"sha256": digest}}},
                "metadata": {
                    "name": "example",
                    "version": "2.0.0",
                    "license_expression": "GPL-3.0",
                },
            }
        ],
    }

    assert _dependency_inventory(
        audit_payload,
        {},
        install_report=install_report,
        lock_path=lock_path,
    ) == (("example", "2.0.0", "GPL-3.0"),)


def test_dependency_inventory_rejects_same_version_with_unlocked_artifact(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "requirements.lock"
    lock_path.write_text(f"example==2.0.0 \\\n    --hash=sha256:{'a' * 64}\n")
    audit_payload = {
        "dependencies": [
            {"name": "example", "version": "2.0.0", "vulns": []},
        ]
    }
    install_report = {
        "version": "1",
        "install": [
            {
                "download_info": {"archive_info": {"hashes": {"sha256": "b" * 64}}},
                "metadata": {
                    "name": "example",
                    "version": "2.0.0",
                    "license_expression": "MIT",
                },
            }
        ],
    }

    with pytest.raises(ValueError, match="not hash-bound"):
        _dependency_inventory(
            audit_payload,
            {},
            install_report=install_report,
            lock_path=lock_path,
        )


@pytest.mark.parametrize(
    "record_path",
    [
        ("allowed_architecture_edges", 0),
        ("allowed_licenses", 0),
        ("license_fallbacks", 0),
        ("dynamic_import_allowlist", 0),
    ],
)
def test_security_policy_rejects_ownerless_grants(
    record_path: tuple[str, int],
) -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "security/security-profile-policy.json").read_text())
    collection, index = record_path
    del payload[collection][index]["approved_by"]

    with pytest.raises(ValueError, match="exact reviewed fields"):
        _reviewed_policy_config(
            payload,
            trusted_clock=lambda: datetime(2026, 8, 28, tzinfo=UTC),
        )


def test_security_policy_rejects_ownerless_telemetry_grants() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "security/security-profile-policy.json").read_text())
    del payload["privacy"]["telemetry_allowlist"][0]["approved_by"]

    with pytest.raises(ValueError, match="exact reviewed fields"):
        _reviewed_policy_config(
            payload,
            trusted_clock=lambda: datetime(2026, 8, 28, tzinfo=UTC),
        )


def test_security_policy_rejects_expired_grants() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "security/security-profile-policy.json").read_text())
    payload["dynamic_import_allowlist"][0]["expires_at"] = "2026-08-27T00:00:00Z"

    with pytest.raises(ValueError, match="review has expired"):
        _reviewed_policy_config(
            payload,
            trusted_clock=lambda: datetime(2026, 8, 28, tzinfo=UTC),
        )


def test_privacy_evidence_requires_executed_exact_candidate_artifact(tmp_path: Path) -> None:
    policy_path = tmp_path / "security-profile-policy.json"
    verifier_path = tmp_path / "verify_privacy_controls.py"
    policy_path.write_text("{}")
    verifier_path.write_text("# verifier\n")
    artifact_path = tmp_path / "privacy-evidence.json"
    artifact = {
        "candidate_sha": SHA,
        "classification": "INTERNAL",
        "deletion_test_passed": True,
        "emitted_telemetry": ["latency_ms", "outcome", "run_id"],
        "policy_file_digest": "sha256:" + "0" * 64,
        "residency": "IN",
        "retention_days": 30,
        "verifier_file_digest": "sha256:" + "0" * 64,
    }
    artifact["evidence_digest"] = canonical_digest(artifact)
    artifact_path.write_text(json.dumps(artifact))

    with pytest.raises(ValueError, match="privacy verifier artifact"):
        _privacy_evidence_from_artifact(
            artifact_path,
            candidate_sha=SHA,
            policy_path=policy_path,
            verifier_path=verifier_path,
        )


def test_ci_executes_provider_neutral_privacy_before_composed_profile() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/ci.yml").read_text()

    verifier = workflow.index("python scripts/ci/verify_privacy_controls.py")
    composed = workflow.index("python scripts/ci/evaluate_security_profile.py")
    assert verifier < composed
    assert "--privacy-evidence /tmp/security-profile/privacy-evidence.json" in workflow
    assert "AWS_RESIDENCY" not in workflow
    assert "configure-aws-credentials" not in workflow
    assert "observe_runtime_residency.py" not in workflow


def test_ci_materializes_security_authority_from_exact_protected_base() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/ci.yml").read_text()
    security = workflow[workflow.index("security-static:") : workflow.index("product-backend:")]

    assert "fetch-depth: 0" in security
    assert "BASE_SHA: ${{ github.event.pull_request.base.sha || github.sha }}" in security
    assert 'git cat-file -e "$BASE_SHA^{commit}"' in security
    assert (
        'git show "$BASE_SHA:security/security-profile-policy.json" '
        "> /tmp/trusted-security-policy/security-profile-policy.json"
    ) in security
    assert (
        'git show "$BASE_SHA:security/secret-allowlist.json" '
        "> /tmp/trusted-security-policy/secret-allowlist.json"
    ) in security
    assert "--allowlist /tmp/trusted-security-policy/secret-allowlist.json" in security
    assert "--policy /tmp/trusted-security-policy/security-profile-policy.json" in security
    assert "--secret-allowlist /tmp/trusted-security-policy/secret-allowlist.json" in security
    assert "--no-deps --disable-pip" in security
    assert "--root ." in security
    assert "--allowlist security/secret-allowlist.json" not in security
    assert "--policy security/security-profile-policy.json" not in security


def test_ci_keeps_editable_builds_inside_the_hash_lock() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/ci.yml").read_text()
    pyproject = (root / "pyproject.toml").read_text()
    lockfile = (root / "requirements.lock").read_text()

    assert 'requires = ["setuptools==' in pyproject
    assert "setuptools==" in lockfile
    locked_editable_install = "pip install --no-deps --no-build-isolation -e ."
    assert workflow.count(locked_editable_install) == 4
    candidate_isolation = workflow[
        workflow.index("candidate-isolation:") : workflow.index("security-static:")
    ]
    assert locked_editable_install in candidate_isolation
