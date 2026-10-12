#!/bin/bash
set -euo pipefail

sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources

apt-get update
apt-get install -y gcc libc6-dev python3-pip python3-venv wabt

venv_dir=/tmp/wasm-pipeline-tests-venv

if [ ! -x "$venv_dir/bin/python" ]; then
  rm -rf "$venv_dir"
  python3 -m venv "$venv_dir"
fi

if ! "$venv_dir/bin/python" -m pytest --version >/dev/null 2>&1; then
  "$venv_dir/bin/pip" install pytest
fi

if ! "$venv_dir/bin/python" -c 'import wasmtime' >/dev/null 2>&1; then
  "$venv_dir/bin/pip" install wasmtime
fi

test_dir="${TEST_DIR:-/tests}"
if [ -d "$test_dir/tests" ]; then
  test_dir="$test_dir/tests"
elif [ ! -d "$test_dir" ] && [ -d /tests ]; then
  test_dir=/tests
fi
"$venv_dir/bin/python" -m pytest -q "$test_dir"
