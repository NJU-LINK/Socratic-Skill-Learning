#!/bin/bash
set -euo pipefail

cat > /app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

src_dir=/app/src
manifest_path="$src_dir/.release-times"
output_path=/app/release.tar.zst
default_epoch=946684800

if [[ ! -d "$src_dir" ]]; then
    echo "missing source tree: $src_dir" >&2
    exit 1
fi

if [[ ! -f "$manifest_path" ]]; then
    echo "missing manifest: $manifest_path" >&2
    exit 1
fi

rm -f -- "$output_path"

tmp_root=$(mktemp -d)
cleanup() {
    rm -rf "$tmp_root"
}
trap cleanup EXIT

stage_dir="$tmp_root/stage"
list_file="$tmp_root/archive.list"
mkdir -p "$stage_dir"

declare -A manifest_times
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^(.*)[[:space:]]+([0-9]+)$ ]] || {
        echo "invalid manifest line: $line" >&2
        exit 1
    }
    manifest_times["${BASH_REMATCH[1]}"]="${BASH_REMATCH[2]}"
done < "$manifest_path"

is_forced_text_extension() {
    case "$1" in
        *.txt|*.md|*.py|*.sh|*.c|*.h|*.js|*.css|*.html|*.xml|*.json|*.yaml|*.yml)
            return 0
            ;;
    esac
    return 1
}

is_text_file() {
    local path="$1"
    local mime
    mime=$(file --mime-type -b -- "$path")
    [[ "$mime" == text/* ]] && return 0
    is_forced_text_extension "$path"
}

has_shebang() {
    local path="$1"
    LC_ALL=C dd if="$path" bs=2 count=1 status=none 2>/dev/null | cmp -s - <(printf '#!')
}

lookup_epoch() {
    local rel="$1"
    if [[ -n "${manifest_times[$rel]+x}" ]]; then
        printf '%s' "${manifest_times[$rel]}"
    else
        printf '%s' "$default_epoch"
    fi
}

cd "$src_dir"
while IFS= read -r -d '' entry; do
    rel=${entry#./}
    src_path="$src_dir/$rel"
    dst_path="$stage_dir/$rel"

    if [[ -f "$src_path" && ! -L "$src_path" ]]; then
        case "$rel" in
            *.tmp|*.pyc|*.o)
                continue
                ;;
        esac

        if [[ "$(stat -c '%a' -- "$src_path")" == "600" ]]; then
            continue
        fi
    fi

    if [[ -d "$src_path" && ! -L "$src_path" ]]; then
        mkdir -p -- "$dst_path"
        continue
    fi

    mkdir -p -- "$(dirname "$dst_path")"
    cp -a -- "$src_path" "$dst_path"
done < <(find . -mindepth 1 \( -type d \( -name .git -o -name node_modules -o -name tmp -o -name .cache -o -name __pycache__ \) -prune \) -o -print0)

while IFS= read -r -d '' entry; do
    rel=${entry#./}
    path="$stage_dir/$rel"

    if [[ -d "$path" && ! -L "$path" ]]; then
        chmod 0755 -- "$path"
        continue
    fi

    if [[ -f "$path" && ! -L "$path" ]]; then
        if is_text_file "$path"; then
            perl -0pi -e 's/\r\n/\n/g' -- "$path"
        fi

        if [[ -x "$path" ]] || has_shebang "$path"; then
            chmod 0755 -- "$path"
        else
            chmod 0644 -- "$path"
        fi
    fi
done < <(cd "$stage_dir" && find . -mindepth 1 -print0)

while IFS= read -r -d '' entry; do
    rel=${entry#./}
    path="$stage_dir/$rel"
    touch -h -d "@$(lookup_epoch "$rel")" -- "$path"
done < <(cd "$stage_dir" && find . -mindepth 1 -print0)

(
    cd "$stage_dir"
    find . -mindepth 1 -printf '%P\0' | sort -z > "$list_file"
    tar \
        --format=gnu \
        --no-recursion \
        --sort=name \
        --owner=0 \
        --group=0 \
        --numeric-owner \
        --null \
        -T "$list_file" \
        -cf - \
        | zstd -19 --long --no-check --single-thread -o "$output_path"
)
EOF

chmod +x /app/build.sh
