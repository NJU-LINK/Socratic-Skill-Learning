import hashlib
import os
import subprocess
import tempfile
import tomllib
import urllib.parse
import urllib.request
import venv
import zipfile
from email import message_from_string
from html.parser import HTMLParser
from pathlib import Path


INDEX_URL = "http://127.0.0.1:8080/simple/vectorops/"
STALE_WHEEL = Path("/app/prebuilt-dist/vectorops-0.1.0-py3-none-any.whl")
PACKAGE_SRC = Path("/app/package-src")


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(value)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_venv(tmp_path: Path) -> tuple[Path, Path]:
    env_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    bin_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    return env_dir, bin_dir


def fetch_simple_index() -> tuple[str, str]:
    with urllib.request.urlopen(INDEX_URL, timeout=5) as response:
        body = response.read().decode()
        status = response.status
    assert status == 200
    return body, INDEX_URL


def download_hosted_wheel() -> tuple[str, bytes]:
    body, base_url = fetch_simple_index()
    parser = LinkParser()
    parser.feed(body)

    candidates = []
    for href in parser.hrefs:
        candidate = urllib.parse.urljoin(base_url, href)
        if candidate.endswith(".whl") and "vectorops-0.1.0" in candidate:
            candidates.append(candidate)

    assert candidates, "simple index did not link to a vectorops wheel"

    for candidate in candidates:
        with urllib.request.urlopen(candidate, timeout=5) as response:
            wheel_bytes = response.read()
            if response.status == 200 and wheel_bytes:
                return candidate, wheel_bytes

    raise AssertionError("simple index links did not resolve to a downloadable wheel")


def wheel_contents(path: Path) -> dict[str, bytes]:
    contents = {}
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith(".dist-info/RECORD"):
                continue
            contents[name] = archive.read(name)
    return contents


def wheel_package_contents(path: Path) -> dict[str, bytes]:
    return {
        name: data
        for name, data in wheel_contents(path).items()
        if not name.startswith("vectorops-0.1.0.dist-info/")
    }


def wheel_metadata_message(path: Path):
    with zipfile.ZipFile(path) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata_text = archive.read(metadata_name).decode()
    return message_from_string(metadata_text)


def source_package_contents() -> dict[str, bytes]:
    package_root = PACKAGE_SRC / "src" / "vectorops"
    contents = {}
    for path in sorted(package_root.rglob("*")):
        if path.is_file():
            contents[str(path.relative_to(PACKAGE_SRC / "src"))] = path.read_bytes()
    return contents


def expected_project_metadata() -> dict[str, str]:
    pyproject = tomllib.loads((PACKAGE_SRC / "pyproject.toml").read_text())
    project = pyproject["project"]
    readme_path = PACKAGE_SRC / project["readme"]
    return {
        "Name": project["name"],
        "Version": project["version"],
        "Summary": project["description"],
        "Requires-Python": project["requires-python"],
        "Description": readme_path.read_text().strip(),
    }


def test_simple_index_links_to_a_downloadable_fresh_wheel():
    wheel_url, wheel_bytes = download_hosted_wheel()

    assert wheel_url.startswith("http://127.0.0.1:8080/")
    assert sha256_bytes(wheel_bytes) != sha256_file(STALE_WHEEL), "stale wheel was republished"


def test_hosted_wheel_matches_package_src_and_pyproject_metadata():
    _, wheel_bytes = download_hosted_wheel()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        hosted_wheel = tmp_path / "hosted.whl"
        hosted_wheel.write_bytes(wheel_bytes)

        assert wheel_package_contents(hosted_wheel) == source_package_contents(), (
            "hosted wheel does not package the exact source files from /app/package-src"
        )

        metadata = wheel_metadata_message(hosted_wheel)
        expected = expected_project_metadata()
        assert metadata["Name"] == expected["Name"]
        assert metadata["Version"] == expected["Version"]
        assert metadata["Summary"] == expected["Summary"]
        assert metadata["Requires-Python"] == expected["Requires-Python"]
        assert expected["Description"] in metadata.get_payload()


def test_pip_installs_corrected_package_from_local_index():
    with tempfile.TemporaryDirectory() as tmpdir:
        _, bin_dir = make_venv(Path(tmpdir))
        python_bin = bin_dir / "python"
        pip_bin = bin_dir / "pip"

        subprocess.run(
            [
                str(pip_bin),
                "install",
                "--no-cache-dir",
                "--index-url",
                "http://127.0.0.1:8080/simple",
                "vectorops==0.1.0",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        code = """
from vectorops import cosine_similarity, dotproduct

assert dotproduct([1, 2, 3], [4, 5, 6]) == 32
value = cosine_similarity([1, 0, 1], [1, 1, 0])
assert abs(value - 0.5) < 1e-12
print('ok')
"""
        completed = subprocess.run(
            [str(python_bin), "-c", code],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert completed.stdout.strip() == "ok"


def test_installed_distribution_does_not_come_from_prebuilt_dist_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        _, bin_dir = make_venv(Path(tmpdir))
        python_bin = bin_dir / "python"
        pip_bin = bin_dir / "pip"

        subprocess.run(
            [
                str(pip_bin),
                "install",
                "--no-cache-dir",
                "--index-url",
                "http://127.0.0.1:8080/simple",
                "vectorops==0.1.0",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        completed = subprocess.run(
            [
                str(python_bin),
                "-c",
                (
                    "import inspect, vectorops;"
                    "print(inspect.getfile(vectorops));"
                    "from pathlib import Path;"
                    "print(Path(inspect.getfile(vectorops)).resolve())"
                ),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        assert lines, "module path not reported"
        for line in lines:
            assert "/app/prebuilt-dist/" not in line
