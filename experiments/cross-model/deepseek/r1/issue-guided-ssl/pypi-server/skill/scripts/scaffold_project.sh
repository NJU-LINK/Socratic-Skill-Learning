#!/usr/bin/env bash
# Stage 2 helper (optional): scaffold a minimal src-layout project when the
# task workspace is empty. For real tasks the function bodies and exports
# almost always need manual authoring afterwards -- this only establishes the
# build metadata + import surface skeleton.
#
# Env: SRC_DIR, PKG_NAME (distribution name), PKG_VERSION, IMPORT_NAME
#      (default: PKG_NAME with '-' -> '_'), MODULES (comma-separated module
#      file names, default "_core").
set -euo pipefail

SRC_DIR="${SRC_DIR:-/app}"
PKG_NAME="${PKG_NAME:?PKG_NAME required}"
PKG_VERSION="${PKG_VERSION:-0.1.0}"
IMPORT_NAME="${IMPORT_NAME:-$(printf '%s' "$PKG_NAME" | tr '-' '_')}"
MODULES="${MODULES:-_core}"

mkdir -p "$SRC_DIR/src/$IMPORT_NAME"
cat > "$SRC_DIR/pyproject.toml" <<EOF
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "$PKG_NAME"
version = "$PKG_VERSION"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
EOF

for m in $(printf '%s' "$MODULES" | tr ',' ' '); do
  [ "$m" = "__init__" ] && continue
  [ -f "$SRC_DIR/src/$IMPORT_NAME/$m.py" ] || printf '"""%s."""\n' "$m" > "$SRC_DIR/src/$IMPORT_NAME/$m.py"
done

[ -f "$SRC_DIR/src/$IMPORT_NAME/__init__.py" ] || cat > "$SRC_DIR/src/$IMPORT_NAME/__init__.py" <<EOF
"""${IMPORT_NAME} public API."""
__version__ = "$PKG_VERSION"
EOF

echo "AUTHOR: scaffolded src-layout project in $SRC_DIR (import name: $IMPORT_NAME, modules: $MODULES)"
echo "AUTHOR: FILL IN function bodies and re-export the public surface from __init__.py, then rebuild."