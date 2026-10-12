#!/bin/bash
set -euo pipefail

test_dir="${TEST_DIR:-/tests}"
if [ -d "$test_dir/tests" ]; then
  test_dir="$test_dir/tests"
elif [ ! -d "$test_dir" ] && [ -d /tests ]; then
  test_dir=/tests
fi
test_dir="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$test_dir")"

solution=""
for candidate in /app/solution.sh /tests/solution.sh "$test_dir/../solution.sh"; do
  if [ -f "$candidate" ]; then
    solution="$candidate"
    break
  fi
done
if [ -n "$solution" ]; then
  bash "$solution"
fi

venv_dir=/tmp/filter-js-tests-venv
if [ ! -x "$venv_dir/bin/python" ]; then
  rm -rf "$venv_dir"
  python3 -m venv "$venv_dir"
fi
"$venv_dir/bin/pip" install --quiet pytest beautifulsoup4 selenium
"$venv_dir/bin/python" -m pytest -q "$test_dir"
