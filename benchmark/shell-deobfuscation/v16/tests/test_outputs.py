import json
import stat
from pathlib import Path


SUSPICIOUS = Path("/app/suspicious_script.sh")
CLEAN = Path("/app/clean.sh")
SNAPSHOT = Path("/opt/task-input/suspicious_script.sh")
EXPECTED = Path("/tests/expected_clean.sh")
CONTRACT = json.loads(Path("/tests/contract.json").read_text(encoding="utf-8"))


def validate_benchmark_fixture():
    assert SNAPSHOT.is_file()
    assert EXPECTED.is_file()
    content = SNAPSHOT.read_bytes()
    assert len(content) >= CONTRACT["minimum_input_bytes"]
    for marker in CONTRACT["required_input_markers"]:
        assert marker.encode() in content
    for marker in CONTRACT["forbidden_plaintext_markers"]:
        assert marker.encode() not in content


validate_benchmark_fixture()


def test_clean_script_exists():
    assert CLEAN.is_file()


def test_suspicious_script_remains():
    assert SUSPICIOUS.is_file()


def test_clean_script_is_the_exact_recovered_payload():
    assert CLEAN.read_bytes() == EXPECTED.read_bytes()


def test_clean_script_is_non_executable():
    execute_mask = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    assert not (CLEAN.stat().st_mode & execute_mask)


def test_suspicious_script_is_non_executable():
    execute_mask = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    assert not (SUSPICIOUS.stat().st_mode & execute_mask)


def test_suspicious_script_bytes_are_unchanged():
    assert SUSPICIOUS.read_bytes() == SNAPSHOT.read_bytes()


def test_neither_script_was_executed():
    for path in CONTRACT["side_effect_paths"]:
        assert not Path(path).exists(), f"execution side effect exists: {path}"
