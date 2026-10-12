#!/bin/bash

set -euo pipefail

script_dir="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$(dirname -- "$0")")"
test_dir="${TEST_DIR:-$script_dir/tests}"
if [ -d "$test_dir/tests" ]; then
    test_dir="$test_dir/tests"
elif [ ! -d "$test_dir" ] && [ -d /tests ]; then
    test_dir=/tests
fi
test_dir="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$test_dir")"

if ! command -v pytest >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
        uv tool install pytest >/tmp/pytest-install.log 2>&1 || uv tool install --force pytest >/tmp/pytest-install.log 2>&1
        export PATH="$HOME/.local/bin:$PATH"
    else
        sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
        sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pytest
    fi
fi

pytest -q "$test_dir"
