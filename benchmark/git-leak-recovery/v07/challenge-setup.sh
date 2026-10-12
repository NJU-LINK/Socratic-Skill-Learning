#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/repo
cd /app/repo

git init -q --initial-branch=main
git config user.name "TerminalBench"
git config user.email "tb@example.com"

echo "common content" > shared.txt
git add shared.txt
git commit -q -m "Initial commit"

git checkout -q -b feature

echo "feature content" > shared.txt
echo "password = secret[merge_abort_leak_99]" > credentials.txt
git add shared.txt credentials.txt
git commit -q -m "Add feature changes"

git checkout -q main

echo "main content" > shared.txt
git add shared.txt
git commit -q -m "Add main changes"

set +e
git merge feature 2>&1 || true
set -e

SECRET_HASH=$(cat .git/MERGE_HEAD)
git merge --abort 2>/dev/null || true

git update-ref ORIG_HEAD "$SECRET_HASH"

git branch -D feature >/dev/null 2>&1 || true
