import math
import pathlib
import subprocess
import sys
import tempfile
import urllib.request

APP_DIR = pathlib.Path("/app")
INDEX_ROOT = APP_DIR / "index-root"


def run(cmd):
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def wait_for_solution_server():
    index_url = "http://127.0.0.1:8080/simple/"

    for _ in range(50):
        try:
            with urllib.request.urlopen(index_url, timeout=1):
                return
        except Exception:
            continue

    raise AssertionError("solution did not leave a reachable static package index on port 8080")


def test_solution_creates_static_simple_index_and_sdist_only():
    simple_root = INDEX_ROOT / "simple"
    package_root = simple_root / "vectorops"

    assert simple_root.is_dir()
    assert package_root.is_dir()
    assert (simple_root / "index.html").read_text()
    package_index = (package_root / "index.html").read_text()
    assert "vectorops-0.1.0.tar.gz" in package_index
    package_files = sorted(path.name for path in package_root.iterdir() if path.is_file())
    assert package_files == ["index.html", "vectorops-0.1.0.tar.gz"]


def test_static_server_serves_simple_index_on_port_8080():
    wait_for_solution_server()

    with urllib.request.urlopen("http://127.0.0.1:8080/simple/", timeout=5) as response:
        body = response.read().decode()
    assert response.status == 200
    assert "vectorops/" in body

    with urllib.request.urlopen("http://127.0.0.1:8080/simple/vectorops/", timeout=5) as response:
        body = response.read().decode()
    assert response.status == 200
    assert "vectorops-0.1.0.tar.gz" in body


def test_pip_installs_from_local_index_only_and_exports_required_api():
    wait_for_solution_server()

    with tempfile.TemporaryDirectory() as tmpdir:
        target = pathlib.Path(tmpdir) / "site"
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-cache-dir",
                "--index-url",
                "http://127.0.0.1:8080/simple",
                "--target",
                str(target),
                "vectorops==0.1.0",
            ]
        )

        code = (
            "import math, sys; "
            f"sys.path.insert(0, {str(target)!r}); "
            "from vectorops import dotproduct, vector_length; "
            "assert dotproduct([1, 2, 3], [4, 5, 6]) == 32; "
            "assert math.isclose(vector_length([3, 4]), 5.0); "
            "assert math.isclose(vector_length([2, 3, 6]), 7.0)"
        )
        run([sys.executable, "-c", code])
