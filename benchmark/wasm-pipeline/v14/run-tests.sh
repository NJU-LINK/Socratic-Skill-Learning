#!/bin/bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test_dir="$script_dir/tests"

if [ ! -d "$test_dir" ] && [ -d /tests ]; then
    test_dir=/tests
fi

test_dir=$(realpath "$test_dir")

pytest -q "$@" "$test_dir"
