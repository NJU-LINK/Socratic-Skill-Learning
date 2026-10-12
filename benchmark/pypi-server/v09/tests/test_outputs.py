import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


INDEX_URL = "http://localhost:9090/simple"
ROOT_URL = "http://127.0.0.1:9090"
PUBLISHED_WHEEL = Path("/app/published-packages/vectorops-0.1.0-py3-none-any.whl")


def venv_bin(venv_dir: Path, name: str) -> str:
    if os.name == "nt":
        return str(venv_dir / "Scripts" / f"{name}.exe")
    return str(venv_dir / "bin" / name)


def create_environment(root: Path) -> tuple[str, str]:
    venv_dir = root / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    return venv_bin(venv_dir, "pip"), venv_bin(venv_dir, "python")


def test_simple_index_exposes_only_the_intended_wheel():
    with urllib.request.urlopen(f"{ROOT_URL}/simple/vectorops/", timeout=5) as response:
        body = response.read().decode()
    assert response.status == 200
    assert "vectorops-0.1.0-py3-none-any.whl" in body
    assert "vectorops-0.0.9" not in body
    assert PUBLISHED_WHEEL.is_file()


def test_exact_pinned_download_resolves_to_the_local_wheel():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        pip, _ = create_environment(root)
        download_dir = root / "downloads"
        subprocess.run(
            [
                pip,
                "download",
                "--no-cache-dir",
                "--no-deps",
                "--index-url",
                INDEX_URL,
                "vectorops==0.1.0",
                "-d",
                str(download_dir),
            ],
            check=True,
        )
        assert [path.name for path in download_dir.iterdir()] == [
            "vectorops-0.1.0-py3-none-any.whl"
        ]


def test_fresh_install_exposes_the_declared_runtime_behavior():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        pip, python = create_environment(root)
        subprocess.run(
            [
                pip,
                "install",
                "--no-cache-dir",
                "--no-deps",
                "--index-url",
                INDEX_URL,
                "vectorops==0.1.0",
            ],
            check=True,
        )
        result = subprocess.run(
            [
                python,
                "-c",
                (
                    "from vectorops import dotproduct; "
                    "print(dotproduct([1, 2, 3], [4, 5, 6])); "
                    "print(dotproduct([1.5, 2.0], [3, 4]))"
                ),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip().splitlines() == ["32", "12.5"]


def test_installed_package_rejects_mismatched_lengths():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        pip, python = create_environment(root)
        subprocess.run(
            [
                pip,
                "install",
                "--no-cache-dir",
                "--no-deps",
                "--index-url",
                INDEX_URL,
                "vectorops==0.1.0",
            ],
            check=True,
        )
        result = subprocess.run(
            [python, "-c", "from vectorops import dotproduct; dotproduct([1, 2], [3])"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "ValueError" in result.stderr


def test_upload_rejects_wrong_credentials():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "twine",
            "upload",
            "--non-interactive",
            "--repository-url",
            f"{ROOT_URL}/",
            "--username",
            "wrong",
            "--password",
            "wrong",
            str(PUBLISHED_WHEEL),
        ],
        capture_output=True,
        text=True,
    )
    combined = f"{result.stdout}\n{result.stderr}".lower()
    assert result.returncode != 0
    assert "403" in combined or "forbidden" in combined or "unauthorized" in combined
