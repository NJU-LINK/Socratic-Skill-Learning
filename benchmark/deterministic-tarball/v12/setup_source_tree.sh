#!/bin/bash
set -euo pipefail

create_test_tree() {
    local base="$1"
    local nested
    local longname

    rm -rf "$base" /app/build-metadata
    mkdir -p "$base" /app/build-metadata

    printf '1717171717\n' > /app/build-metadata/epoch.txt

    mkdir -p "$base/src"
    cat > "$base/src/main.c" << 'EOF'
#include <stdio.h>
int main() {
    printf("hello variant\n");
    return 0;
}
EOF

    printf 'import sys\r\nprint("windows")\r\n' > "$base/src/windows.py"
    printf '#!/usr/bin/env python3\nprint("unix")\n' > "$base/src/unix.py"
    chmod +x "$base/src/unix.py"

    mkdir -p "$base/scripts"
    cat > "$base/scripts/deploy.sh" << 'EOF'
#!/bin/bash
echo "deploying"
EOF
    chmod 0755 "$base/scripts/deploy.sh"

    mkdir -p "$base/docs"
    printf 'Line 1\r\nLine 2\r\nLine 3\r\n' > "$base/docs/README.txt"
    printf '# Notes\nKeep this file.\n' > "$base/docs/NOTES.md"

    mkdir -p "$base/config"
    cat > "$base/config/service.yaml" << 'EOF'
service:
  name: archive-builder
  token: visible-to-group
EOF
    cat > "$base/config/pipeline.yaml" << 'EOF'
pipeline:
  step: package
  retries: 2
EOF
    chmod 0640 "$base/config/service.yaml" "$base/config/pipeline.yaml"

    mkdir -p "$base/credentials"
    cat > "$base/credentials/prod.json" << 'EOF'
{"token":"super-secret"}
EOF
    cat > "$base/credentials/test.json" << 'EOF'
{"token":"staging-secret"}
EOF
    chmod 0640 "$base/credentials/prod.json" "$base/credentials/test.json"

    mkdir -p "$base/cache/pip" "$base/cache/build"
    printf 'wheel-cache\n' > "$base/cache/pip/index.txt"
    printf 'intermediate-object\n' > "$base/cache/build/state.txt"

    printf 'old notes\n' > "$base/docs/README.txt.bak"
    printf 'stale backup\n' > "$base/config/service.yaml.bak"

    mkdir -p "$base/src/__pycache__"
    printf 'compiled\n' > "$base/src/__pycache__/mod.cpython-312.pyc"
    printf '' > "$base/src/main.o"

    mkdir -p "$base/.git/objects"
    printf 'ref: refs/heads/main\n' > "$base/.git/HEAD"
    printf '' > "$base/.git/objects/dummy"

    mkdir -p "$base/node_modules/pkg"
    printf 'module.exports = 1;\n' > "$base/node_modules/pkg/index.js"

    ln -sf ../docs/README.txt "$base/src/readme-link"
    ln -sf /etc/hosts "$base/src/hosts-link"
    ln -sf ../missing/ghost.txt "$base/src/broken-link"

    touch "$base/src/file with spaces.txt"
    touch "$base/src/file\$special\!chars.py"

    longname="very_long_filename_that_exceeds_two_hundred_characters_"
    longname="${longname}this_variant_checks_that_gnu_tar_handles_long_paths_without_"
    longname="${longname}depending_on_unstable_metadata_and_keeps_reproducible_ordering_"
    longname="${longname}through_the_final_archive_build_process.txt"
    printf 'long path\n' > "$base/src/$longname"

    nested="$base/deeply"
    for _ in $(seq 1 22); do
        nested="$nested/nested"
        mkdir -p "$nested"
    done
    printf 'deep file\n' > "$nested/file.txt"

    printf 'Text line\nBinary: \x00\x01\x02\x03\nMore text\n' > "$base/src/mixed.dat"

    mkdir -p "$base/assets"
    printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde' > "$base/assets/red.png"

    touch "$base/src/readonly.txt"
    chmod 0444 "$base/src/readonly.txt"

    touch -t 199901010000 "$base/src/old.txt"
    touch -t 203012312359 "$base/src/future.txt"
}

create_test_tree /app/src
echo "Created variant source tree at /app/src"
