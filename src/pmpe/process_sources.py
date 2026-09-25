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
from types import CodeType
from typing import TYPE_CHECKING, Any

from pmpe.contracts.canonical import canonical_digest, strict_loads

if TYPE_CHECKING:
    from pmpe.barebones import Template

# Set by the import system; declared for type checking only (no assignment).
__cached__: str | None


def raw_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _startup_record(name: str) -> list[bytes] | None:
    """The kernel's copy of this process's startup argv or environment, where available.

    Runtime edits to ``os.environ`` or ``sys._xoptions`` do not change these records.
    Platforms without ``/proc`` (for example macOS) fall back to the runtime values.
    """
    try:
        return (Path("/proc/self") / name).read_bytes().split(b"\0")
    except OSError:
        return None


def _interpreter_xoptions(cmdline: list[bytes]) -> list[bytes]:
    """``-X`` values given to the interpreter itself, before the script, ``-c`` or ``-m``.

    Anything after that boundary is an argument to the program, not a startup option.
    """
    values: list[bytes] = []
    index = 1
    while index < len(cmdline):
        token = cmdline[index]
        if token == b"--" or token == b"-" or not token.startswith(b"-"):
            break
        if token.startswith(b"--"):
            index += 2 if token == b"--check-hash-based-pycs" else 1
            continue
        flags = token[1:]
        for position in range(len(flags)):
            flag = flags[position : position + 1]
            if flag in (b"c", b"m"):
                return values
            if flag in (b"X", b"W"):
                inline = flags[position + 1 :]
                if not inline:
                    index += 1
                    inline = cmdline[index] if index < len(cmdline) else b""
                if flag == b"X":
                    values.append(inline)
                break
        index += 1
    return values


def _startup_pycache_prefix() -> str | None:
    """The cache prefix this interpreter was started with (``-X`` wins over the env).

    Where ``/proc`` exists only the kernel's startup records count: runtime edits to
    ``sys._xoptions`` or ``os.environ`` can neither add a prefix nor remove the startup
    ``-X`` that overrode the environment.
    """
    cmdline = _startup_record("cmdline")
    if cmdline is not None:
        prefixes = [
            value.removeprefix(b"pycache_prefix=")
            for value in _interpreter_xoptions(cmdline)
            if value.startswith(b"pycache_prefix=")
        ]
        if prefixes:
            return os.fsdecode(prefixes[-1]) or None
        if sys.flags.ignore_environment:
            return None
        # getenv() returns the first entry, so the first one is what CPython read.
        entries = [
            entry.removeprefix(b"PYTHONPYCACHEPREFIX=")
            for entry in _startup_record("environ") or []
            if entry.startswith(b"PYTHONPYCACHEPREFIX=")
        ]
        return os.fsdecode(entries[0]) or None if entries else None
    # No /proc (for example macOS): only runtime values exist here (open question Q20).
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


def _compiled_code(source: str) -> dict[str, list[CodeType]]:
    """Every code object compiled from ``source``, keyed by qualified name."""
    try:
        root = compile(Path(source).read_bytes(), source, "exec", dont_inherit=True)
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError("process gate implementation source does not compile") from exc
    codes: dict[str, list[CodeType]] = {}
    pending = [root]
    while pending:
        for constant in pending.pop().co_consts:
            if isinstance(constant, CodeType):
                codes.setdefault(constant.co_qualname, []).append(constant)
                pending.append(constant)
    return codes


def _require_compiled_methods(klass: type) -> None:
    if klass.__module__ == "builtins":
        return
    source = inspect.getsourcefile(klass)
    if source is None:
        raise ValueError("process gate implementation has no inspectable source")
    compiled = _compiled_code(source)
    for value in vars(klass).values():
        function = getattr(value, "__func__", value)
        if isinstance(function, property):
            function = function.fget
        if not inspect.isfunction(function):
            continue
        code = inspect.unwrap(function).__code__
        # The code must be this class's own method, not other code from the same file.
        if code.co_qualname != klass.__qualname__ + "." + code.co_name or not any(
            code == candidate for candidate in compiled.get(code.co_qualname, ())
        ):
            raise ValueError("process gate implementation is not its canonical module class")


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
    # A dict that merely claims the module's name (for example one filled by exec) is not
    # the loaded module; the class's own functions must close over the real module's dict.
    module = inspect.getmodule(cls)
    if canonical is not cls or module is None or vars(module) is not namespace:
        raise ValueError("process gate implementation is not its canonical module class")
    source = inspect.getsourcefile(cls)
    if source is None:
        raise ValueError("process gate implementation has no inspectable source")
    # A replacement module can take the approved name and __file__, but not the approved
    # code: every method must be the code compiled from its class's own source file.
    for klass in cls.__mro__[:-1]:
        _require_compiled_methods(klass)
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
