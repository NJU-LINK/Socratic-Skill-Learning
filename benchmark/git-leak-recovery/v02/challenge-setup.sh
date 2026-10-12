#!/usr/bin/env bash
set -euo pipefail

mkdir -p repo
cd repo
git init -q
git config user.name "TerminalBench"
git config user.email "tb@example.com"

echo "demo project" > README.md
git add README.md
git commit -m "chore: init e665d1a2-04a7-4e61-b523-e897e231d9cc"

printf '%s' "secret[split_git" > part1.txt
git add part1.txt

printf '%s' "_recovery]" > part2.txt
git add part2.txt

git reset HEAD .

rm -f part1.txt part2.txt

echo "some changes" >> README.md
git add README.md
git commit -m "chore: update readme"
