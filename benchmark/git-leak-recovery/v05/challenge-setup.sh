#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/repo
cd /app/repo
git init -q
git config user.name "TestUser"
git config user.email "test@example.com"

# Commit 1
echo "# Project" > README.md
git add README.md
git commit -m "Initial commit"

# Commit 2
echo "def feature(): pass" > feature.py
git add feature.py
git commit -m "Add feature module"

# Commit 3
echo '{"version": 1}' > config.json
git add config.json
git commit -m "Add config"

# Commit 4 — add secret alongside a legitimate file
echo "secret[amended_and_forgotten]" > secret.txt
echo "name,value" > data.csv
echo "x,1" >> data.csv
git add secret.txt data.csv
git commit -m "Add data and scratch notes"

# Amend commit 4: remove just the secret file, fold into same commit
git rm secret.txt
git commit --amend --no-edit

# Commit 5 — final innocent change
echo "// TODO items" > notes.md
git add notes.md
git commit -m "Add notes"
