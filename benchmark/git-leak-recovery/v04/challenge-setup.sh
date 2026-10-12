#!/usr/bin/env bash
set -euo pipefail

mkdir -p repo
cd repo
git init -q
git config user.name "TerminalBench"
git config user.email "tb@example.com"
git branch -m main

echo "Welcome to the team!" > README.md
git add README.md
git commit -m "chore: initial commit 8a1f3c9b"

git checkout -b feature

echo "api_key = secret[stashed_away]" > credentials.cfg
git add credentials.cfg

git stash

git stash drop

git checkout main

echo "Project setup complete" >> README.md
git add README.md
git commit -m "docs: update readme"
