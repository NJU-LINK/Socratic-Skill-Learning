import subprocess
import tempfile
import urllib.request
import venv
import zipfile
from pathlib import Path


INDEX_ROOT = Path("/tmp/vectorops-index")


def test_simple_index_is_served_on_port_8080():
    root_html = urllib.request.urlopen("http://localhost:8080/simple/").read().decode()
    package_html = urllib.request.urlopen("http://localhost:8080/simple/vectorops/").read().decode()

    assert "vectorops/" in root_html
    assert "vectorops-0.1.0" in package_html


def test_wheel_is_present_and_contains_package_data():
    wheels = sorted((INDEX_ROOT / "simple" / "vectorops").glob("vectorops-0.1.0-*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())

    assert "vectorops/__init__.py" in names
    assert "vectorops/core.py" in names
    assert "vectorops/data/coefficient.txt" in names


def test_install_from_local_index_only_and_runtime_behavior():
    with tempfile.TemporaryDirectory() as tmpdir:
        env_dir = Path(tmpdir) / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        pip = env_dir / "bin" / "pip"
        python = env_dir / "bin" / "python"

        subprocess.run(
            [
                str(pip),
                "install",
                "--index-url",
                "http://localhost:8080/simple",
                "vectorops==0.1.0",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        result = subprocess.run(
            [
                str(python),
                "-c",
                "from vectorops import dotproduct, weighted_dotproduct; "
                "print(dotproduct([1, 2, 3], [4, 5, 6])); "
                "print(weighted_dotproduct([1, 2], [3, 4]))",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    assert result.stdout.splitlines() == ["32", "16.5"]


def test_public_api_imports_from_vectorops():
    code = (
        "from vectorops import dotproduct, weighted_dotproduct\n"
        "assert dotproduct([2, 3], [5, 7]) == 31\n"
        "assert weighted_dotproduct([2, 3], [5, 7]) == 46.5\n"
        "print('ok')\n"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        env_dir = Path(tmpdir) / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        pip = env_dir / "bin" / "pip"
        python = env_dir / "bin" / "python"

        subprocess.run(
            [
                str(pip),
                "install",
                "--index-url",
                "http://localhost:8080/simple",
                "vectorops==0.1.0",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        result = subprocess.run(
            [str(python), "-c", code],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    assert result.stdout.strip() == "ok"
