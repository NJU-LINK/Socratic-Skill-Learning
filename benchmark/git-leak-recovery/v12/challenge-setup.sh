#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/app/repo"
mkdir -p "$REPO_DIR"
cd "$REPO_DIR"
git init -q
git config user.name "Developer"
git config user.email "dev@example.com"

# Commit 1
echo "# Project Alpha" > README.md
git add README.md
git commit -m "chore: init project"

# Commit 2
mkdir -p features
echo "Feature 1: authentication module" > features/feature1.md
git add features/
git commit -m "feat: add feature specification"

# Commit 3
mkdir -p config
cat > config/app.yaml << 'EOF'
app_name: alpha
version: 1.0.0
debug: false
EOF
git add config/
git commit -m "chore: add app configuration"

# Commit 4
mkdir -p lib
cat > lib/helpers.py << 'EOF'
def load_config(path):
    pass
EOF
git add lib/
git commit -m "feat: add helper library"

# Commit 5 — the secret
echo "secret[replaced_but_not_gone]" > secret.txt
git add secret.txt
git commit -m "feat: add scratch notes"
ORIG5=$(git rev-parse HEAD)

# Record commit-5 metadata for the replacement
PARENT_OF_ORIG5=$(git rev-parse ${ORIG5}^)
TREE_BEFORE_SECRET=$(git rev-parse ${PARENT_OF_ORIG5}^{tree})
C5_MSG="feat: add scratch notes"
C5_AUTHOR_NAME=$(git log --format="%an" -1 $ORIG5)
C5_AUTHOR_EMAIL=$(git log --format="%ae" -1 $ORIG5)
C5_DATE=$(git log --format="%aD" -1 $ORIG5)

# Create a replacement commit with the tree from commit 4 (no secret.txt)
export GIT_AUTHOR_NAME="$C5_AUTHOR_NAME"
export GIT_AUTHOR_EMAIL="$C5_AUTHOR_EMAIL"
export GIT_AUTHOR_DATE="$C5_DATE"
export GIT_COMMITTER_NAME="$C5_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$C5_AUTHOR_EMAIL"
export GIT_COMMITTER_DATE="$C5_DATE"

REPLACEMENT5=$(echo "$C5_MSG" | git commit-tree $TREE_BEFORE_SECRET -p $PARENT_OF_ORIG5)

unset GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_AUTHOR_DATE
unset GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GIT_COMMITTER_DATE

# Set up the replace ref: ORIG5 -> REPLACEMENT5
git replace $ORIG5 $REPLACEMENT5

# Move master to point to the replacement commit.
# Now ORIG5 is reachable ONLY via the replace ref (refs/replace/ORIG5).
git update-ref refs/heads/master $REPLACEMENT5
# Sync index and working tree with the new HEAD so secret.txt is not carried forward
git reset --hard HEAD

# Commits 6-8 on top of the clean history
echo "Feature 1: implemented authentication module" > features/feature1.md
git add features/feature1.md
git commit -m "docs: update feature status"

cat >> config/app.yaml << 'EOF'
logging:
  level: info
EOF
git add config/app.yaml
git commit -m "chore: add logging config"

mkdir -p tests
echo "def test_load_config(): pass" > tests/test_helpers.py
git add tests/
git commit -m "test: add helper tests"
