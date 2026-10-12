#!/usr/bin/env bash
set -euo pipefail

rm -rf /app/repo
mkdir -p /app/repo
cd /app/repo

git init -q
git branch -m main
git config user.name "Developer"
git config user.email "dev@example.com"

# ============================================================
# main branch — 20 commits
# ============================================================

cat > README.md << 'EOF'
# Large Monorepo
A multi-module project.
EOF
cat > .gitignore << 'EOF'
*.pyc
__pycache__/
.env
EOF
git add README.md .gitignore
git commit -m "Initial commit: project scaffolding"

mkdir -p src/core src/utils tests docs

cat > src/core/__init__.py << 'EOF'
# core module
EOF
git add src/core/__init__.py
git commit -m "Add core module structure"

cat > src/core/config.py << 'PYEOF'
import os
class Config:
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    PORT = int(os.getenv("PORT", "8080"))
PYEOF
git add src/core/config.py
git commit -m "Add configuration module"

cat > src/core/models.py << 'PYEOF'
from dataclasses import dataclass
@dataclass
class User:
    id: int; name: str; email: str
PYEOF
git add src/core/models.py
git commit -m "Add data models"

cat > src/core/database.py << 'PYEOF'
import sqlite3
def get_connection(db_path):
    return sqlite3.connect(db_path)
