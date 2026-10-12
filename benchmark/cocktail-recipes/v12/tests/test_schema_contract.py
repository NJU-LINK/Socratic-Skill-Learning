from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator


OUTPUT = Path("/app/output.json")
SCHEMA = Path("/app/format_spec.json")


def test_output_satisfies_public_schema() -> None:
    assert OUTPUT.exists(), "output.json not found"
    output = json.loads(OUTPUT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(output), key=lambda error: list(error.path))
    assert not errors, "; ".join(
        f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
        for error in errors
    )
