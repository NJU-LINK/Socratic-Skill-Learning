#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/repo
cd /app/repo
git init -q
git config user.name "TerminalBench"
git config user.email "tb@example.com"

# ---- main branch: 5 commits ----
echo "# Project" > README.md
git add README.md
git commit -q -m "chore: initial commit"
git branch -m main

echo "*.pyc" > .gitignore
git add .gitignore
git commit -q -m "chore: add gitignore"

cat > requirements.txt << 'REQ'
flask>=2.0
click>=8.0
REQ
git add requirements.txt
git commit -q -m "feat: add dependencies"

mkdir -p src
cat > src/main.py << 'MAIN'
def main():
    print("Hello, World!")
MAIN
git add src/main.py
git commit -q -m "feat: add main module"

cat > src/utils.py << 'UTIL'
def get_version():
    return "1.0.0"
UTIL
git add src/utils.py
git commit -q -m "feat: add utilities"

git tag v0.5 HEAD~2
git tag v1.0

# ---- feature-clean: 3 commits (branch from commit 3 - dependencies) ----
git checkout -q -b feature-clean HEAD~2
mkdir -p tests
touch tests/__init__.py
git add tests/__init__.py
git commit -q -m "chore: add test init"

cat > tests/test_main.py << 'EOF'
from src.main import main

def test_main():
    main()
EOF
git add tests/test_main.py
git commit -q -m "feat: add main tests"

cat > tests/test_utils.py << 'EOF'
from src.utils import get_version

def test_version():
    assert get_version() == "1.0.0"
EOF
git add tests/test_utils.py
git commit -q -m "feat: add util tests"

# ---- feature-secret: 4 commits (branch from commit 2 - gitignore) ----
git checkout -q main
git checkout -q -b feature-secret HEAD~3

mkdir -p src
touch src/__init__.py
git add src/__init__.py
git commit -q -m "chore: add src init"

echo "secret[orphaned_branch_leak]" > secret.txt
git add secret.txt
git commit -q -m "feat: add scratch notes"

cat > src/helper.py << 'EOF'
def help_func():
    return "helper"
EOF
git add src/helper.py
git commit -q -m "feat: add helper"

mkdir -p docs
cat > docs/notes.md << 'EOF'
# Notes
TODO: add documentation
EOF
git add docs/notes.md
git commit -q -m "docs: add notes"

# ---- delete feature-secret — its commits become dangling ----
git checkout -q main
git branch -D feature-secret
