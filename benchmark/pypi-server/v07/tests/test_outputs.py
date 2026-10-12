import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse


ROOT = Path("/app")
DIST = ROOT / "dist"
INDEX_FILE = ROOT / "simple" / "vector-ops" / "index.html"
INDEX_URL = "http://localhost:8080/simple/vector-ops/"


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(value for key, value in attrs if key == "href")


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs)


def wait_for_index():
    last_error = None
    for _ in range(40):
        try:
            with urllib.request.urlopen(INDEX_URL, timeout=2) as response:
                if response.status == 200:
                    return response.read().decode()
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise AssertionError(f"index was not reachable: {last_error}")


def test_build_produces_wheel_and_sdist():
    names = sorted(path.name for path in DIST.iterdir() if path.is_file())
    assert any(name.endswith(".whl") for name in names)
    assert any(name.endswith(".tar.gz") for name in names)
    assert all("0.1.0" in name for name in names)


def test_live_simple_index_points_only_to_built_artifacts():
    html = wait_for_index()
    parser = AnchorParser()
    parser.feed(html)

    resolved = set()
    for href in parser.hrefs:
        target = urlparse(urljoin(INDEX_URL, href))
        assert target.scheme == "http"
        assert target.netloc == "localhost:8080"
        served_file = ROOT / target.path.lstrip("/")
        assert served_file.is_file()
        resolved.add(served_file.resolve())

    built = {path.resolve() for path in DIST.iterdir() if path.is_file()}
    assert resolved == built
    assert INDEX_FILE.is_file()


def test_fresh_install_uses_distribution_name_and_public_api():
    wait_for_index()
    with tempfile.TemporaryDirectory() as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / "bin" / "python"
        pip = environment / "bin" / "pip"

        run(
            [
                str(pip),
                "install",
                "--index-url",
                "http://localhost:8080/simple",
                "--no-cache-dir",
                "--no-deps",
                "vector-ops==0.1.0",
            ],
            env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
        )

        run(
            [
                str(python),
                "-c",
                """
from importlib.metadata import version
from vectorops import dotproduct

assert version("vector-ops") == "0.1.0"
assert dotproduct([1, 2, 3], [4, 5, 6]) == 32
cases = [
    (("x", [1]), TypeError),
    (([1], "x"), TypeError),
    (([1, "x"], [2, 3]), TypeError),
    (([1, 2], [3]), ValueError),
]
for arguments, expected in cases:
    try:
        dotproduct(*arguments)
    except expected:
        pass
    else:
        raise AssertionError(f"expected {expected.__name__} for {arguments!r}")
""",
            ]
        )
