import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path


WORKDIR = Path.cwd()
PROJECTDIR = WORKDIR / "vectorops-project"
PYPROJECT = PROJECTDIR / "pyproject.toml"
PACKAGE_JSON = PROJECTDIR / "src" / "vectorops" / "constants.json"
SIMPLE_INDEX = "http://localhost:3141/packager/dev/+simple/"


def fetch_json(url):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def test_project_metadata_and_package_data_configuration():
    assert PYPROJECT.exists()
    assert PACKAGE_JSON.exists()
    data = tomllib.loads(PYPROJECT.read_text())

    assert data["project"]["name"] == "vectorops"
    assert data["project"]["version"] == "0.1.0"
    assert '0.5' in PACKAGE_JSON.read_text()


def test_devpi_simple_index_serves_vectorops():
    with urllib.request.urlopen(f"{SIMPLE_INDEX}vectorops/") as response:
        body = response.read().decode("utf-8")

    assert response.status == 200
    assert "vectorops-0.1.0" in body
    assert ".whl" in body or ".tar.gz" in body


def test_devpi_api_and_packager_stage_exist():
    root_api = fetch_json("http://localhost:3141/+api")
    user_config = fetch_json("http://localhost:3141/packager")
    stage_api = fetch_json("http://localhost:3141/packager/dev/+api")
    stage_config = fetch_json("http://localhost:3141/packager/dev")

    assert root_api["type"] == "apiconfig"
    assert root_api["result"]["login"] == "http://localhost:3141/+login"
    assert "push-register-project" in root_api["result"]["features"]

    assert user_config["type"] == "userconfig"
    assert user_config["result"]["username"] == "packager"
    assert "dev" in user_config["result"]["indexes"]

    assert stage_api["type"] == "apiconfig"
    assert stage_api["result"]["index"] == "http://localhost:3141/packager/dev"
    assert stage_api["result"]["simpleindex"] == SIMPLE_INDEX
    assert stage_api["result"]["pypisubmit"] == "http://localhost:3141/packager/dev/"

    assert stage_config["type"] == "indexconfig"
    assert stage_config["result"]["type"] == "stage"
    assert stage_config["result"]["bases"] == []
    assert stage_config["result"]["acl_upload"] == ["packager"]
    assert "vectorops" in stage_config["result"]["projects"]


def test_install_and_runtime_behavior_from_devpi():
    tempdir = Path(tempfile.mkdtemp(prefix="vectorops-install-"))
    try:
        venv_dir = tempdir / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

        pip = venv_dir / "bin" / "pip"
        python = venv_dir / "bin" / "python"

        subprocess.run(
            [
                str(pip),
                "install",
                "--index-url",
                SIMPLE_INDEX,
                "vectorops==0.1.0",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        result = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "from importlib import resources; "
                    "from vectorops import default_weights, dotproduct; "
                    "resource = resources.files('vectorops').joinpath('constants.json'); "
                    "print(dotproduct([1, 2.5, -1], [4, 2, 3])); "
                    "print(default_weights()); "
                    "print(resource.is_file())"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        assert lines[0] == "6.0"
        assert lines[1] == "[0.5, 1.5, -2.0, 4.0]"
        assert lines[2] == "True"
    finally:
        shutil.rmtree(tempdir)
