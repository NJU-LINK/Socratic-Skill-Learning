#!/bin/bash
set -euo pipefail

cat > /app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

src_root=/app/src
payload=/app/release.tar.zst
meta=/app/release-meta.tar.zst

epoch="${SOURCE_DATE_EPOCH:-946684800}"
compressor=(zstd -19 --long --no-check --single-thread)

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

normalized_root="$workdir/normalized"
manifest_root="$workdir/meta"
mkdir -p "$normalized_root" "$manifest_root"

is_excluded_path() {
    local rel="$1"
    case "$rel" in
        .git|.git/*|node_modules|node_modules/*|tmp|tmp/*|.cache|.cache/*|__pycache__|__pycache__/*|*/__pycache__|*/__pycache__/*)
            return 0
            ;;
        reports/generated-checksums.sha256)
            return 0
            ;;
        *.tmp|*.pyc|*.o)
            return 0
            ;;
    esac
    return 1
}

is_text_file() {
    local path="$1"
    case "$(file --mime-type -b "$path")" in
        text/*|*/xml|*/json|inode/x-empty)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

normalize_text_file() {
    local src="$1"
    local dest="$2"
    python3 - "$src" "$dest" <<'PY'
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])
data = src.read_bytes()
text = data.decode('utf-8', errors='surrogateescape')
text = text.replace('\r\n', '\n').replace('\r', '\n')
dest.write_bytes(text.encode('utf-8', errors='surrogateescape'))
PY
}

while IFS= read -r -d '' rel; do
    if is_excluded_path "$rel"; then
        continue
    fi

    src_path="$src_root/$rel"
    if [ -f "$src_path" ] && [ "$(stat -c '%a' "$src_path")" = "600" ]; then
        continue
    fi

    dest_path="$normalized_root/$rel"
    parent_dir=$(dirname "$dest_path")
    mkdir -p "$parent_dir"
    chmod 0755 "$parent_dir"

    if [ -L "$src_path" ]; then
        ln -snf "$(readlink "$src_path")" "$dest_path"
        continue
    fi

    if [ -d "$src_path" ]; then
        mkdir -p "$dest_path"
        chmod 0755 "$dest_path"
        continue
    fi

    if is_text_file "$src_path"; then
        normalize_text_file "$src_path" "$dest_path"
    else
        cp -p "$src_path" "$dest_path"
    fi

    if [ -x "$src_path" ] || head -c 2 "$src_path" 2>/dev/null | grep -q '^#!'; then
        chmod 0755 "$dest_path"
    else
        chmod 0644 "$dest_path"
    fi
done < <(cd "$src_root" && find . -mindepth 1 -printf '%P\0' | sort -z)

touch -h -d "@${epoch}" "$normalized_root"
while IFS= read -r -d '' path; do
    touch -h -d "@${epoch}" "$path"
done < <(find "$normalized_root" -mindepth 1 -print0)

manifest="$manifest_root/MANIFEST.txt"
build_info="$manifest_root/BUILD-INFO.txt"

while IFS= read -r -d '' rel; do
    item="$normalized_root/$rel"
    if [ -L "$item" ]; then
        digest=$(printf '%s' "$(readlink "$item")" | sha256sum | awk '{print $1}')
    elif [ -f "$item" ]; then
        digest=$(sha256sum "$item" | awk '{print $1}' | sed 's/^\\//')
    else
        continue
    fi
    printf '%s  %s\n' "$digest" "$rel" >> "$manifest"
done < <(cd "$normalized_root" && find . \( -type f -o -type l \) -printf '%P\0' | sort -z)

printf 'EPOCH=%s\n' "$epoch" > "$build_info"
printf 'PAYLOAD_COMPRESSOR=%s\n' "${compressor[*]}" >> "$build_info"
printf 'META_COMPRESSOR=%s\n' "${compressor[*]}" >> "$build_info"

touch -d "@${epoch}" "$manifest" "$build_info"

rm -f "$payload" "$meta"

tar --sort=name \
    --format=gnu \
    --mtime="@${epoch}" \
    --owner=0 --group=0 --numeric-owner \
    -C "$normalized_root" -cf - . | "${compressor[@]}" -o "$payload"

tar --sort=name \
    --format=gnu \
    --mtime="@${epoch}" \
    --owner=0 --group=0 --numeric-owner \
    -C "$manifest_root" -cf - MANIFEST.txt BUILD-INFO.txt | "${compressor[@]}" -o "$meta"
EOF

chmod +x /app/build.sh
