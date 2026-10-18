"""Bounded operator configuration for the canonical build path."""

from __future__ import annotations

import argparse
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pmpe.barebones import BudgetCaps, ContractInvalidError
from pmpe.contracts.canonical import strict_loads

_INPUT_LIMIT_BYTES = 1_000_000


def read_input_bytes(path: Path, description: str, limit: int = _INPUT_LIMIT_BYTES) -> bytes:
    """Read only a bounded regular operator input through one opened descriptor."""
    if limit <= 0:
        raise ContractInvalidError(f"{description} has an invalid size limit")
    if not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")):
        raise ContractInvalidError("secure CLI input reading is unavailable")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ContractInvalidError(f"cannot read {description}") from exc
    try:
        try:
            file_status = os.fstat(descriptor)
            if not stat.S_ISREG(file_status.st_mode):
                raise ContractInvalidError(f"{description} must be a regular file")
            if file_status.st_size > limit:
                raise ContractInvalidError(f"{description} exceeds size limit")
            payload = bytearray()
            while len(payload) <= limit:
                chunk = os.read(descriptor, min(64 * 1024, limit + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
            if len(payload) > limit:
                raise ContractInvalidError(f"{description} exceeds size limit")
            return bytes(payload)
        except OSError as exc:
            raise ContractInvalidError(f"cannot read {description}") from exc
    finally:
        os.close(descriptor)


def register_build_options(parser: argparse.ArgumentParser, *, runtime: bool) -> None:
    parser.add_argument("--task-graph", help="JSON dependency context bound to the compiled plan")
    if runtime:
        parser.add_argument("--max-attempts", type=int, default=3)
        parser.add_argument("--max-model-calls", type=int, default=8)
        parser.add_argument("--max-model-output-bytes", type=int, default=1_000_000)
        parser.add_argument(
            "--max-wall-time",
            type=float,
            default=1800.0,
            help="cumulative checkpoint time limit in seconds",
        )
        parser.add_argument("--max-input-tokens", type=int)
        parser.add_argument("--max-output-tokens", type=int)


def build_budget(args: argparse.Namespace) -> BudgetCaps:
    return BudgetCaps(
        max_attempts=args.max_attempts,
        max_model_calls=args.max_model_calls,
        max_model_output_bytes=args.max_model_output_bytes,
        max_wall_time_seconds=args.max_wall_time,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
    )


def load_task_graph(path: str | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    payload = read_input_bytes(Path(path), "task graph")
    result = strict_loads(payload, "application/json")
    if not isinstance(result, Mapping):
        raise ContractInvalidError("task graph must be a JSON object")
    return result
