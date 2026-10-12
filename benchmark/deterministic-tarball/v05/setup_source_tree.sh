#!/bin/bash
set -euo pipefail

create_test_tree() {
    local base="$1"
    local nested
    local longname

    rm -rf "$base"
    mkdir -p "$base"

    mkdir -p \
        "$base/src" \
        "$base/docs" \
        "$base/templates" \
        "$base/db" \
        "$base/config" \
        "$base/scripts" \
        "$base/bin" \
        "$base/packaging" \
        "$base/assets" \
        "$base/notes" \
        "$base/ops" \
        "$base/tmp" \
        "$base/.cache" \
        "$base/.git/objects" \
        "$base/node_modules/pkg" \
        "$base/generated" \
        "$base/src/__pycache__"

    cat > "$base/packaging/executables.txt" <<'EOF'
# Relative paths that must be executable in the archive.
scripts/release-helper
scripts/deploy.sh
EOF

    cat > "$base/packaging/text-extensions.txt" <<'EOF'
txt
md
py
sh
c
h
js
css
html
xml
json
yaml
yml
sql
tmpl
EOF

    cat > "$base/src/main.c" <<'EOF'
#include <stdio.h>

int main(void) {
    puts("deterministic");
    return 0;
}
EOF

    printf 'import sys\r\nprint("windows")\r\n' > "$base/src/windows.py"
    printf '#!/usr/bin/env python3\nprint("should not become executable")\n' > "$base/bin/runner.py"
    chmod +x "$base/bin/runner.py"

    printf 'SELECT 1;\r\nSELECT 2;\r\n' > "$base/db/schema.sql"
    printf 'Hello, {{ name }}\r\n' > "$base/templates/greeting.tmpl"
    printf 'apiVersion: v1\r\nkind: ConfigMap\r\n' > "$base/config/service.yaml"
    printf 'function main(){\r\n  return 42;\r\n}\r\n' > "$base/generated/app.min.js"
    printf 'Line one\r\nLine two\r\n' > "$base/docs/README.txt"
    printf '# Notes\nDeterministic packaging\n' > "$base/docs/guide.md"
    printf '#!/bin/bash\necho deploy\n' > "$base/scripts/deploy.sh"
    chmod 0644 "$base/scripts/deploy.sh"
    printf 'echo helper\n' > "$base/scripts/release-helper"
    chmod 0644 "$base/scripts/release-helper"
    printf '#!/bin/sh\necho keep me non-executable\n' > "$base/scripts/ops-tool"
    chmod 0755 "$base/scripts/ops-tool"

    # Extensionless config should stay byte-for-byte unchanged.
    printf 'MODE=prod\r\nREGION=west\r\n' > "$base/config/runtime"

    # Non-secret 0600 file should remain included.
    printf 'token=internal-use\n' > "$base/config/keep.env"
    chmod 0600 "$base/config/keep.env"

    printf 'remove me\n' > "$base/notes/brief.secret"
    chmod 0644 "$base/notes/brief.secret"
    printf 'db_password=hunter2\n' > "$base/ops/prod.secret"
    chmod 0600 "$base/ops/prod.secret"

    touch "$base/src/main.o"
    touch "$base/src/__pycache__/cache.pyc"
    touch "$base/tmp/scratch.tmp"
    touch "$base/.cache/index"
    touch "$base/node_modules/pkg/index.js"
    echo 'ref: refs/heads/main' > "$base/.git/HEAD"
    touch "$base/.git/objects/pack"

    printf 'Text line\nBinary:\x00\x01\x02\n' > "$base/assets/mixed.dat"
    printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde' > "$base/assets/red.png"

    touch "$base/src/file with spaces.txt"
    touch "$base/src/file\$special\!chars.py"

    longname='very_long_filename_that_exceeds_two_hundred_characters_'
    longname="${longname}manifest_driven_packaging_needs_to_handle_unusually_long_paths_without_"
    longname="${longname}changing_archive_order_or_tar_metadata_even_when_the_name_is_cumbersome_"
    longname="${longname}and_extension_rules_still_need_to_apply.sql"
    printf 'SELECT 99;\r\n' > "$base/src/$longname"

    nested="$base/deeply"
    for _ in {1..22}; do
        nested="$nested/nested"
        mkdir -p "$nested"
    done
    printf 'nested\r\nfile\r\n' > "$nested/final.tmpl"

    ln -sf ../docs/README.txt "$base/src/readme-link"
    ln -sf /etc/passwd "$base/src/passwd-link"

    touch -t 199901010000 "$base/src/old.txt"
    touch -t 203012312359 "$base/src/future.txt"
}

create_test_tree /app/src
echo "Created variant source tree at /app/src"
