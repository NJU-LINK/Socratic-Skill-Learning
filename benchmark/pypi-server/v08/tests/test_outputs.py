import json
import subprocess
import tempfile
import urllib.request
from importlib import resources
from pathlib import Path


INDEX_URL = "http://localhost:3141/publisher/packages/+simple/"
PROJECT_SIMPLE_URL = INDEX_URL + "vectorops/"


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs)


def test_devpi_service_and_authenticated_user_exist():
    status = urllib.request.urlopen("http://localhost:3141/+status", timeout=10)
    assert status.status == 200

    with tempfile.TemporaryDirectory() as clientdir:
        run(["devpi", "--clientdir", clientdir, "use", "http://localhost:3141"])
        run(["devpi", "--clientdir", clientdir, "login", "publisher", "--password", "publish123"])
        indexes = run(["devpi", "--clientdir", clientdir, "index", "-l"]).stdout
        assert "publisher/packages" in indexes


def test_only_required_versions_are_published():
    html = urllib.request.urlopen(PROJECT_SIMPLE_URL, timeout=10).read().decode("utf-8")
    assert "vectorops-0.0.9-py3-none-any.whl" in html
    assert "vectorops-0.0.9.tar.gz" in html
    assert "vectorops-0.1.0-py3-none-any.whl" in html
    assert "vectorops-0.1.0.tar.gz" in html
    assert "vectorops-0.1.1" not in html
    assert "vectorops-0.0.8" not in html


def test_pinned_install_and_api_behavior():
    venv_dir = Path(tempfile.mkdtemp(prefix="vectorops-test-venv-"))
    try:
        run(["python3", "-m", "venv", str(venv_dir)])
        pip = venv_dir / "bin" / "pip"
        python = venv_dir / "bin" / "python"

        run([str(pip), "install", "--index-url", INDEX_URL, "vectorops==0.1.0"])

        script = """
import json
from importlib import resources
from vectorops import DotProductCalculator

default_calc = DotProductCalculator()
override_calc = DotProductCalculator(precision=6)
data = json.loads(resources.files('vectorops').joinpath('data/defaults.json').read_text())
result = {
    'default_precision': default_calc.precision,
    'override_precision': override_calc.precision,
    'default_value': default_calc.dotproduct([0.123456, 0.654321], [1.234567, 1.111111]),
    'override_value': override_calc.dotproduct([0.123456, 0.654321], [1.234567, 1.111111]),
    'data_precision': data['precision'],
}
print(json.dumps(result))
"""
        payload = json.loads(run([str(python), "-c", script]).stdout)

        assert payload["data_precision"] == 4
        assert payload["default_precision"] == 4
        assert payload["override_precision"] == 6
        assert payload["default_value"] == 0.8794
        assert payload["override_value"] == 0.879438
    finally:
        subprocess.run(["rm", "-rf", str(venv_dir)], check=True)
