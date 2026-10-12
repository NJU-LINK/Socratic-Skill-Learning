#!/bin/bash
set -euo pipefail

create_release_tree() {
    local base="$1"

    rm -rf "$base"
    mkdir -p "$base"

    mkdir -p "$base/app/bin" "$base/app/config" "$base/app/scripts"
    mkdir -p "$base/docs/guides" "$base/assets/images"
    mkdir -p "$base/vendor/cache/pkg-a" "$base/vendor/cache/pkg-b"
    mkdir -p "$base/tmp/reports" "$base/tmp/logs"
    mkdir -p "$base/build/output" "$base/.git/objects"
    mkdir -p "$base/modules/core/python" "$base/modules/core/include"

    cat > "$base/app/bin/launch.sh" <<'EOF'
#!/usr/bin/env bash
printf 'launching release\n'
EOF
    chmod 0755 "$base/app/bin/launch.sh"

    printf 'APP_ENV=production\r\nLOG_LEVEL=info\r\n' > "$base/app/config/runtime.env"
    printf '{\r\n  "service": "release-bundle",\r\n  "port": 8080\r\n}\r\n' > "$base/app/config/settings.json"

    cat > "$base/app/scripts/build-index.py" <<'EOF'
#!/usr/bin/env python3
print("index build")
EOF
    chmod 0755 "$base/app/scripts/build-index.py"

    cat > "$base/modules/core/python/main.py" <<'EOF'
def run():
    return "ok"
EOF

    cat > "$base/modules/core/include/main.h" <<'EOF'
#pragma once
int main(void);
EOF

    printf 'Release notes\r\n==============\r\nReady for shipment.\r\n' > "$base/docs/README.txt"
    printf '# Packaging Guide\n\nFollow the manifest.\n' > "$base/docs/guides/packaging.md"
    printf 'temporary notice\r\nkeep this in bundle\r\n' > "$base/tmp/NOTICE.txt"
    printf 'debug trace\n' > "$base/tmp/logs/runtime.log"
    printf 'intermediate data\n' > "$base/tmp/reports/daily.tmp"

    printf 'artifact\n' > "$base/build/output/app.o"
    printf 'compiled\n' > "$base/modules/core/python/__pycache__.pyc"

    printf 'cached dependency\n' > "$base/vendor/cache/pkg-a/index.js"
    printf 'retained marker\n' > "$base/vendor/cache/.keep"
    printf 'other package\n' > "$base/vendor/cache/pkg-b/lock.json"

    printf 'ref: refs/heads/main\n' > "$base/.git/HEAD"
    printf 'obj\n' > "$base/.git/objects/placeholder"

    printf 'plain text with spaces\r\nand windows line endings\r\n' > "$base/app/config/file with spaces.txt"
    printf 'name: release\nvalue: stable\n' > "$base/app/config/release.yaml"
    printf 'keep me out\n' > "$base/app/config/secret.token"
    chmod 0600 "$base/app/config/secret.token"

    printf 'binary\x00payload\x01\n' > "$base/assets/images/logo.bin"

    ln -s ../docs/README.txt "$base/app/README.link"
    ln -s /etc/hostname "$base/app/host.link"

    local longdir="$base/docs/guides/deep"
    local i
    for i in $(seq 1 18); do
        longdir="$longdir/level_$i"
        mkdir -p "$longdir"
    done
    printf 'deep content\n' > "$longdir/notes.txt"

    local longname="manifest_driven_release_bundle_with_a_filename_that_is_intentionally_long_to_exercise_gnu_tar_path_handling_and_reproducible_archive_ordering_across_nested_directories.txt"
    printf 'long path file\n' > "$base/docs/guides/$longname"

    touch -t 202401010101 "$base/app/bin/launch.sh"
    touch -t 202402020202 "$base/app/config/runtime.env"
    touch -t 202403030303 "$base/docs/README.txt"
    touch -t 202404040404 "$base/tmp/NOTICE.txt"
    touch -t 202405050505 "$base/assets/images/logo.bin"

    cat > "$base/release.manifest" <<'EOF'
# Manifest format:
#   set-mtime <unix-epoch>
#   include <glob>
#   exclude <glob>
# Later rules override earlier ones. Selected paths are archived in the
# order produced by the include rules after exclusions are applied.

set-mtime 1712345678
include app/
include docs/
include assets/images/logo.bin
include tmp/NOTICE.txt
exclude .git/**
exclude build/**
exclude vendor/cache/**
include vendor/cache/.keep
exclude tmp/**
include tmp/NOTICE.txt
exclude **/__pycache__*
exclude **/*.pyc
exclude **/*.o
exclude **/*.tmp
exclude **/*.token
EOF
}

create_release_tree /app/src
mkdir -p /app/out
echo "Created manifest-driven source tree at /app/src"
