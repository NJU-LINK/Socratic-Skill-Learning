#!/bin/bash
set -euo pipefail

cd /app

DEVPI_SERVER_DIR=/app/devpi-data
DEVPI_CLIENT_DIR=/app/.devpi-client
DEVPI_URL=http://localhost:3141
WORK_DIR=/tmp/vectorops-build
PROJECT_DIR="$WORK_DIR/vectorops_project"
DIST_DIR="$WORK_DIR/dist"

mkdir -p "$DEVPI_SERVER_DIR" "$DEVPI_CLIENT_DIR" "$PROJECT_DIR/src/vectorops/core" "$PROJECT_DIR/src/vectorops/data" "$DIST_DIR"

cat <<'EOF' > "$PROJECT_DIR/README.md"
# vectorops

Small vector operations package for local package index testing.
EOF

cat <<'EOF' > "$PROJECT_DIR/pyproject.toml"
[build-system]
requires = ["setuptools>=75.6.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vectorops"
version = "0.1.0"
description = "Vector operations package for local devpi publishing"
readme = "README.md"
requires-python = ">=3.13"
authors = [
  { name = "Task Author" }
]

[tool.setuptools]
include-package-data = true

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
vectorops = ["data/*.json"]
EOF

cat <<'EOF' > "$PROJECT_DIR/src/vectorops/__init__.py"
from vectorops.api import DotProductCalculator

__all__ = ["DotProductCalculator"]
EOF

cat <<'EOF' > "$PROJECT_DIR/src/vectorops/api.py"
from vectorops.core.calculator import DotProductCalculator

__all__ = ["DotProductCalculator"]
EOF

cat <<'EOF' > "$PROJECT_DIR/src/vectorops/core/__init__.py"
from vectorops.core.calculator import DotProductCalculator

__all__ = ["DotProductCalculator"]
EOF

cat <<'EOF' > "$PROJECT_DIR/src/vectorops/core/calculator.py"
import json
from importlib.resources import files


def _load_default_precision() -> int:
    data_path = files("vectorops").joinpath("data/defaults.json")
    with data_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return int(payload["precision"])


class DotProductCalculator:
    def __init__(self, precision: int | None = None) -> None:
        self.precision = _load_default_precision() if precision is None else int(precision)

    def dotproduct(self, left: list[int | float], right: list[int | float]) -> float:
        if len(left) != len(right):
            raise ValueError("left and right vectors must have the same length")
        total = sum(a * b for a, b in zip(left, right))
        return round(float(total), self.precision)
EOF

cat <<'EOF' > "$PROJECT_DIR/src/vectorops/data/defaults.json"
{
  "precision": 4
}
EOF

for version in 0.0.9 0.1.0; do
    python3 - <<PY
from pathlib import Path

pyproject = Path("$PROJECT_DIR/pyproject.toml")
lines = pyproject.read_text().splitlines()
for index, line in enumerate(lines):
    if line.startswith("version = "):
        lines[index] = f'version = "$version"'
        break
pyproject.write_text("\n".join(lines) + "\n")
PY
    python3 -m build "$PROJECT_DIR" --outdir "$DIST_DIR"
done

if [ ! -f "$DEVPI_SERVER_DIR/.serverversion" ]; then
    devpi-init --serverdir "$DEVPI_SERVER_DIR" --root-passwd rootpass
fi

if pgrep -f "devpi-server.*3141" >/dev/null 2>&1; then
    pkill -f "devpi-server.*3141"
    sleep 1
fi

nohup devpi-server --serverdir "$DEVPI_SERVER_DIR" --host 0.0.0.0 --port 3141 >/tmp/devpi-server.log 2>&1 &

for _ in $(seq 1 60); do
    if curl -fsS "$DEVPI_URL/+status" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

curl -fsS "$DEVPI_URL/+status" >/dev/null

devpi --clientdir "$DEVPI_CLIENT_DIR" use "$DEVPI_URL"
devpi --clientdir "$DEVPI_CLIENT_DIR" login root --password rootpass

if ! devpi --clientdir "$DEVPI_CLIENT_DIR" user -l | grep -qx 'publisher'; then
    devpi --clientdir "$DEVPI_CLIENT_DIR" user -c publisher password=publish123
else
    devpi --clientdir "$DEVPI_CLIENT_DIR" user -m publisher password=publish123
fi

if ! devpi --clientdir "$DEVPI_CLIENT_DIR" index -l | grep -qx 'publisher/packages'; then
    devpi --clientdir "$DEVPI_CLIENT_DIR" index -c publisher/packages bases=root/pypi
fi

devpi --clientdir "$DEVPI_CLIENT_DIR" login publisher --password publish123
devpi --clientdir "$DEVPI_CLIENT_DIR" use publisher/packages
devpi --clientdir "$DEVPI_CLIENT_DIR" upload --from-dir "$DIST_DIR"
