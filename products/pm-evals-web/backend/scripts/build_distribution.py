"""Build one installable wheel containing the API, CLI, and dashboard.

Run from any directory with Python 3.11/3.12, Node 22.18+, npm, setuptools,
and wheel installed. No generated frontend files are added to the source tree.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    backend = Path(__file__).resolve().parents[1]
    frontend = backend.parent / "frontend"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=backend / "dist")
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Use already installed frontend dependencies instead of npm ci",
    )
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("CI", "1")
    # Stable timestamps make repeated builds of the same inputs reproducible.
    # Pin the Python and Node build tool versions when comparing wheel bytes.
    env.setdefault("SOURCE_DATE_EPOCH", "1704067200")
    if not args.skip_install:
        subprocess.run(["npm", "ci"], cwd=frontend, env=env, check=True)
    subprocess.run(
        ["node", "node_modules/vite/bin/vite.js", "build"],
        cwd=frontend,
        env=env,
        check=True,
    )
    subprocess.run(
        ["node", "scripts/write-build-id.mjs"],
        cwd=frontend,
        env=env,
        check=True,
    )
    dist = frontend / "dist"
    if not (dist / "index.html").is_file() or not (dist / "BUILD_ID").is_file():
        raise RuntimeError("Frontend build is missing index.html or BUILD_ID")
    with tempfile.TemporaryDirectory(prefix="pm-evals-wheel-") as temporary:
        stage = Path(temporary)
        shutil.copy2(backend / "pyproject.toml", stage / "pyproject.toml")
        shutil.copytree(
            backend / "src",
            stage / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info", "web"),
        )
        shutil.copytree(dist, stage / "src" / "pm_evals_monitoring" / "web")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--disable-pip-version-check",
                "--no-index",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(output),
                str(stage),
            ],
            env=env,
            check=True,
        )
    print(f"Installable dashboard wheel: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
