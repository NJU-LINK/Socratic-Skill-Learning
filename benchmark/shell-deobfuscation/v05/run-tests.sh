#!/bin/bash

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

# Fix apt sources for HTTP proxy (required before apt-get calls)
sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true

# Strategy 1: install pytest via uv (requires apt-get + curl, may need root)
if ! python3 -m pytest --version &>/dev/null 2>&1; then
    command -v curl &>/dev/null || apt-get update -qq 2>/dev/null && apt-get install -y -qq curl 2>/dev/null || true
    if command -v curl &>/dev/null 2>&1 && ! command -v uv &>/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh 2>/dev/null || true
    fi
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null 2>&1; then
        uv venv .tbench-testing 2>/dev/null || true
        . .tbench-testing/bin/activate 2>/dev/null || true
        uv pip install pytest 2>/dev/null || true
    fi
fi

# Strategy 2: install pytest via pip (get-pip.py, works without root)
if ! python3 -m pytest --version &>/dev/null 2>&1; then
    python3 -c "
import urllib.request, subprocess, sys
try:
    urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '/tmp/get-pip.py')
    subprocess.run([sys.executable, '/tmp/get-pip.py', '--user', '--break-system-packages'], check=True, capture_output=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--user', '--break-system-packages', 'pytest'], check=True, capture_output=True)
except Exception:
    sys.exit(1)
" 2>/dev/null || true
fi

# Run tests (pytest preferred, unittest fallback)
if python3 -m pytest --version &>/dev/null 2>&1; then
    exec python3 -m pytest "$TEST_DIR/test_outputs.py" -v --tb=long
else
    exec python3 -m unittest discover -v -s "$TEST_DIR" -p "test_*.py"
fi
