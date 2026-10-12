#!/bin/bash
set -euo pipefail

cat > /app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

src_root="/app/src"
meta_path="$src_root/.release-meta.json"
out_path="/app/release.tar.zst"
staging_root="$(mktemp -d)"
resolve_source_path() {
    local rel_path="$1"
    local candidate="$src_root/$rel_path"

    if [[ -e "$candidate" || -L "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    candidate="$src_root/${rel_path//!/\\!}"
    if [[ -e "$candidate" || -L "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    echo "missing source path for manifest entry: $rel_path" >&2
    return 1
}

cleanup() {
    rm -rf "$staging_root"
}
trap cleanup EXIT

if [[ ! -f "$meta_path" ]]; then
    echo "missing release metadata: $meta_path" >&2
    exit 1
fi

epoch="${SOURCE_DATE_EPOCH:-946684800}"
staging_dir="$staging_root/release"
mkdir -p "$staging_dir"

jq -r '.files | to_entries[] | @base64' "$meta_path" | while IFS= read -r encoded; do
    entry_json="$(printf '%s' "$encoded" | base64 -d)"
    rel_path="$(printf '%s' "$entry_json" | jq -r '.key')"
    kind="$(printf '%s' "$entry_json" | jq -r '.value.kind')"
    src_path="$(resolve_source_path "$rel_path")"
    dst_path="$staging_dir/$rel_path"

    mkdir -p "$(dirname "$dst_path")"

    case "$kind" in
        text)
            tr -d '\r' < "$src_path" > "$dst_path"
            chmod "$(printf '%s' "$entry_json" | jq -r '.value.mode')" "$dst_path"
            ;;
        binary)
            cp --preserve=links "$src_path" "$dst_path"
            chmod "$(printf '%s' "$entry_json" | jq -r '.value.mode')" "$dst_path"
            ;;
        symlink)
            ln -s "$(readlink "$src_path")" "$dst_path"
            ;;
        *)
            echo "unsupported manifest kind for $rel_path: $kind" >&2
            exit 1
            ;;
    esac
done

find "$staging_dir" -type d -print0 | xargs -0r chmod 0755
find "$staging_dir" -print0 | xargs -0r touch -h -d "@$epoch"

rm -f -- "$out_path"

tar --format=gnu \
    --sort=name \
    --mtime="@$epoch" \
    --owner=0 --group=0 --numeric-owner \
    -C "$staging_dir" \
    -cf - . | zstd -19 --long --no-check --single-thread -o "$out_path"
EOF

chmod +x /app/build.sh
