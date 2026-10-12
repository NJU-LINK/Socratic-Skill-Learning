#!/usr/bin/env bash
set -euo pipefail

cd /app
mkdir -p repo
cd repo
git init -q
git config user.name "TerminalBench"
git config user.email "tb@example.com"

echo "# Project" > README.md
git add README.md
git commit -m "chore: init 7a8b9c0d-1234-5678-abcd-ef0123456789"

echo "config=production" > config.ini
git add config.ini
git commit -m "chore: add config"

# Create submodule with a dangling secret commit
mkdir -p lib/secrets
cd /app/repo/lib/secrets
git init -q
git config user.name "TerminalBench"
git config user.email "tb@example.com"

echo "library code" > lib.py
git add lib.py
git commit -m "chore: init lib 8b9c0d1e-2345-6789-abcd-ef0123456789"

echo "secret[submodule_leak_found]" > secret.key
git add secret.key
git commit -m "chore: add secret.key"

git reset --hard HEAD~1

# Add submodule to main repo
cd /app/repo
git submodule add /app/repo/lib/secrets lib/secrets
git add .gitmodules lib/secrets
git commit -m "chore: add secrets submodule"
