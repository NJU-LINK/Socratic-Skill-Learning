#!/bin/bash
set -euo pipefail

cat > /app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

export LC_ALL=C

src_root="/app/src"
metadata_file="/app/build-metadata/epoch.txt"
archive_path="/app/release.tar.zst"

epoch="$(tr -d '\r\n' < "$metadata_file")"
if [[ ! "$epoch" =~ ^[0-9]+$ ]]; then
    echo "invalid epoch: $epoch" >&2
    exit 1
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

stage_dir="$workdir/stage"
mkdir -p "$stage_dir"

is_text_file() {
    local path="$1"
    local encoding

    encoding="$(file --brief --mime-encoding -- "$path")"
    [[ "$encoding" != "binary" ]]
}

has_shebang() {
    local path="$1"

    python3 - "$path" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
with path.open('rb') as handle:
    sys.exit(0 if handle.read(2) == b'#!' else 1)
PY
}

normalize_text_file() {
    local src="$1"
    local dest="$2"

    python3 - "$src" "$dest" <<'PY'
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])
data = src.read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n')
dest.write_bytes(data)
PY
}

while IFS= read -r -d '' src_path; do
    rel_path="${src_path#"$src_root"/}"

    case "$rel_path" in
        .git|.git/*|node_modules|node_modules/*|cache|cache/*|credentials|credentials/*|*.pyc|*.o|*.bak|*/__pycache__|*/__pycache__/*)
            continue
            ;;
    esac

    if [[ -L "$src_path" && ! -e "$src_path" ]]; then
        continue
    fi

    dest_path="$stage_dir/$rel_path"

    if [[ -d "$src_path" ]]; then
        mkdir -p "$dest_path"
        chmod 0750 "$dest_path"
        continue
    fi

    mkdir -p "$(dirname "$dest_path")"

    if [[ -L "$src_path" ]]; then
        ln -s "$(readlink "$src_path")" "$dest_path"
        continue
    fi

    if [[ -f "$src_path" ]]; then
        if is_text_file "$src_path"; then
            normalize_text_file "$src_path" "$dest_path"
        else
            cp -- "$src_path" "$dest_path"
        fi

        if [[ "$rel_path" == config/* ]]; then
            chmod 0640 "$dest_path"
        elif [[ -x "$src_path" ]] || has_shebang "$src_path"; then
            chmod 0555 "$dest_path"
        else
            chmod 0444 "$dest_path"
        fi
    fi
done < <(find "$src_root" -mindepth 1 -print0 | sort -z)

rm -f "$archive_path"

find "$stage_dir" -mindepth 1 -type d -exec chmod 0750 {} +

find "$stage_dir" -mindepth 1 -printf '%P\0' \
    | sort -z \
    | tar --null \
        --no-recursion \
        --directory="$stage_dir" \
        --format=gnu \
        --sort=name \
        --owner=0 \
        --group=0 \
        --numeric-owner \
        --mtime="@$epoch" \
        --files-from=- \
        -cf - \
    | zstd -q -T1 -10 -o "$archive_path"
EOF

chmod +x /app/build.sh
