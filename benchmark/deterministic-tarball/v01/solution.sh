#!/bin/bash
set -euo pipefail

cat > /app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

src_root="/app/src"
out_file="/app/release.tar.zst"
epoch="${SOURCE_DATE_EPOCH:-946684800}"
stage_dir="$(mktemp -d)"
trap 'rm -rf "$stage_dir"' EXIT

python3 - "$src_root" "$stage_dir" <<'PY'
import fnmatch
import os
import shutil
import stat
import sys
from pathlib import Path

src_root = Path(sys.argv[1])
stage_dir = Path(sys.argv[2])

ignore_file = src_root / ".distignore"
patterns = []
for line in ignore_file.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    patterns.append(line)


def matches_pattern(rel_path: str, pattern: str) -> bool:
    parts = tuple(part for part in rel_path.split("/") if part)
    if pattern.endswith("/"):
        directory_pattern = pattern[:-1]
        if directory_pattern.startswith("**/"):
            suffix = directory_pattern[3:]
            return suffix in parts
        return rel_path == directory_pattern or rel_path.startswith(directory_pattern + "/")

    name = parts[-1] if parts else ""
    return fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(name, pattern)


def should_exclude(rel_path: str, source_path: Path) -> bool:
    if source_path.is_file() and not source_path.is_symlink():
        if stat.S_IMODE(source_path.stat(follow_symlinks=False).st_mode) == 0o600:
            return True

    return any(matches_pattern(rel_path, pattern) for pattern in patterns)


def is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def normalized_file_mode(source_path: Path, data: bytes) -> int:
    source_mode = stat.S_IMODE(source_path.stat(follow_symlinks=False).st_mode)
    if source_mode & 0o111 or data.startswith(b"#!"):
        return 0o755
    return 0o644


def copy_tree(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(target_dir, 0o755)

    for entry in sorted(os.scandir(source_dir), key=lambda item: item.name):
        rel_path = entry.path[len(str(src_root)) + 1 :].replace(os.sep, "/")
        source_path = Path(entry.path)
        target_path = target_dir / entry.name

        if should_exclude(rel_path, source_path):
            continue

        if entry.is_symlink():
            os.symlink(os.readlink(entry.path), target_path)
            continue

        if entry.is_dir(follow_symlinks=False):
            copy_tree(source_path, target_path)
            continue

        if not entry.is_file(follow_symlinks=False):
            continue

        data = source_path.read_bytes()
        if is_text(data):
            data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        target_path.write_bytes(data)
        os.chmod(target_path, normalized_file_mode(source_path, data))


copy_tree(src_root, stage_dir)
PY

rm -f "$out_file"

LC_ALL=C tar \
  --sort=name \
  --format=gnu \
  --mtime="@${epoch}" \
  --owner=0 \
  --group=0 \
  --numeric-owner \
  -C "$stage_dir" \
  -cf - \
  . | zstd -19 --long --no-check --single-thread -o "$out_file"
EOF

chmod +x /app/build.sh
