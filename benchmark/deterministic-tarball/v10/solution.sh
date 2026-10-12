#!/bin/bash

set -euo pipefail

cat >/app/build.sh <<'EOF'
#!/bin/bash

set -euo pipefail

export LC_ALL=C
export TZ=UTC

src=/app/site-src
out=/app/site.tar
epoch=${SOURCE_DATE_EPOCH:-946684800}
staging=$(mktemp -d)

cleanup() {
    rm -rf "$staging"
}
trap cleanup EXIT

mkdir -p "$staging"

normalize_text_file() {
    local src_path="$1"
    local dst_path="$2"
    python3 - "$src_path" "$dst_path" <<'PY'
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
data = src.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
dst.write_bytes(data)
PY
}

copy_entry() {
    local rel="$1"
    local src_path="$src/$rel"
    local dst_path="$staging/$rel"
    local parent

    parent=$(dirname "$dst_path")
    mkdir -p "$parent"
    chmod 0755 "$parent"

    if [ -L "$src_path" ]; then
        if [ ! -e "$src_path" ]; then
            return
        fi
        ln -s "$(readlink "$src_path")" "$dst_path"
        return
    fi

    if [ -d "$src_path" ]; then
        mkdir -p "$dst_path"
        chmod 0755 "$dst_path"
        return
    fi

    case "$rel" in
        *.html|*.css|*.js|*.json)
            normalize_text_file "$src_path" "$dst_path"
            ;;
        *)
            cp -p -- "$src_path" "$dst_path"
            ;;
    esac

    case "$rel" in
        cgi-bin/*)
            chmod 0755 "$dst_path"
            ;;
        *)
            chmod 0644 "$dst_path"
            ;;
    esac
}

while IFS= read -r -d '' path; do
    rel=${path#"$src"/}
    if [ "$path" = "$src" ]; then
        continue
    fi
    copy_entry "$rel"
done < <(
    find -P "$src" \
        \( -type d \( -name drafts -o -name preview-cache -o \( -name '.*' ! -name '.well-known' \) \) -prune \) \
        -o \( -type f -name '*.map' -prune \) \
        -o -print0
)

tar \
    --format=posix \
    --pax-option=delete=atime,delete=ctime \
    --sort=name \
    --mtime="@$epoch" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -cf "$out" \
    -C "$staging" .
EOF

chmod +x /app/build.sh
