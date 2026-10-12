#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/repo
cd /app/repo

git init -q
git config user.name "TB"
git config user.email "tb@example.com"
git branch -M main

# --- main: 5 clean commits ---
echo "# Project" > README.md
git add README.md && git commit -m "chore: init"

echo "print('hello world')" > main.py
git add main.py && git commit -m "feat: add main entry"

printf 'DEBUG=true\n' > .env
git add .env && git commit -m "chore: add env config"

echo "version=1.0.0" > VERSION
git add VERSION && git commit -m "docs: set version"

echo "import sys" > utils.py
git add utils.py && git commit -m "feat: add utils module"

# --- feature: 5 commits (clean, no secret) ---
git checkout -b feature
echo "feature_a" > feature_a.py && git add feature_a.py && git commit -m "feat: feature a"
echo "feature_b" > feature_b.py && git add feature_b.py && git commit -m "feat: feature b"
echo "feature_c" > feature_c.py && git add feature_c.py && git commit -m "feat: feature c"
echo "feature_d" > feature_d.py && git add feature_d.py && git commit -m "feat: feature d"
echo "feature_e" > feature_e.py && git add feature_e.py && git commit -m "feat: feature e"

# --- Back to main, modify .env to create divergence ---
git checkout main
printf 'DEBUG=false\n' > .env
git add .env && git commit -m "chore: disable debug"

# --- Create detached commit with the secret ---
# Detach from the parent of the .env change (so .env still has DEBUG=true)
git checkout --detach HEAD~1

printf 'DEBUG=true\nLOGGING=on\n' > .env
printf 'secret[cherry_pick_gone_wrong]' > secret.txt
git add .env secret.txt
git commit -m "feat: add logging and secret config"

DETACHED_COMMIT=$(git rev-parse HEAD)

# --- Cherry-pick detached commit onto main (will conflict on .env) ---
git checkout main
git cherry-pick "$DETACHED_COMMIT" || true

# Resolve conflict on .env (keep main's version), accept secret.txt from cherry-pick
printf 'DEBUG=false\n' > .env
git add .env
GIT_EDITOR=true git cherry-pick --continue || true

# --- Revert the cherry-pick ---
git revert HEAD --no-edit

# --- Remove both cherry-pick and revert from branch history ---
# This makes them dangling — only reachable via reflog
git reset --hard HEAD~2

# --- Add clean commits after ---
echo "post-cleanup task" > task.txt
git add task.txt && git commit -m "chore: add task tracking"

echo "1.0.1" > VERSION
git add VERSION && git commit -m "docs: bump version"
