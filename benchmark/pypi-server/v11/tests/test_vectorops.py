from __future__ import annotations

import os
import pathlib
import subprocess
import tarfile
import time
import urllib.request
import venv


INDEX_ROOT = pathlib.Path("/var/local/vector-index")
PACKAGES_DIR = INDEX_ROOT / "packages"
PACKAGE_NAME = "vectorops"
PACKAGE_VERSION = "0.1.0"
BASE_URL = "http://127.0.0.1:9091"


def wait_for_index() -> str:
    url = f"{BASE_URL}/simple/{PACKAGE_NAME}/"
    last_error = None
    for _ in range(20):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read().decode()
        except Exception as exc:  # pragma: no cover - retry path
            last_error = exc
            time.sleep(1)
    raise AssertionError(f"package index never became reachable: {last_error}")


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, env=env, check=False)


def test_packages_directory_contains_only_the_required_sdist() -> None:
    assert PACKAGES_DIR.is_dir(), f"missing packages directory: {PACKAGES_DIR}"
    package_files = sorted(path.name for path in PACKAGES_DIR.iterdir() if path.is_file())
    assert package_files == ["vectorops-0.1.0.tar.gz"]
    with tarfile.open(PACKAGES_DIR / package_files[0]) as archive:
        members = set(archive.getnames())
    assert "vectorops-0.1.0/pyproject.toml" in members
    assert "vectorops-0.1.0/vectorops/__init__.py" in members


def test_simple_index_is_served_from_required_port() -> None:
    html = wait_for_index()
    assert PACKAGE_NAME in html.lower()


def test_install_command_works_from_local_index_only(tmp_path: pathlib.Path) -> None:
    wait_for_index()

    venv_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    bindir = "Scripts" if os.name == "nt" else "bin"
    pip_path = venv_dir / bindir / "pip"
    python_path = venv_dir / bindir / "python"

    env = os.environ.copy()
    env["PIP_NO_CACHE_DIR"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

    install = run(
        [
            str(pip_path),
            "install",
            "--index-url",
            f"{BASE_URL}/simple",
            f"{PACKAGE_NAME}=={PACKAGE_VERSION}",
        ],
        env=env,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    check = run(
        [
            str(python_path),
            "-c",
            (
                "from vectorops import dotproduct, squared_norm; "
                "import importlib.metadata; "
                "assert dotproduct([1, 1], [0, 1]) == 1; "
                "assert dotproduct([2, -3, 4], [5, 6, 0.5]) == -6; "
                "assert squared_norm([3, 4]) == 25; "
                "assert squared_norm([1.5, -2.0, 0]) == 6.25; "
                "assert importlib.metadata.version('vectorops') == '0.1.0'"
            ),
        ],
        env=env,
    )
    assert check.returncode == 0, check.stdout + check.stderr
