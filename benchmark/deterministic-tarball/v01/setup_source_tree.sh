#!/bin/bash
set -euo pipefail

create_test_tree() {
    local base="$1"

    rm -rf "$base"
    mkdir -p "$base"

    mkdir -p "$base/app/src"
    cat > "$base/app/src/main.c" <<'EOF'
#include <stdio.h>
int main() {
    printf("Hello, release!\n");
    return 0;
}
EOF

    printf 'import sys\r\nprint("release build")\r\n' > "$base/app/src/windows.py"
    printf '#!/usr/bin/env python3\nimport os\nprint("unix")\n' > "$base/app/src/unix.py"
    chmod +x "$base/app/src/unix.py"

    mkdir -p "$base/tools"
    cat > "$base/tools/build-release.sh" <<'EOF'
#!/bin/bash
echo "bundle"
EOF
    chmod +x "$base/tools/build-release.sh"

    mkdir -p "$base/docs"
    printf 'Release Notes\r\nVersion 1\r\n' > "$base/docs/README.txt"
    echo "# Bundle Guide" > "$base/docs/guide.md"

    mkdir -p "$base/.hg/store"
    echo "default = https://example.invalid/repo" > "$base/.hg/hgrc"
    touch "$base/.hg/store/data"

    mkdir -p "$base/vendor/js/package1"
    touch "$base/vendor/js/package1/index.js"

    mkdir -p "$base/scratch/build"
    touch "$base/scratch/build/log.txt"
    mkdir -p "$base/.state/cache"
    touch "$base/.state/cache/session.db"

    mkdir -p "$base/app/src/__pycache__"
    touch "$base/app/src/__pycache__/test.pyc"
    touch "$base/app/src/main.o"
    touch "$base/app/src/module.pyo"
    mkdir -p "$base/classes"
    touch "$base/classes/App.class"
    touch "$base/app/src/ignored.tmp"

    mkdir -p "$base/keys"
    echo "SECRET_KEY" > "$base/keys/private.key"
    chmod 0600 "$base/keys/private.key"

    mkdir -p "$base/secrets"
    echo "password123" > "$base/secrets/db.conf"
    chmod 0600 "$base/secrets/db.conf"

    ln -sf ../docs/README.txt "$base/app/src/README"
    ln -sf /etc/passwd "$base/app/src/passwd-link"

    touch "$base/app/src/file with spaces.txt"
    touch "$base/app/src/file\$special\!chars.py"

    local longname="very_long_filename_that_exceeds_two_hundred_characters_"
    longname="${longname}this_is_to_test_edge_cases_in_tar_handling_and_filesystem_limits_"
    longname="${longname}some_systems_have_issues_with_very_long_paths_so_we_need_to_test_this_properly_"
    longname="${longname}end.txt"
    touch "$base/app/src/$longname"

    local nested="$base/deeply"
    for i in {1..22}; do
        nested="$nested/nested"
        mkdir -p "$nested"
    done
    echo "deep file" > "$nested/file.txt"

    printf 'Text line\nBinary: \x00\x01\x02\x03\nMore text\n' > "$base/app/src/mixed.dat"

    mkdir -p "$base/assets"
    printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde' > "$base/assets/red.png"

    touch "$base/app/src/readonly.txt"
    chmod 0444 "$base/app/src/readonly.txt"

    touch -t 199901010000 "$base/app/src/old.txt"
    touch -t 203012312359 "$base/app/src/future.txt"

    cat > "$base/.distignore" <<'EOF'
.hg/
vendor/js/
scratch/
.state/
**/__pycache__/
*.tmp
*.pyc
*.pyo
*.o
*.class
EOF
}

create_test_tree /app/src
echo "Created release source tree at /app/src"
