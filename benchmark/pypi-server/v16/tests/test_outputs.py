from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


PROJECT = Path("/app/vectorops")
STATE = Path(os.environ.get("DEVPKG_INDEX_STATE_DIR", "/tmp/devpkg-index-state"))
INDEX_URL = "http://localhost:3141/simple"
INDEX_TOOL = "/usr/local/bin/devpkg-index"


def test_project_and_built_metadata_use_corrected_version():
    pyproject = (PROJECT / "pyproject.toml").read_text()
    assert 'version = "0.1.1"' in pyproject

    artifacts = sorted(path.name for path in (PROJECT / "dist").iterdir() if path.is_file())
    assert artifacts
    assert all("0.1.1" in name for name in artifacts)


def test_index_preserves_old_release_and_publishes_new_release():
    packages = sorted(path.name for path in (STATE / "packages").iterdir() if path.is_file())
    assert any("0.1.0" in name for name in packages)
    assert any("0.1.1" in name for name in packages)

    page = urllib.request.urlopen(f"{INDEX_URL}/vectorops/").read().decode()
    assert "0.1.0" in page
    assert "0.1.1" in page


def test_index_state_requires_declared_authentication(tmp_path: Path):
    users = json.loads((STATE / "users.json").read_text())
    assert users == {"releasebot": "releasebot-pass"}

    clean_env = {**os.environ, "HOME": str(tmp_path)}
    wrong = subprocess.run(
        [
            INDEX_TOOL,
            "--state-dir",
            str(STATE),
            "login",
            "--username",
            "releasebot",
            "--password",
            "wrong",
        ],
        env=clean_env,
        text=True,
        capture_output=True,
    )
    assert wrong.returncode != 0
    assert "Authentication failed" in wrong.stderr

    unauthenticated = subprocess.run(
        [
            INDEX_TOOL,
            "--state-dir",
            str(STATE),
            "upload",
            str(next((PROJECT / "dist").iterdir())),
        ],
        env=clean_env,
        text=True,
        capture_output=True,
    )
    assert unauthenticated.returncode != 0
    assert "Not logged in" in unauthenticated.stderr


def test_exact_new_version_installs_and_runs_from_local_index(tmp_path: Path):
    target = tmp_path / "site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--no-deps",
            "--index-url",
            INDEX_URL,
            "--target",
            str(target),
            "vectorops==0.1.1",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    env = {**os.environ, "PYTHONPATH": str(target)}
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from importlib.metadata import version; "
                "from vectorops import dotproduct; "
                "assert version('vectorops') == '0.1.1'; "
                "assert dotproduct([1,2,3], [4,5,6]) == 32; "
                "assert dotproduct([1.5,2.0], [2,4.0]) == 11.0"
            ),
        ],
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
