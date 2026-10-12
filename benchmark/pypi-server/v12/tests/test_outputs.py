import base64
import math
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import venv


PROJECT = pathlib.Path("/app/vector-ops-work/vector-ops-project")
DIST = PROJECT / "dist"
ROOT_URL = "http://localhost:8080"
INDEX_URL = f"{ROOT_URL}/simple"


def run(command):
    return subprocess.run(command, check=True, text=True, capture_output=True)


def upload_request(artifact: pathlib.Path, *, authenticated: bool):
    boundary = "asset-gate-upload-boundary"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name=":action"\r\n\r\n',
            b"file_upload\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="protocol_version"\r\n\r\n',
            b"1\r\n",
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="content"; filename="{artifact.name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode(),
            artifact.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if authenticated:
        token = base64.b64encode(b"publisher:upload-secret").decode()
        headers["Authorization"] = f"Basic {token}"
    return urllib.request.Request(
        f"{ROOT_URL}/legacy/",
        data=body,
        method="POST",
        headers=headers,
    )


def test_dist_contains_wheel_and_sdist():
    names = sorted(path.name for path in DIST.iterdir() if path.is_file())
    assert len(names) >= 2
    assert any(name.endswith(".whl") for name in names)
    assert any(name.endswith(".tar.gz") for name in names)
    assert all(name.startswith("vector_ops-0.1.0") for name in names)


def test_upload_endpoint_enforces_and_accepts_declared_credentials():
    artifact = next(DIST.glob("*.whl"))
    with pytest_raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(upload_request(artifact, authenticated=False))
    assert error.value.code == 401

    with urllib.request.urlopen(upload_request(artifact, authenticated=True)) as response:
        assert response.status == 200


def test_simple_index_serves_all_built_artifacts_exactly():
    root = urllib.request.urlopen(f"{INDEX_URL}/").read().decode()
    page = urllib.request.urlopen(f"{INDEX_URL}/vector-ops/").read().decode()
    assert "vector-ops" in root

    names = sorted(path.name for path in DIST.iterdir() if path.is_file())
    assert all(name in page for name in names)
    assert re.search(r'href="/packages/vector_ops-0\.1\.0[^"]+"', page)
    for name in names:
        served = urllib.request.urlopen(f"{ROOT_URL}/packages/{name}").read()
        assert served == (DIST / name).read_bytes()


def test_fresh_install_uses_distribution_name_and_runtime_api():
    with tempfile.TemporaryDirectory() as temporary:
        environment = pathlib.Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / "bin" / "python"
        pip = environment / "bin" / "pip"

        run(
            [
                str(pip),
                "install",
                "--no-cache-dir",
                "--no-deps",
                "--index-url",
                INDEX_URL,
                "vector-ops==0.1.0",
            ]
        )
        result = run(
            [
                str(python),
                "-c",
                (
                    "import json, math; "
                    "from importlib.metadata import version; "
                    "from vectorops import dotproduct, cosine_similarity; "
                    "print(json.dumps({"
                    "'version': version('vector-ops'), "
                    "'dot': dotproduct([1,2,3], [4,5,6]), "
                    "'cos': cosine_similarity([1,0], [1,1])"
                    "}))"
                ),
            ]
        )
        import json

        values = json.loads(result.stdout)
        assert values["version"] == "0.1.0"
        assert values["dot"] == 32
        assert math.isclose(values["cos"], 1 / math.sqrt(2), rel_tol=1e-12)


class pytest_raises:
    def __init__(self, expected):
        self.expected = expected
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            raise AssertionError(f"expected {self.expected.__name__}")
        if not issubclass(exc_type, self.expected):
            return False
        self.value = exc
        return True
