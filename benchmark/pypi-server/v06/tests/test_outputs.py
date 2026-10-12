import json
import math
import subprocess
import tarfile
import tempfile
import time
import tomllib
import urllib.request
import venv
import zipfile
from pathlib import Path


PROJECT = Path("/app/vectorops-project")
DIST = PROJECT / "dist"
INDEX_URL = "http://localhost:8091/simple"


def run(command):
    return subprocess.run(command, check=True, text=True, capture_output=True)


def wait_for_index(path="/"):
    url = f"{INDEX_URL}{path}"
    last_error = None
    for _ in range(40):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return response.read().decode()
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise AssertionError(f"index was not reachable at {url}: {last_error}")


def install_in_fresh_environment():
    temporary = tempfile.TemporaryDirectory()
    environment = Path(temporary.name) / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin" / "python"
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--no-deps",
            "--index-url",
            INDEX_URL,
            "vectorops==0.1.0",
        ]
    )
    return temporary, python


def test_src_layout_and_metadata_are_explicit():
    pyproject = PROJECT / "pyproject.toml"
    package = PROJECT / "src" / "vectorops"

    assert pyproject.is_file()
    assert package.is_dir()
    metadata = tomllib.loads(pyproject.read_text())
    assert metadata["project"]["name"] == "vectorops"
    assert metadata["project"]["version"] == "0.1.0"
    assert metadata["tool"]["setuptools"]["package-dir"] == {"": "src"}
    assert (package / "__init__.py").is_file()


def test_wheel_sdist_and_index_represent_the_same_release():
    wheel = next(iter(sorted(DIST.glob("vectorops-0.1.0-*.whl"))), None)
    sdist = DIST / "vectorops-0.1.0.tar.gz"
    assert wheel is not None
    assert sdist.is_file()

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert "vectorops/__init__.py" in names
        assert any(name.endswith(".dist-info/METADATA") for name in names)

    with tarfile.open(sdist) as archive:
        names = set(archive.getnames())
        assert "vectorops-0.1.0/pyproject.toml" in names
        assert "vectorops-0.1.0/src/vectorops/__init__.py" in names

    page = wait_for_index("/vectorops/")
    assert wheel.name in page
    assert sdist.name in page


def test_fresh_install_exports_correct_numeric_behavior():
    temporary, python = install_in_fresh_environment()
    try:
        result = run(
            [
                str(python),
                "-c",
                (
                    "import json; "
                    "from vectorops import dotproduct, vectornorm; "
                    "print(json.dumps({"
                    "'dot': dotproduct([2, -1], [5, 4]), "
                    "'norm': vectornorm([1, 2, 2])"
                    "}))"
                ),
            ]
        )
        values = json.loads(result.stdout)
        assert values["dot"] == 6
        assert math.isclose(values["norm"], 3.0)
    finally:
        temporary.cleanup()


def test_fresh_install_enforces_declared_validation():
    temporary, python = install_in_fresh_environment()
    try:
        run(
            [
                str(python),
                "-c",
                """
from vectorops import dotproduct, vectornorm

cases = [
    (dotproduct, ([], []), ValueError),
    (dotproduct, ([1], []), ValueError),
    (dotproduct, ("x", [1]), TypeError),
    (dotproduct, ([1, "x"], [2, 3]), TypeError),
    (vectornorm, ([],), ValueError),
    (vectornorm, ("x",), TypeError),
    (vectornorm, ([1, "x"],), TypeError),
]
for function, arguments, expected in cases:
    try:
        function(*arguments)
    except expected:
        pass
    else:
        raise AssertionError(f"{function.__name__}{arguments!r} should raise {expected.__name__}")
""",
            ]
        )
    finally:
        temporary.cleanup()
