"""Local process deployment with real verification (ADR-005).

Deploy = start the generated product as a real subprocess with a freshly
generated token, wait for /health, then walk the main user journey over HTTP
(including a negative auth check). Also emits the deployable artifact:
run.sh, Dockerfile, DEPLOYMENT.md, ROLLBACK.md.
"""

from __future__ import annotations

import json
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

from pmpe.domain.models import DeploymentResult, MvpSpec
from pmpe.stacks import capabilities_for, collection_route, has_auth


class DeploymentAdapter(Protocol):
    def write_artifacts(self, workspace: Path, spec: MvpSpec) -> list[str]: ...

    def deploy(self, workspace: Path, spec: MvpSpec) -> DeploymentResult: ...


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    method: str, url: str, body: dict[str, Any] | None = None, token: str | None = None
) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, json.loads(raw) if raw else None


class LocalProcessDeployer:
    def __init__(self, timeout_s: float = 15.0) -> None:
        self.timeout_s = timeout_s

    # --- deployable artifact ------------------------------------------------------

    def write_artifacts(self, workspace: Path, spec: MvpSpec) -> list[str]:
        deploy_dir = workspace / "deploy"
        deploy_dir.mkdir(exist_ok=True)
        files = {
            "run.sh": _RUN_SH,
            "Dockerfile": _DOCKERFILE,
            "DEPLOYMENT.md": _deployment_md(spec),
            "ROLLBACK.md": _rollback_md(spec),
        }
        for name, content in files.items():
            (deploy_dir / name).write_text(content)
        (deploy_dir / "run.sh").chmod(0o755)
        return [f"deploy/{name}" for name in files]

    # --- live deploy + verification -------------------------------------------------

    def deploy(self, workspace: Path, spec: MvpSpec) -> DeploymentResult:
        port = _free_port()
        token = secrets.token_urlsafe(24) if has_auth(spec) else ""
        workspace = workspace.resolve()
        db_path = workspace / "deploy" / "verify.db"
        db_path.unlink(missing_ok=True)
        env = {
            "APP_DB": str(db_path),
            "APP_PORT": str(port),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        }
        if token:
            env["APP_TOKEN"] = token
        base = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.server"],
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            healthy = self._wait_healthy(base, proc)
            journey_passed, details = (
                self._run_journey(base, spec, token) if healthy else (False, "not healthy")
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            db_path.unlink(missing_ok=True)
        return DeploymentResult(
            environment="local",
            url=base,
            healthy=healthy,
            journey_passed=journey_passed,
            rollback_instructions_path="deploy/ROLLBACK.md",
            details=details if healthy else _proc_failure_details(proc),
        )

    def _wait_healthy(self, base: str, proc: subprocess.Popen[str]) -> bool:
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return False
            try:
                status, body = _request("GET", f"{base}/health")
                if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
                    return True
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.1)
        return False

    def _run_journey(self, base: str, spec: MvpSpec, token: str) -> tuple[bool, str]:
        """Walk the main user journey derived from the spec's capabilities."""
        steps: list[str] = ["health: ok"]
        if not spec.entities:
            return True, "; ".join(steps)
        entity = spec.entities[0]
        caps = capabilities_for(spec, entity)
        route = collection_route(entity)
        required = {f.name: f"smoke {f.name}" for f in entity.fields if f.required}
        has_status = any(f.name == "status" for f in entity.fields)

        if has_auth(spec):
            status, _ = _request("GET", f"{base}{route}")
            if status != 401:
                return False, f"unauthorized request returned {status}, expected 401"
            steps.append("auth rejects missing token: ok")

        item_id: int | None = None
        if "entity.create" in caps:
            status, body = _request("POST", f"{base}{route}", required, token)
            if status != 201:
                return False, f"create returned {status}, expected 201"
            item_id = body["id"]
            steps.append("create: ok")
        if "entity.list" in caps:
            status, body = _request("GET", f"{base}{route}", token=token)
            if status != 200 or (item_id is not None and item_id not in [r["id"] for r in body]):
                return False, f"list returned {status} or missing created item"
            steps.append("list: ok")
        if "entity.update" in caps and item_id is not None and has_status:
            status, body = _request("PATCH", f"{base}{route}/{item_id}", {"status": "done"}, token)
            if status != 200 or body.get("status") != "done":
                return False, f"complete (status=done) failed with {status}"
            steps.append("complete: ok")
        if "entity.read" in caps and item_id is not None:
            status, body = _request("GET", f"{base}{route}/{item_id}", token=token)
            if status != 200:
                return False, f"read-back returned {status}"
            steps.append("read-back: ok")
        return True, "; ".join(steps)


def _proc_failure_details(proc: subprocess.Popen[str]) -> str:
    err = ""
    if proc.stderr is not None:
        err = proc.stderr.read()[-500:]
    return f"process did not become healthy; stderr tail: {err}"


_RUN_SH = """#!/usr/bin/env bash
set -euo pipefail
: "${APP_TOKEN:?APP_TOKEN must be set — see DEPLOYMENT.md}"
export APP_DB="${APP_DB:-data.db}"
export APP_PORT="${APP_PORT:-8000}"
exec python3 -m app.server
"""

_DOCKERFILE = """FROM python:3.11-slim
WORKDIR /srv/app
COPY app/ app/
ENV APP_DB=/data/data.db APP_PORT=8000 APP_BIND=0.0.0.0
VOLUME /data
EXPOSE 8000
# APP_TOKEN must be provided at runtime: docker run -e APP_TOKEN=... (never bake it in)
CMD ["python3", "-m", "app.server"]
"""


def _deployment_md(spec: MvpSpec) -> str:
    return f"""# Deploying {spec.product_name}

## Local process
1. `export APP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"`
2. `export APP_DB=/var/lib/{spec.product_name.lower()}/data.db` (any writable path)
3. `./deploy/run.sh`
4. Verify: `curl -fsS http://127.0.0.1:8000/health` returns status ok.

## Container
1. `docker build -t {spec.product_name.lower()} .` (uses deploy/Dockerfile)
2. `docker run -e APP_TOKEN=... -p 8000:8000 -v appdata:/data {spec.product_name.lower()}`

The token is injected at runtime only — it is never stored in the image or repo.
"""


def _rollback_md(spec: MvpSpec) -> str:
    return f"""# Rolling back {spec.product_name}

1. Stop the process (Ctrl-C, `kill <pid>`, or `docker stop <container>`).
2. Restore the previous artifact directory (each deploy is a self-contained copy).
3. The SQLite file (APP_DB) is the only state. Back it up before upgrades:
   `cp "$APP_DB" "$APP_DB.bak-$(date +%s)"` — restore by copying it back.
4. Restart with deploy/run.sh and re-verify /health.

No schema migrations are applied automatically in V1, so rollback never loses
data written by a newer version silently — CREATE TABLE IF NOT EXISTS is additive only.
"""
