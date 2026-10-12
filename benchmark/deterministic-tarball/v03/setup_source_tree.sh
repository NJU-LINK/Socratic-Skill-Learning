#!/bin/bash
set -euo pipefail

create_test_tree() {
    local base="$1"

    rm -rf "$base"
    mkdir -p "$base"

    mkdir -p "$base/src/lib" "$base/scripts" "$base/tools/bin" "$base/assets" "$base/docs"

    cat > "$base/src/lib/main.c" <<'EOF'
#include <stdio.h>

int main(void) {
    puts("release build");
    return 0;
}
EOF

    printf 'from pathlib import Path\r\nprint(Path("/tmp").exists())\r\n' > "$base/src/lib/windows_style.py"
    printf 'This README ships with the release.\r\nKeep line endings stable.\r\n' > "$base/docs/README.txt"
    printf 'deploy=true\n' > "$base/docs/release-notes.md"

    cat > "$base/tools/run" <<'EOF'
echo "launching tool"
EOF
    chmod 0644 "$base/tools/run"

    cat > "$base/scripts/no_shebang" <<'EOF'
printf 'no shebang but should execute\n'
EOF
    chmod 0644 "$base/scripts/no_shebang"

    cat > "$base/assets/template.cgi" <<'EOF'
Content-Type: text/plain

Generated from template.
EOF
    chmod 0755 "$base/assets/template.cgi"

    printf 'Text line\nBinary: \x00\x01\x02\x03\nMore text\n' > "$base/assets/mixed.dat"
    chmod 0755 "$base/assets/mixed.dat"

    printf '\x7fELFhelper-binary\x00\x01\x02' > "$base/tools/bin/helper.bin"
    chmod 0644 "$base/tools/bin/helper.bin"

    printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde' > "$base/assets/red.png"

    touch "$base/src/file with spaces.txt"
    printf 'name with spaces\r\n' > "$base/src/file with spaces.txt"
    touch "$base/src/file\$special\!chars.py"
    printf 'print("special")\r\n' > "$base/src/file\$special\!chars.py"

    longname="very_long_filename_that_exceeds_two_hundred_characters_"
    longname="${longname}manifest_driven_release_modes_make_permission_inference_invalid_"
    longname="${longname}this_path_exists_to_validate_gnu_tar_handling_for_reproducible_archives_"
    longname="${longname}end.txt"
    printf 'long path payload\r\n' > "$base/src/$longname"

    nested="$base/deeply"
    for i in {1..22}; do
        nested="$nested/nested"
        mkdir -p "$nested"
    done
    printf 'deep file\r\n' > "$nested/file.txt"

    mkdir -p "$base/.git/objects" "$base/node_modules/pkg" "$base/tmp" "$base/.cache" "$base/src/__pycache__"
    printf 'ref: refs/heads/main\n' > "$base/.git/HEAD"
    touch "$base/.git/objects/dummy" "$base/node_modules/pkg/index.js" "$base/tmp/throwaway.tmp"
    touch "$base/.cache/cache.db" "$base/src/__pycache__/compiled.pyc" "$base/src/lib/main.o"

    mkdir -p "$base/keys" "$base/secrets"
    printf 'PRIVATE KEY\n' > "$base/keys/private.key"
    chmod 0600 "$base/keys/private.key"
    printf 'db-password\n' > "$base/secrets/db.conf"
    chmod 0600 "$base/secrets/db.conf"

    touch "$base/src/readonly.txt"
    chmod 0444 "$base/src/readonly.txt"
    touch "$base/src/future.txt"
    chmod 0755 "$base/src/future.txt"
    touch -t 199901010000 "$base/src/readonly.txt"
    touch -t 203012312359 "$base/src/future.txt"

    ln -sf ../docs/README.txt "$base/src/README"
    ln -sf /etc/passwd "$base/src/passwd-link"

    cat > "$base/.release-meta.json" <<'EOF'
{
  "files": {
    "assets/mixed.dat": {"kind": "binary", "mode": "0644"},
    "assets/red.png": {"kind": "binary", "mode": "0644"},
    "assets/template.cgi": {"kind": "text", "mode": "0644"},
    "deeply/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/nested/file.txt": {"kind": "text", "mode": "0644"},
    "docs/README.txt": {"kind": "text", "mode": "0644"},
    "docs/release-notes.md": {"kind": "text", "mode": "0644"},
    "scripts/no_shebang": {"kind": "text", "mode": "0755"},
    "src/README": {"kind": "symlink"},
    "src/file with spaces.txt": {"kind": "text", "mode": "0644"},
    "src/file$special!chars.py": {"kind": "text", "mode": "0644"},
    "src/future.txt": {"kind": "text", "mode": "0644"},
    "src/lib/main.c": {"kind": "text", "mode": "0644"},
    "src/lib/windows_style.py": {"kind": "text", "mode": "0644"},
    "src/passwd-link": {"kind": "symlink"},
    "src/readonly.txt": {"kind": "text", "mode": "0644"},
    "src/very_long_filename_that_exceeds_two_hundred_characters_manifest_driven_release_modes_make_permission_inference_invalid_this_path_exists_to_validate_gnu_tar_handling_for_reproducible_archives_end.txt": {"kind": "text", "mode": "0644"},
    "tools/bin/helper.bin": {"kind": "binary", "mode": "0755"},
    "tools/run": {"kind": "text", "mode": "0755"}
  }
}
EOF
}

create_test_tree /app/src
echo "Created manifest-driven source tree at /app/src"
