#!/bin/bash
set -euo pipefail

cat > /app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

src_dir="/app/src"
out_file="/app/release.tar.zst"
epoch="${SOURCE_DATE_EPOCH:-946684800}"

if [[ ! -d "$src_dir" ]]; then
    echo "missing source tree: $src_dir" >&2
    exit 1
fi

tmpdir="$(mktemp -d)"
stage_dir="$tmpdir/stage"
trap 'rm -rf "$tmpdir"' EXIT

mkdir -p "$stage_dir"

declare -A exec_map=()
declare -A text_ext_map=()

while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    exec_map["$line"]=1
done < "$src_dir/packaging/executables.txt"

while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    text_ext_map["$line"]=1
done < "$src_dir/packaging/text-extensions.txt"

while IFS= read -r -d '' rel; do
    [[ -z "$rel" ]] && continue
    src_path="$src_dir/$rel"
    dst_path="$stage_dir/$rel"
    parent_dir="$(dirname "$dst_path")"

    mkdir -p "$parent_dir"

    if [[ -L "$src_path" ]]; then
        ln -s "$(readlink "$src_path")" "$dst_path"
        continue
    fi

    if [[ -d "$src_path" ]]; then
        mkdir -p "$dst_path"
        continue
    fi

    ext=""
    base_name="$(basename "$rel")"
    if [[ "$base_name" == *.* ]]; then
        ext="${base_name##*.}"
    fi

    if [[ -n "$ext" && -n "${text_ext_map[$ext]:-}" ]]; then
        python3 - "$src_path" "$dst_path" <<'PY'
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
dst.write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))
PY
    else
        cp -p "$src_path" "$dst_path"
    fi

    chmod "$([[ -n "${exec_map[$rel]:-}" ]] && printf 0755 || printf 0644)" "$dst_path"
done < <(
    find "$src_dir" \
        \( -path "$src_dir/.git" -o -path "$src_dir/node_modules" -o -path "$src_dir/tmp" -o -path "$src_dir/.cache" -o -path '*/__pycache__' \) -prune \
        -o \( -name '*.tmp' -o -name '*.pyc' -o -name '*.o' -o -name '*.secret' \) -prune \
        -o -printf '%P\0' | LC_ALL=C sort -z
)

find "$stage_dir" -type d -print0 | xargs -0r chmod 0755
find "$stage_dir" -exec touch -h -d "@$epoch" {} +

rm -f "$out_file"

tar --sort=name \
    --format=gnu \
    --mtime="@$epoch" \
    --owner=0 --group=0 --numeric-owner \
    -C "$stage_dir" -cf - . | zstd -12 --no-check --single-thread -o "$out_file"
EOF

chmod +x /app/build.sh
