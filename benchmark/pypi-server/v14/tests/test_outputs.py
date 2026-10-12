import base64
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


INDEX_URL = "http://localhost:8080/simple"
PACKAGE_NAME = "vectorops"
PACKAGE_VERSION = "0.1.0"


def request(url: str, *, method: str = "GET", data: bytes | None = None, auth: tuple[str, str] | None = None):
    req = urllib.request.Request(url, data=data, method=method)
    if auth is not None:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    if data is not None:
        req.add_header("Content-Length", str(len(data)))
    return urllib.request.urlopen(req, timeout=3)


def fetch_text(url: str) -> str:
    deadline = time.time() + 10
    last_error = None
    while time.time() < deadline:
        try:
            with request(url) as response:
                return response.read().decode("utf-8")
        except Exception as exc:  # pragma: no cover - retry path
            last_error = exc
            time.sleep(0.2)
    raise AssertionError(f"failed to fetch {url}: {last_error}")


def package_links() -> list[str]:
    package_page = fetch_text(f"{INDEX_URL}/{PACKAGE_NAME}/")
    return re.findall(r'href="([^"]+)"', package_page)


def install_target() -> str:
    target_dir = tempfile.mkdtemp()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--index-url",
            INDEX_URL,
            "--target",
            target_dir,
            f"{PACKAGE_NAME}=={PACKAGE_VERSION}",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return target_dir


def test_simple_index_serves_only_the_built_wheel():
    root_page = fetch_text(f"{INDEX_URL}/")
    assert PACKAGE_NAME in root_page

    links = package_links()
    assert len(links) == 1
    assert links[0].endswith(".whl")
    assert all(not link.endswith(".tar.gz") for link in links)


def test_upload_endpoint_requires_expected_credentials():
    links = package_links()
    assert links, "expected a published wheel"

    artifact_path = links[0]
    artifact_url = f"http://localhost:8080{artifact_path}"
    with request(artifact_url) as response:
        payload = response.read()

    upload_url = f"http://localhost:8080/packages/{artifact_path.rsplit('/', 1)[-1]}"

    for auth in (None, ("uploader", "wrong-password")):
        try:
            with request(upload_url, method="PUT", data=payload, auth=auth):
                raise AssertionError("upload unexpectedly succeeded without valid credentials")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            assert exc.headers.get("WWW-Authenticate") == 'Basic realm="packages"'

    with request(upload_url, method="PUT", data=payload, auth=("uploader", "password")) as response:
        assert response.status == 201


def test_package_installs_from_local_index_and_exposes_dotproduct():
    target_dir = install_target()
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = target_dir

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.metadata;"
                    "from vectorops import dotproduct;"
                    "print(importlib.metadata.version('vectorops'));"
                    "print(dotproduct([1, 2, 3], [4, 5, 6]))"
                ),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        lines = result.stdout.strip().splitlines()
        assert lines == [PACKAGE_VERSION, "32"]
    finally:
        subprocess.run(["rm", "-rf", target_dir], check=True)


def test_installed_dotproduct_validates_lengths_and_numeric_inputs():
    target_dir = install_target()
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = target_dir

        validation_script = """
from vectorops import dotproduct

try:
    dotproduct([1, 2], [3])
except ValueError:
    pass
else:
    raise SystemExit('missing ValueError')

try:
    dotproduct([1, 'bad'], [3, 4])
except TypeError:
    pass
else:
    raise SystemExit('missing TypeError')
"""

        subprocess.run(
            [sys.executable, "-c", validation_script],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    finally:
        subprocess.run(["rm", "-rf", target_dir], check=True)
