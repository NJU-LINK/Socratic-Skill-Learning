#!/usr/bin/env bash
set -euo pipefail

mkdir -p repo
cd repo
git init -q
git config user.name "TerminalBench"
git config user.email "tb@example.com"
git branch -m master main

# ===== main branch: 12 clean commits =====
echo "# Project" > README.md
git add README.md && git commit -m "chore: init project a1b2c3d4"

echo "*.log" > .gitignore
echo "*.pyc" >> .gitignore
git add .gitignore && git commit -m "chore: add gitignore"

mkdir -p src
echo "print('hello world')" > src/main.py
git add src/main.py && git commit -m "feat: add main entrypoint"

echo "def util_hello():" > src/utils.py
git add src/utils.py && git commit -m "feat: add utility functions"

mkdir -p tests
echo "from src.main import *" > tests/test_main.py
git add tests/test_main.py && git commit -m "test: add main tests"

echo "from src.utils import *" > tests/test_utils.py
git add tests/test_utils.py && git commit -m "test: add util tests"

echo "DEBUG=true" > config.ini
git add config.ini && git commit -m "chore: add config file"

echo "# Changelog" > CHANGELOG.md
git add CHANGELOG.md && git commit -m "docs: add changelog"

echo "all: test" > Makefile
git add Makefile && git commit -m "chore: add Makefile"

mkdir -p docs
echo "# Docs" > docs/index.md
git add docs/index.md && git commit -m "docs: add index"

echo "MIT License" > LICENSE
git add LICENSE && git commit -m "chore: add license"

echo "1.0.0" > VERSION
git add VERSION && git commit -m "release: v1.0.0"

# ===== feature-x branch: 10 clean commits =====
git checkout -b feature-x

echo "feature_x_config = true" > feature.config
git add feature.config && git commit -m "chore: add feature config"

mkdir -p feature_x
echo "def feature_x_func():" > feature_x/__init__.py
git add feature_x/__init__.py && git commit -m "feat: add feature_x package"

echo "    pass" >> feature_x/__init__.py
git add feature_x/__init__.py && git commit -m "feat: implement feature_x func"

echo "ENABLE_FEATURE_X=true" > .env
git add .env && git commit -m "chore: add feature_x env vars"

mkdir -p tests/feature_x
echo "from feature_x import *" > tests/feature_x/test_init.py
git add tests/feature_x/test_init.py && git commit -m "test: add feature_x tests"

echo "DEBUG_FEATURE_X=true" >> config.ini
git add config.ini && git commit -m "chore: enable feature_x debug"

echo "def feature_x_utils():" > feature_x/utils.py
git add feature_x/utils.py && git commit -m "feat: add feature_x utils"

echo "def feature_helper():" >> feature_x/utils.py
git add feature_x/utils.py && git commit -m "feat: add helper function"

echo "FEATURE_X_PORT=9090" >> .env
git add .env && git commit -m "chore: configure feature_x port"

echo "feature_x docs" > docs/feature_x.md
git add docs/feature_x.md && git commit -m "docs: add feature_x docs"

# ===== experiment orphan branch: 8 commits (contains secret) =====
git checkout --orphan experiment
git rm -rfq .

echo "experiment init" > experiment_init.txt
git add experiment_init.txt && git commit -m "wip: experiment init"

echo "experiment data" > data.csv
git add data.csv && git commit -m "wip: add experiment data"

echo "iter 1" >> data.csv
git add data.csv && git commit -m "wip: experiment iteration 1"

echo "iter 2" >> data.csv
git add data.csv && git commit -m "wip: experiment iteration 2"

echo "secret[orphan_tag_secret]" > secret.txt
git add secret.txt && git commit -m "wip: add scratch notes"
SECRET_COMMIT=$(git rev-parse HEAD)

echo "iter 3" >> data.csv
git add data.csv && git commit -m "wip: experiment iteration 3"

echo "iter 4" >> data.csv
git add data.csv && git commit -m "wip: experiment iteration 4"

echo "iter 5" >> data.csv
git add data.csv && git commit -m "wip: experiment iteration 5"

# Tag the secret commit
git tag v1.0rc "$SECRET_COMMIT"

# ===== Back to main, delete experiment branch =====
git checkout main
git branch -D experiment

# ===== Create backup refs pointing to the secret commit =====
echo "$SECRET_COMMIT" > .git/ORIG_HEAD
echo "$SECRET_COMMIT		not-for-merge	branch 'experiment' of origin" > .git/FETCH_HEAD