def init_db(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    conn.commit()
PYEOF
git add src/core/database.py
git commit -m "Add database layer"

cat > src/utils/__init__.py << 'EOF'
# utils module
EOF
cat > src/utils/helpers.py << 'PYEOF'
import hashlib
def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()
PYEOF
git add src/utils/
git commit -m "Add utility functions"

cat > src/core/service.py << 'PYEOF'
from .models import User
from .database import get_connection, init_db
class UserService:
    def create_user(self, name, email):
        conn = get_connection(":memory:")
        init_db(conn)
        conn.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
        return User(id=1, name=name, email=email)
PYEOF
git add src/core/service.py
git commit -m "Add business logic service"

cat > requirements.txt << 'EOF'
flask==3.0.0
gunicorn==21.2.0
requests==2.31.0
sqlalchemy==2.0.23
EOF
git add requirements.txt
git commit -m "Add project dependencies"

cat > setup.py << 'PYEOF'
from setuptools import setup, find_packages
setup(name="monorepo", version="0.1.0", packages=find_packages())
PYEOF
git add setup.py
git commit -m "Add package setup"

cat > Makefile << 'EOF'
.PHONY: install test
install:
	pip install -r requirements.txt
test:
	python -m pytest tests/
EOF
git add Makefile
git commit -m "Add Makefile with common tasks"

# Tag v1.0 on clean main
git tag -a v1.0 -m "Release v1.0 - initial release"
# Anchor for experiment branch creation
git tag anchor-experiment

# Continue main commits
cat > src/core/auth.py << 'PYEOF'
class AuthService:
    def __init__(self):
        self._users = {}
    def register(self, user):
        self._users[user.id] = user
    def login(self, email, password):
        for u in self._users.values():
            if u.email == email:
                return u
        return None
PYEOF
git add src/core/auth.py
git commit -m "Add authentication service"

cat > src/core/cache.py << 'PYEOF'
import time
class Cache:
    def __init__(self, ttl=300):
        self._store = {}; self._ttl = ttl
    def get(self, key):
        if key in self._store:
            val, exp = self._store[key]
            if time.time() < exp:
                return val
            del self._store[key]
        return None
    def set(self, key, value):
        self._store[key] = (value, time.time() + self._ttl)
PYEOF
git add src/core/cache.py
git commit -m "Add caching layer"

cat > src/core/validators.py << 'PYEOF'
import re
def validate_email(email):
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None
PYEOF
git add src/core/validators.py
git commit -m "Add input validators"

cat > tests/test_core.py << 'PYEOF'
def test_config():
    from src.core.config import Config
    assert Config.DEBUG is False
PYEOF
git add tests/
git commit -m "Add core unit tests"

cat > docs/api.md << 'EOF'
# API Documentation
## Endpoints
- GET /health
- POST /users
EOF
git add docs/
git commit -m "Add API documentation"

cat > src/main.py << 'PYEOF'
from src.core.config import Config
from src.core.database import get_connection, init_db
def main():
    cfg = Config()
    conn = get_connection(cfg.DB_URL)
    init_db(conn)
    print(f"Server starting on port {cfg.PORT}")
if __name__ == "__main__":
    main()
PYEOF
git add src/main.py
git commit -m "Add application entry point"

cat > README.md << 'EOF'
# Large Monorepo
A multi-module project with several components.
## Modules
- core: business logic and data models
- utils: helper functions
## Setup
make install && make test
EOF
git add README.md
git commit -m "Update project README"

cat > CONTRIBUTING.md << 'EOF'
# Contributing
Please follow existing code style and add tests for new features.
EOF
git add CONTRIBUTING.md
git commit -m "Add contributing guidelines"

cat > src/core/middleware.py << 'PYEOF'
import time
class TimingMiddleware:
    def process_request(self):
        self.start = time.time()
    def process_response(self):
        elapsed = time.time() - self.start
        print(f"Request took {elapsed:.3f}s")
PYEOF
git add src/core/middleware.py
git commit -m "Add request timing middleware"

cat > src/core/exceptions.py << 'PYEOF'
class AppError(Exception): pass
class NotFoundError(AppError): pass
class ValidationError(AppError): pass
PYEOF
git add src/core/exceptions.py
git commit -m "Add custom exception classes"

cat > src/__init__.py << 'EOF'
# src package
EOF
git add src/__init__.py
git commit -m "Add src package init"

# Anchor for feature-a and feature-b branch creation
# (at a mid-point before final commits)
git tag anchor-branches

# ============================================================
# feature-a branch — 15 commits (will be merged into main)
# ============================================================
git checkout -b feature-a anchor-branches
mkdir -p src/feature_a
for i in $(seq 1 15); do
    cat > "src/feature_a/module_a${i}.py" << EOF
# Module A${i}
EOF
    git add "src/feature_a/module_a${i}.py"
    git commit -m "feat(feature-a): Add module A${i}"
done

# ============================================================
# feature-b branch — 10 commits (not merged, separate)
# ============================================================
git checkout -b feature-b anchor-branches
mkdir -p src/feature_b
for i in $(seq 1 10); do
    cat > "src/feature_b/module_b${i}.py" << EOF
# Module B${i}
EOF
    git add "src/feature_b/module_b${i}.py"
    git commit -m "feat(feature-b): Add module B${i}"
done

# ============================================================
# Merge feature-a into main, tag v2.0
# ============================================================
git checkout main
git merge feature-a --no-ff -m "Merge feature-a into main"
git tag -a v2.0 -m "Release v2.0 - with feature-a integration"

# ============================================================
# experiment branch — 8 commits (contains the secret, then deleted)
# ============================================================
git checkout -b experiment anchor-experiment
mkdir -p src/experiment
for i in $(seq 1 7); do
    cat > "src/experiment/exp_${i}.py" << EOF
# Experiment module ${i}
EOF
    git add "src/experiment/exp_${i}.py"
    git commit -m "feat(experiment): Add experiment module ${i}"
done

# The secret commit
echo "secret[tagged_and_orphaned]" > secret.txt
git add secret.txt
git commit -m "Add experimental scratch file"

# Annotated tag on the secret commit with secret also in tag message
git tag -a v0.1-experiment -m "Experiment branch snapshot secret[tagged_and_orphaned]"

# ============================================================
# Cleanup: delete experiment branch, set ORIG_HEAD, remove anchors
# ============================================================
git checkout main
git branch -D experiment
git tag -d anchor-experiment anchor-branches

# Set ORIG_HEAD via a test merge attempt
git merge --no-commit feature-b 2>/dev/null || true
git merge --abort 2>/dev/null || true

cd /
