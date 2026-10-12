#!/bin/bash
set -euo pipefail

create_test_tree() {
    local base="$1"
    local nested
    local longname

    rm -rf "$base"
    mkdir -p "$base"

    mkdir -p \
        "$base/appsrc/bin" \
        "$base/appsrc/lib" \
        "$base/appsrc/scripts" \
        "$base/appsrc/build/output" \
        "$base/appsrc/.deps/vendor" \
        "$base/appsrc/cache/state" \
        "$base/guide/notes" \
        "$base/guide/patches" \
        "$base/guide/reference" \
        "$base/guide/cache/drafts" \
        "$base/assets" \
        "$base/credentials" \
        "$base/tools"

    cat > "$base/appsrc/main.c" <<'EOF'
#include <stdio.h>

int main(void) {
    puts("stable build");
    return 0;
}
EOF

    printf 'import pathlib\r\nprint(pathlib.Path(__file__).name)\r\n' > "$base/appsrc/lib/windows_style.py"
    printf '#!/usr/bin/env bash\nset -eu\nprintf "deploying\\n"\n' > "$base/appsrc/scripts/deploy.sh"
    chmod +x "$base/appsrc/scripts/deploy.sh"

    printf 'Stage 1\r\nStage 2\r\n' > "$base/guide/notes/README.txt"
    printf '# Build Notes\r\n\r\nKeep archive stable.\r\n' > "$base/guide/notes/plan.md"
    printf 'diff --git a/app.txt b/app.txt\r\n--- a/app.txt\r\n+++ b/app.txt\r\n@@ -1 +1 @@\r\n-old\r\n+new\r\n' > "$base/guide/patches/release.patch"

    printf 'legacy=true\n' > "$base/guide/notes/legacy-config.bak"
    printf 'old copy\n' > "$base/appsrc/bin/previous-output.bak"

    printf 'temporary object\n' > "$base/appsrc/build/output/result.txt"
    printf 'dependency cache\n' > "$base/appsrc/.deps/vendor/lock.txt"
    printf 'cache state\n' > "$base/appsrc/cache/state/cache.db"
    printf 'draft cache\n' > "$base/guide/cache/drafts/note.txt"

    printf 'API_TOKEN=keep-out\n' > "$base/credentials/prod.env"
    chmod 0600 "$base/credentials/prod.env"

    printf 'user guide\n' > "$base/guide/reference/file with spaces.txt"
    printf 'shell helper\n' > "$base/tools/helper.sh"
    chmod +x "$base/tools/helper.sh"

    ln -sf ../guide/notes/README.txt "$base/appsrc/notes-link"
    ln -sf /etc/hosts "$base/appsrc/external-hosts-link"

    longname='deterministic_archive_validation_filename_that_pushes_path_length_limits_'
    longname="${longname}while_still_remaining_a_plain_regular_file_for_tar_and_gzip_checks_"
    longname="${longname}inside_the_reference_material_section_for_this_variant_payload.txt"
    printf 'long path data\n' > "$base/guide/reference/$longname"

    nested="$base/guide"
    for _ in $(seq 1 20); do
        nested="$nested/deep"
        mkdir -p "$nested"
    done
    printf 'deep file\n' > "$nested/final.txt"

    nested="$base/appsrc"
    for _ in $(seq 1 10); do
        nested="$nested/module"
        mkdir -p "$nested"
    done
    printf 'nested code\n' > "$nested/data.txt"

    printf 'Text line\nBinary:\x00\x01\x02\nTail\n' > "$base/assets/mixed.dat"
    printf '\x1f\x8b\x08\x00demo' > "$base/assets/blob.bin"

    touch "$base/appsrc/empty.txt"
    chmod 0444 "$base/appsrc/empty.txt"
    touch -t 200102030405 "$base/appsrc/old.log"
    touch -t 203112312359 "$base/guide/notes/future.log"
}

create_test_tree /app/workspace
echo "Created variant source tree at /app/workspace"
