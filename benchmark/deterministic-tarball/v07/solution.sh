#!/bin/bash
set -euo pipefail

cat > /app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

src_dir=/app/src
output_path=/app/release.tar.gz
epoch="${SOURCE_DATE_EPOCH:-946684800}"

work_dir=$(mktemp -d)
stage_dir="$work_dir/stage"
tar_path="$work_dir/release.tar"
mkdir -p "$stage_dir"

cleanup() {
    rm -rf "$work_dir"
}
trap cleanup EXIT

manifest_file="$src_dir/manifest/packages.txt"
declare -a manifest_packages=()
while IFS= read -r line; do
    [ -n "$line" ] || continue
    manifest_packages+=("${line%/}")
done < "$manifest_file"

is_manifest_scoped() {
    local rel="$1"
    local package_root
    for package_root in "${manifest_packages[@]}"; do
        if [[ "$rel" == "$package_root" || "$rel" == "$package_root/"* ]]; then
            return 0
        fi
    done
    return 1
}

is_text_file() {
    local path="$1"
    local mime
    mime=$(file -b --mime "$path")
    [[ "$mime" != *"charset=binary"* ]]
}

has_shebang() {
    python3 - "$1" <<'PY'
import pathlib
import sys

sys.exit(0 if pathlib.Path(sys.argv[1]).read_bytes()[:2] == b"#!" else 1)
PY
}

normalize_crlf_to_lf() {
    python3 - "$1" "$2" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1]).read_bytes()
Path(sys.argv[2]).write_bytes(src.replace(b"\r\n", b"\n"))
PY
}

find -P "$src_dir" \
    \( -type d \( -name .git -o -name .venv -o -name coverage -o -name tmp -o -name temp -o -name .cache -o -name __pycache__ \) -prune \) \
    -o -mindepth 1 -print0 |
while IFS= read -r -d '' path; do
    rel_path=${path#"$src_dir/"}
    dest_path="$stage_dir/$rel_path"

    if [ -d "$path" ]; then
        mkdir -p "$dest_path"
        chmod 0755 "$dest_path"
        continue
    fi

    if [ -L "$path" ]; then
        mkdir -p "$(dirname "$dest_path")"
        ln -s "$(readlink "$path")" "$dest_path"
        continue
    fi

    if [ ! -f "$path" ]; then
        continue
    fi

    case "$path" in
        *.tmp|*.pyc|*.o|*.log)
            continue
            ;;
    esac

    if [ "$(stat -c '%a' "$path")" = "600" ]; then
        continue
    fi

    mkdir -p "$(dirname "$dest_path")"

    if is_manifest_scoped "$rel_path" && is_text_file "$path"; then
        normalize_crlf_to_lf "$path" "$dest_path"
    else
        cp -P "$path" "$dest_path"
    fi

    src_mode=$(stat -c '%a' "$path")
    if has_shebang "$path" || (( (8#$src_mode & 8#111) != 0 )); then
        chmod 0755 "$dest_path"
    else
        chmod 0644 "$dest_path"
    fi
done

find "$stage_dir" -type d -exec chmod 0755 {} +

LC_ALL=C tar \
    --format=gnu \
    --sort=name \
    --mtime="@$epoch" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -C "$stage_dir" \
    -cf "$tar_path" \
    .

gzip -n -c "$tar_path" > "$output_path"
EOF

chmod +x /app/build.sh
