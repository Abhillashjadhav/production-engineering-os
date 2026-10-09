"""Local task tracker for contract PMOS-TASK-TRACKER-001.

Written by the in-session model during the live build. One CLI process per
command; state lives in a JSON store whose path the caller must supply.
Creation is not idempotent by approved decision; completion is idempotent.
Durability covers orderly process exit, not power loss. Single writer only.
"""

import json
import os
import sys
import tempfile

STATUSES = ("all", "open", "completed")


class TrackerError(Exception):
    """A documented product error carrying its CLI error code and exit status."""

    def __init__(self, code, exit_code):
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def emit(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()


def empty_state():
    return {"version": 1, "next_id": 1, "tasks": []}


def load_state(store):
    try:
        with open(store, "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return empty_state()
    except OSError:
        raise TrackerError("STORE_IO", 1)
    try:
        state = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise TrackerError("STORE_INVALID", 1)
    if not valid_state(state):
        raise TrackerError("STORE_INVALID", 1)
    return state


def valid_state(state):
    if not isinstance(state, dict) or state.get("version") != 1:
        return False
    next_id = state.get("next_id")
    tasks = state.get("tasks")
    if type(next_id) is not int or next_id < 1 or not isinstance(tasks, list):
        return False
    seen = set()
    for task in tasks:
        if not isinstance(task, dict):
            return False
        identifier = task.get("id")
        if type(identifier) is not int or identifier < 1 or identifier >= next_id:
            return False
        if identifier in seen:
            return False
        seen.add(identifier)
        if not isinstance(task.get("title"), str) or task.get("status") not in ("open", "completed"):
            return False
    return True


def save_state(store, state):
    directory = os.path.dirname(os.path.abspath(store)) or "."
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".tasks-", suffix=".tmp", dir=directory)
    except OSError:
        raise TrackerError("STORE_IO", 1)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, store)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise TrackerError("STORE_IO", 1)


def public(task):
    return {"id": task["id"], "title": task["title"], "status": task["status"]}


def parse_id(text):
    if not isinstance(text, str) or not text.isdigit():
        raise TrackerError("INVALID_ID", 2)
    value = int(text)
    if value < 1 or str(value) != text:
        raise TrackerError("INVALID_ID", 2)
    return value


def command_create(store, arguments):
    if len(arguments) != 1:
        raise TrackerError("INVALID_COMMAND", 2)
    title = arguments[0]
    if title.strip() == "":
        raise TrackerError("INVALID_TITLE", 2)
    state = load_state(store)
    task = {"id": state["next_id"], "title": title, "status": "open"}
    state["tasks"].append(task)
    state["next_id"] += 1
    save_state(store, state)
    return {"task": public(task)}


def command_complete(store, arguments):
    if len(arguments) != 1:
        raise TrackerError("INVALID_COMMAND", 2)
    identifier = parse_id(arguments[0])
    state = load_state(store)
    for task in state["tasks"]:
        if task["id"] == identifier:
            if task["status"] != "completed":
                task["status"] = "completed"
                save_state(store, state)
            return {"task": public(task)}
    raise TrackerError("NOT_FOUND", 2)


def command_list(store, arguments):
    status = "all"
    if arguments:
        if len(arguments) != 2 or arguments[0] != "--status":
            raise TrackerError("INVALID_COMMAND", 2)
        status = arguments[1]
        if status not in STATUSES:
            raise TrackerError("INVALID_STATUS", 2)
    state = load_state(store)
    tasks = sorted(state["tasks"], key=lambda task: task["id"])
    if status != "all":
        tasks = [task for task in tasks if task["status"] == status]
    return {"tasks": [public(task) for task in tasks]}


COMMANDS = {"create": command_create, "complete": command_complete, "list": command_list}


def main(argv):
    try:
        if len(argv) < 3 or argv[0] != "--store" or argv[2] not in COMMANDS:
            raise TrackerError("INVALID_COMMAND", 2)
        result = COMMANDS[argv[2]](argv[1], argv[3:])
    except TrackerError as error:
        emit({"error": error.code})
        return error.exit_code
    emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
