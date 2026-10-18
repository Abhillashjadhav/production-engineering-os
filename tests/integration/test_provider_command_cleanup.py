from __future__ import annotations

import io
import selectors
import signal
import subprocess
from types import SimpleNamespace

import pytest

from pmpe.cli import barebones_cmd


class _Stream(io.BytesIO):
    def fileno(self) -> int:
        return 91


class _Process:
    pid = 54321
    returncode: int | None = None

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.stdout = _Stream()
        self.stderr = _Stream()

    def wait(self) -> int:
        self.events.append("wait")
        self.returncode = 0
        return 0


def test_interrupt_after_reap_never_signals_recycled_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    process = _Process(events)
    selector = _Selector(process, events, "success")

    def interrupted_wait() -> int:
        process.returncode = 0
        raise KeyboardInterrupt

    monkeypatch.setattr(process, "wait", interrupted_wait)
    monkeypatch.setattr(barebones_cmd.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(barebones_cmd.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(barebones_cmd, "_wait_for_provider_exit_without_reaping", lambda *_: True)
    monkeypatch.setattr(barebones_cmd.os, "killpg", lambda *_: events.append("killpg"))
    with pytest.raises(KeyboardInterrupt):
        barebones_cmd._run_provider_command(("provider",), b"{}", 2)
    assert events == ["killpg", "selector-close"]


class _Selector:
    def __init__(self, process: _Process, events: list[str], failure: str) -> None:
        self.process = process
        self.events = events
        self.failure = failure
        self.registered: list[object] = []
        self.closed = False

    def register(self, fileobj: object, _events: int, _data: str) -> None:
        if self.failure == "register":
            raise OSError("test-only register failure")
        self.registered.append(fileobj)

    def get_map(self) -> dict[str, object]:
        if self.failure == "success":
            return {}
        return {"stdout": self.process.stdout}

    def select(self, _timeout: float) -> list[tuple[object, int]]:
        if self.failure == "interrupt":
            raise KeyboardInterrupt
        if self.failure == "select":
            raise OSError("test-only selector failure")
        key = SimpleNamespace(fd=91, fileobj=self.process.stdout, data="stdout")
        return [(key, selectors.EVENT_READ)]

    def close(self) -> None:
        self.events.append("selector-close")
        self.closed = True


@pytest.mark.parametrize(
    ("failure", "exception"),
    [
        ("register", OSError),
        ("read", OSError),
        ("interrupt", KeyboardInterrupt),
    ],
)
def test_provider_failure_fences_reaps_and_closes_every_allocated_resource(
    monkeypatch: pytest.MonkeyPatch, failure: str, exception: type[BaseException]
) -> None:
    events: list[str] = []
    process = _Process(events)
    selector = _Selector(process, events, failure)
    monkeypatch.setattr(barebones_cmd.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(barebones_cmd.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(
        barebones_cmd.os,
        "killpg",
        lambda pid, sig: events.append(f"killpg:{pid}:{sig}"),
    )
    if failure == "read":

        def failing_read(_fd: int, _size: int) -> bytes:
            raise OSError("test-only read failure")

        monkeypatch.setattr(barebones_cmd.os, "read", failing_read)

    with pytest.raises(exception, match="test-only" if exception is OSError else None):
        barebones_cmd._run_provider_command(("provider",), b"{}", 2)

    assert events.count(f"killpg:{process.pid}:{signal.SIGKILL}") == 1
    assert events.count("wait") == 1
    assert events.index(f"killpg:{process.pid}:{signal.SIGKILL}") < events.index("wait")
    assert selector.closed
    assert process.stdout.closed and process.stderr.closed


def test_successful_provider_fences_group_once_before_reaping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    process = _Process(events)
    selector = _Selector(process, events, "success")
    monkeypatch.setattr(barebones_cmd.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(barebones_cmd.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(
        barebones_cmd,
        "_wait_for_provider_exit_without_reaping",
        lambda _process, _timeout: True,
    )
    monkeypatch.setattr(
        barebones_cmd.os,
        "killpg",
        lambda pid, sig: events.append(f"killpg:{pid}:{sig}"),
    )

    result = barebones_cmd._run_provider_command(("provider",), b"{}", 2)

    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert events.count(f"killpg:{process.pid}:{signal.SIGKILL}") == 1
    assert events.count("wait") == 1
    assert events.index(f"killpg:{process.pid}:{signal.SIGKILL}") < events.index("wait")
    assert selector.closed
    assert process.stdout.closed and process.stderr.closed
