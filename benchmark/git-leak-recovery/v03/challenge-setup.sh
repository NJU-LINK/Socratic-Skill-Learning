#!/usr/bin/env bash
set -euo pipefail

mkdir -p repo
cd repo
git init -q
git config user.name "TerminalBench"
git config user.email "tb@example.com"

echo "demo project" > README.md
git add README.md
git commit -m "chore: init a1b2c3d4-e5f6-7890-abcd-ef1234567890"

echo "# Configuration" > config.md
git add config.md
git commit -m "feat: add configuration docs"

echo "secret[stash_leak_cleanup]" > secret.txt
git add secret.txt
git stash push -m "wip: scratch notes"

echo "updated content" >> README.md
git add README.md
git commit -m "docs: update readme"
