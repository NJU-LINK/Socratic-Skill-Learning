#!/usr/bin/env bash
set -euo pipefail

rm -rf /app/repo
mkdir -p /app/repo
cd /app/repo

git init -q
git config user.name "Developer"
git config user.email "dev@example.com"

# Commit 1 — initial project setup
cat > README.md << 'EOF'
# Project
EOF
cat > .gitignore << 'EOF'
*.pyc
__pycache__/
EOF
git add README.md .gitignore
git commit -m "Initial project setup"

# Branch off before the secret
git branch develop

# Commit 2 — add main entry point
mkdir -p src
cat > src/main.py << 'PYEOF'
def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
PYEOF
git add src/main.py
git commit -m "Add main application entry point"

# Commit 3 — add config
cat > src/config.py << 'PYEOF'
import os

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
PORT = int(os.getenv("PORT", "8080"))
PYEOF
cat > requirements.txt << 'EOF'
flask==2.3.0
requests==2.31.0
EOF
git add src/config.py requirements.txt
git commit -m "Add configuration module"

# Commit 4 — SECRET INTRODUCED
echo "secret[accidental_commit_in_history]" > secret.txt
git add secret.txt
git commit -m "Add scratch notes"
git tag v1.0

# Commit 5 — add database module
cat > src/database.py << 'PYEOF'
import sqlite3

def get_connection(db_path):
    return sqlite3.connect(db_path)
PYEOF
git add src/database.py
git commit -m "Add database module"

# Commit 6 — update docs
cat > README.md << 'EOF'
# Project v2
A sample Python project.
EOF
git add README.md
git commit -m "Update project documentation"

# Commit 7 — remove secret from working tree
git rm secret.txt
echo "secret.txt" >> .gitignore
git add .gitignore
git commit -m "Remove sensitive data from working tree"

# Commit 8 — add processor
cat > src/processor.py << 'PYEOF'
def process_data(data):
    return {"status": "ok", "result": data}
PYEOF
git add src/processor.py
git commit -m "Add data processor"

# Commit 9 — add tests
mkdir -p tests
cat > tests/test_main.py << 'PYEOF'
def test_placeholder():
    assert True
PYEOF
git add tests/
git commit -m "Add test files"

# Commit 10 — finalize
cat > README.md << 'EOF'
# Project v2
A sample Python project.

## Overview
This project demonstrates a simple application setup.
EOF
git add README.md
git commit -m "Finalize project setup"

# Populate develop branch (no secret)
git checkout develop
mkdir -p src
cat > src/feature_flags.py << 'PYEOF'
FEATURES = {
    "new_ui": False,
    "beta_api": True,
}
PYEOF
git add src/feature_flags.py
git commit -m "Add feature flags"

cat > src/dev_config.py << 'PYEOF'
DEBUG = True
VERBOSE_LOGGING = True
PYEOF
git add src/dev_config.py
git commit -m "Add dev configuration"

# Return to main
git checkout master
