#!/bin/bash
set -euo pipefail

cat >/app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

src_dir=/app/src
manifest_path="$src_dir/release.manifest"
out_dir=/app/out
bundle_path="$out_dir/release.bundle.tar.zst"
default_mtime="${SOURCE_DATE_EPOCH:-946684800}"

mkdir -p "$out_dir"

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

stage_dir="$workdir/stage"
list_path="$workdir/archive.list"
mkdir -p "$stage_dir"

python3 - "$src_dir" "$manifest_path" "$stage_dir" "$list_path" "$default_mtime" <<'PY'
import os
import shutil
import stat
import sys
from pathlib import Path, PurePosixPath


def parse_manifest(path: Path):
    rules = []
    current_mtime = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise SystemExit(f"Invalid manifest line: {raw_line}")
        command, value = parts
        if command == "set-mtime":
            current_mtime = int(value)
            continue
        if command not in {"include", "exclude"}:
            raise SystemExit(f"Unsupported manifest command: {command}")
        rules.append((command, value, current_mtime))
    return rules


def walk_entry(root: Path, entry: Path):
    rel = entry.relative_to(root).as_posix()
    if entry.is_dir() and not entry.is_symlink():
        items = [rel + "/"]
        for child in sorted(entry.iterdir(), key=lambda item: item.name):
            items.extend(walk_entry(root, child))
        return items
    return [rel]


def collect_all_paths(root: Path):
    items = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        items.extend(walk_entry(root, child))
    return items


def matches_glob(path_text: str, pattern: str):
    return PurePosixPath(path_text.rstrip("/")).match(pattern.rstrip("/"))


def expand_include(root: Path, pattern: str, known_paths):
    exact = root / pattern.rstrip("/")
    if pattern.endswith("/"):
        if exact.exists() and exact.is_dir() and not exact.is_symlink():
            return walk_entry(root, exact)
        return []
    if exact.exists() or exact.is_symlink():
        return walk_entry(root, exact)
    return [path_text for path_text in known_paths if matches_glob(path_text, pattern)]


def looks_text(data: bytes):
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def normalized_mode(src_path: Path, data: bytes | None):
    if src_path.is_dir() and not src_path.is_symlink():
        return 0o755
    if src_path.is_symlink():
        return None
    src_mode = stat.S_IMODE(os.lstat(src_path).st_mode)
    if data is not None and data.startswith(b"#!"):
        return 0o755
    if src_mode & 0o111:
        return 0o755
    return 0o644


def set_mtime(path: Path, mtime: int, follow_symlinks: bool):
    os.utime(path, (mtime, mtime), follow_symlinks=follow_symlinks)


src_dir = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
stage_dir = Path(sys.argv[3])
list_path = Path(sys.argv[4])
default_mtime = int(sys.argv[5])

all_paths = collect_all_paths(src_dir)
rules = parse_manifest(manifest_path)

selected = []
selected_set = set()
mtimes = {}

for kind, pattern, explicit_mtime in rules:
    matches = expand_include(src_dir, pattern, all_paths)
    if kind == "include":
        for path_text in matches:
            if path_text in selected_set:
                selected.remove(path_text)
            else:
                selected_set.add(path_text)
            selected.append(path_text)
            mtimes[path_text] = explicit_mtime if explicit_mtime is not None else default_mtime
    else:
        for path_text in matches:
            if path_text in selected_set:
                selected.remove(path_text)
                selected_set.remove(path_text)
            mtimes.pop(path_text, None)

for path_text in selected:
    source = src_dir / path_text.rstrip("/")
    target = stage_dir / path_text.rstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    mtime = mtimes[path_text]

    if path_text.endswith("/"):
        target.mkdir(parents=True, exist_ok=True)
        os.chmod(target, normalized_mode(source, None))
        set_mtime(target, mtime, True)
        continue

    if source.is_symlink():
        if target.exists() or target.is_symlink():
            target.unlink()
        os.symlink(os.readlink(source), target)
        set_mtime(target, mtime, False)
        continue

    data = source.read_bytes()
    out_data = data
    if looks_text(data):
        out_data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    target.write_bytes(out_data)
    os.chmod(target, normalized_mode(source, data))
    set_mtime(target, mtime, True)

for path_text in selected:
    if path_text.endswith("/"):
        target = stage_dir / path_text.rstrip("/")
        os.chmod(target, 0o755)
        set_mtime(target, mtimes[path_text], True)

with list_path.open("wb") as handle:
    for path_text in selected:
        handle.write(path_text.rstrip("/").encode("utf-8"))
        handle.write(b"\0")
PY

tmp_tar="$workdir/release.bundle.tar"
tar --format=gnu \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    --no-recursion \
    --null \
    -C "$stage_dir" \
    -T "$list_path" \
    -cf "$tmp_tar"

zstd -19 --single-thread --no-check -f "$tmp_tar" -o "$bundle_path"
EOF

chmod +x /app/build.sh
