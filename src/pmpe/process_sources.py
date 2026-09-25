"""Exact source inventory independent of the contract/receipt that will bind it."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmpe.contracts.canonical import canonical_digest, strict_loads

if TYPE_CHECKING:
    from pmpe.barebones import Template

# Set by the import system; declared for type checking only (no assignment).
__cached__: str | None


def raw_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _startup_pycache_prefix() -> str | None:
    """The cache prefix this interpreter was started with (``-X`` wins over the env)."""
    option = sys._xoptions.get("pycache_prefix")
    if isinstance(option, str) and option:
        return option
    if sys.flags.ignore_environment:
        return None
    return os.environ.get("PYTHONPYCACHEPREFIX") or None


def require_source_only_interpreter() -> Path:
    """Refuse any interpreter that could have loaded code from a bytecode cache.

    Owner-approved boundary (2026-09-25): a gated run starts with bytecode writes off and
    an empty private cache prefix, both fixed at interpreter start. Every source module
    is then compiled from source, so no module-registry scan is needed. A prefix assigned
    after start cannot vouch for modules imported before it.
    """
    if not (sys.flags.dont_write_bytecode and sys.dont_write_bytecode):
        raise ValueError(
            "process gate requires a source-only interpreter: start Python with -B or "
            "PYTHONDONTWRITEBYTECODE=1 so no bytecode is written"
        )
    startup = _startup_pycache_prefix()
    if startup is None or sys.pycache_prefix != startup:
        raise ValueError(
            "process gate requires a source-only interpreter: set an empty private "
            "bytecode prefix at start (-X pycache_prefix=DIR or PYTHONPYCACHEPREFIX) "
            "and keep it unchanged"
        )
    prefix = Path(startup)
    if not prefix.is_absolute():
        # A relative prefix names a different directory after any chdir.
        raise ValueError("process gate requires an absolute private bytecode prefix fixed at start")
    # CPython follows directory symlinks while resolving its parallel cache tree, so an
    # "empty" prefix may hold no entry at all: no file, directory or link of any kind.
    if prefix.is_symlink() or (prefix.exists() and (not prefix.is_dir() or any(prefix.iterdir()))):
        raise ValueError("process gate bytecode prefix is not empty: " + str(prefix))
    return prefix


def bytecode_paths(source: Path) -> tuple[Path, ...]:
    """Where the import system would cache ``source`` at optimization levels "", 1 and 2.

    Mirrors ``importlib.util.cache_from_source`` with pure path logic: the architecture
    gate forbids import machinery in the engine core.
    """
    tag = sys.implementation.cache_tag
    if tag is None:
        raise ValueError("process gate cannot derive bytecode cache paths: no cache tag")
    head = source.absolute().parent
    base, separator, rest = source.name.rpartition(".")
    stem = (base if base else rest) + separator + tag
    names = [stem + (".opt-" + level if level else "") + ".pyc" for level in ("", "1", "2")]
    if sys.pycache_prefix is None:
        directory = head / "__pycache__"
    else:
        directory = Path(sys.pycache_prefix) / head.relative_to(head.anchor)
    return tuple(directory / name for name in names)


def reject_bytecode(roots: Sequence[Path]) -> None:
    resolved = {root.resolve() for root in roots}
    roots = tuple(
        root
        for root in resolved
        if not any(root != parent and root.is_relative_to(parent) for parent in resolved)
    )
    engine_cached = __cached__
    if (
        engine_cached
        and any(Path(__file__).resolve().is_relative_to(root) for root in roots)
        and Path(engine_cached).is_file()
    ):
        raise ValueError("process gate active uninventoried bytecode: " + str(engine_cached))
    for root in set(roots):
        for source in root.rglob("*.py"):
            for cached_path in bytecode_paths(source.resolve()):
                if cached_path.is_file():
                    raise ValueError(
                        "process gate active or future uninventoried bytecode: " + str(cached_path)
                    )
        if any(path.is_file() and path.suffix in {".pyc", ".pyo"} for path in root.rglob("*")):
            raise ValueError("process gate uninventoried bytecode under source root: " + str(root))
    require_source_only_interpreter()


def engine_sources() -> dict[str, Path]:
    root = Path(__file__).parent
    reject_bytecode([root])
    return {
        "engine/" + str(path.relative_to(root)): path.resolve()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def _defining_namespace(cls: type) -> dict[str, Any]:
    """Globals of the module that compiled the class body's own functions.

    Unlike ``__module__``, a function's ``__globals__`` cannot be relabelled after
    definition, so it names where the class was really defined.
    """
    namespaces: list[dict[str, Any]] = []
    for value in vars(cls).values():
        function = getattr(value, "__func__", value)
        if isinstance(function, property):
            function = function.fget
        function = inspect.unwrap(function) if inspect.isfunction(function) else function
        namespace = getattr(function, "__globals__", None)
        if isinstance(namespace, dict):
            namespaces.append(namespace)
    if not namespaces or any(namespace is not namespaces[0] for namespace in namespaces):
        raise ValueError("process gate implementation is not its canonical module class")
    return namespaces[0]


def implementation_identity(implementation: object) -> dict[str, Any]:
    cls = type(implementation)
    namespace = _defining_namespace(cls)
    parts = cls.__qualname__.split(".")
    if namespace.get("__name__") != cls.__module__ or any(
        not part.isidentifier() or part.startswith("__") for part in parts
    ):
        raise ValueError("process gate implementation is not its canonical module class")
    canonical = namespace.get(parts[0])
    for name in parts[1:]:
        canonical = vars(canonical).get(name) if isinstance(canonical, type) else None
    if canonical is not cls:
        raise ValueError("process gate implementation is not its canonical module class")
    source = inspect.getsourcefile(cls)
    if source is None:
        raise ValueError("process gate implementation has no inspectable source")
    identity: dict[str, Any] = {
        "class": type(implementation).__module__ + "." + type(implementation).__qualname__,
        "source_digest": raw_digest(Path(source).read_bytes()),
    }
    delegate = getattr(implementation, "delegate", None)
    if delegate is not None:
        identity["delegate"] = implementation_identity(delegate)
    return identity


def build_source_manifest(
    template: Template,
    source_paths: Mapping[str, Path],
    profile: bytes,
    *,
    sandbox: object | None = None,
) -> bytes:
    """No contract or receipt: an outer freeze can bind these after actual approval."""
    if "adapter" not in source_paths or any(
        key.startswith(("engine/", "approval/", "protected/")) for key in source_paths
    ):
        raise ValueError(
            "source manifest requires adapter and reserves engine/, approval/ and protected/ names"
        )
    reject_bytecode(
        [
            source_paths["adapter"].parent,
            *(path.parent for path in source_paths.values() if path.suffix == ".py"),
        ]
    )
    paths = {**engine_sources(), **source_paths}
    value = {
        "schema_version": "1",
        "sandbox_identity": implementation_identity(sandbox) if sandbox is not None else None,
        "artifacts": {name: raw_digest(path.read_bytes()) for name, path in sorted(paths.items())},
        "template_digest": canonical_digest(asdict(template)),
        "execution_profile_sha256": raw_digest(profile),
        "scope": (
            "Immutable engine, adapter, evaluator/template and "
            "profile; approval freeze is separate."
        ),
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def validate_sources(
    manifest_bytes: bytes,
    source_paths: Mapping[str, Path],
    template: Template,
    profile: bytes,
    implementations: tuple[object, ...],
) -> tuple[dict[str, Path], dict[str, str]]:
    manifest = strict_loads(manifest_bytes, "application/json")
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "sandbox_identity",
            "artifacts",
            "template_digest",
            "execution_profile_sha256",
            "scope",
        }
        or manifest["schema_version"] != "1"
    ):
        raise ValueError("process gate source manifest shape is invalid")
    if "adapter" not in source_paths or any(
        key.startswith(("engine/", "approval/", "protected/")) for key in source_paths
    ):
        raise ValueError(
            "process gate source manifest requires adapter and reserves evidence namespaces"
        )
    reject_bytecode(
        [
            source_paths["adapter"].parent,
            *(path.parent for path in source_paths.values() if path.suffix == ".py"),
        ]
    )
    paths = {**engine_sources(), **source_paths}
    expected = manifest["artifacts"]
    if not isinstance(expected, dict) or set(expected) != set(paths):
        raise ValueError("process gate source manifest omits or adds inventory entries")
    if manifest["template_digest"] != canonical_digest(asdict(template)) or manifest[
        "execution_profile_sha256"
    ] != raw_digest(profile):
        raise ValueError("process gate template/profile differs from bound manifest")
    if manifest["sandbox_identity"] != implementation_identity(implementations[-1]):
        raise ValueError("process gate sandbox identity is not declared in source manifest")
    expanded = list(implementations)
    for implementation in implementations:
        delegate = getattr(implementation, "delegate", None)
        while delegate is not None:
            expanded.append(delegate)
            delegate = getattr(delegate, "delegate", None)
    for implementation in expanded:
        source = inspect.getsourcefile(type(implementation))
        if source is None or Path(source).resolve() not in {
            path.resolve() for path in paths.values()
        }:
            raise ValueError("process gate manifest omits provider/sandbox implementation")
    if any(expected[name] != raw_digest(path.read_bytes()) for name, path in paths.items()):
        raise ValueError("process gate source manifest digest mismatch")
    return paths, expected
