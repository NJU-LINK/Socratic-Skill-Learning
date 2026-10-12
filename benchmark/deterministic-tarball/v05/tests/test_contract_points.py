import os
from pathlib import Path


def test_build_entrypoint_is_present_and_executable():
    build_script = Path("/app/build.sh")
    assert build_script.is_file()
    assert os.access(build_script, os.X_OK)
