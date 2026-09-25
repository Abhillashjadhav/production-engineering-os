"""Local task tracker generated for the approved PMOS task-tracker contract.

Single writer, orderly process restart persistence. Creation is not idempotent.
"""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path


class StoreError(Exception):
    def __init__(self, code):
        self.code = code


def emit(value, code=0):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return code


def load_store(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"version": 1, "next_id": 1, "tasks": []}
    except OSError as error:
        raise StoreError("STORE_IO") from error
    except UnicodeError as error:
        raise StoreError("STORE_INVALID") from error
    try:
        state = json.loads(raw)
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("invalid store version")
        tasks = state.get("tasks")
        next_id = state.get("next_id")
        if not isinstance(tasks, list) or type(next_id) is not int or next_id < 1:
            raise ValueError("invalid store structure")
        seen = set()
        for task in tasks:
            if not isinstance(task, dict) or set(task) != {"id", "title", "status"}:
                raise ValueError("invalid task structure")
            identifier = task["id"]
            if type(identifier) is not int or identifier < 1 or identifier in seen:
                raise ValueError("invalid task identity")
            if not isinstance(task["title"], str) or not task["title"].strip():
                raise ValueError("invalid task title")
            if task["status"] not in ("open", "completed"):
                raise ValueError("invalid task status")
            seen.add(identifier)
        if next_id != max(seen, default=0) + 1:
            raise ValueError("invalid next identity")
        return state
    except (ValueError, TypeError, KeyError) as error:
        raise StoreError("STORE_INVALID") from error


def save_store(path, state):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".task-write-", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(state, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.unlink()  # Deliberate mutation: discard acknowledged writes.
        temporary = None
    except OSError as error:
        raise StoreError("STORE_IO") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("title")
    complete = commands.add_parser("complete")
    complete.add_argument("id")
    listing = commands.add_parser("list")
    listing.add_argument("--status", default="all")
    args = parser.parse_args()

    if args.command == "create" and not args.title.strip():
        return emit({"error": "INVALID_TITLE"}, 2)
    if args.command == "complete":
        if not re.fullmatch(r"[0-9]+", args.id):
            return emit({"error": "INVALID_ID"}, 2)
        try:
            identifier = int(args.id)
        except ValueError:
            return emit({"error": "INVALID_ID"}, 2)
        if identifier < 1:
            return emit({"error": "INVALID_ID"}, 2)
    if args.command == "list" and args.status not in ("all", "open", "completed"):
        return emit({"error": "INVALID_STATUS"}, 2)

    try:
        state = load_store(args.store)
        if args.command == "create":
            task = {"id": state["next_id"], "title": args.title, "status": "open"}
            state["tasks"].append(task)
            state["next_id"] += 1
            save_store(args.store, state)
            return emit({"task": task})
        if args.command == "complete":
            task = next((item for item in state["tasks"] if item["id"] == identifier), None)
            if task is None:
                return emit({"error": "NOT_FOUND"}, 2)
            if task["status"] != "completed":
                task["status"] = "completed"
                save_store(args.store, state)
            return emit({"task": task})
        tasks = sorted(state["tasks"], key=lambda item: item["id"])
        if args.status != "all":
            tasks = [task for task in tasks if task["status"] == args.status]
        return emit({"tasks": tasks})
    except StoreError as error:
        return emit({"error": error.code}, 1)


if __name__ == "__main__":
    raise SystemExit(main())
