#!/bin/bash
set -euo pipefail

cat > /app/build.sh <<'BUILDSCRIPT'
#!/bin/bash
set -euo pipefail

SRC="${SRC:-/app/src}"
OUT="${OUT:-/app/dist/source.tar.xz}"
MTIME="${SOURCE_DATE_EPOCH:-946684800}"

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

STAGE="$TMPDIR/stage"
mkdir -p "$STAGE"

SRC="$SRC" STAGE="$STAGE" MTIME="$MTIME" python3 <<'PY'
import mimetypes
import os
import shutil
import stat
from pathlib import Path

src = Path(os.environ["SRC"])
stage = Path(os.environ["STAGE"])
mtime = int(os.environ["MTIME"])


def excluded(rel: str, path: Path) -> bool:
    parts = Path(rel).parts
    if not parts:
        return False
    if parts[0] in {"vendor", "target", ".rustup"}:
        return True
    if path.is_symlink() and path.name == "build-cache":
        return True
    if rel.endswith(".tmp"):
        return True
    return False


def should_normalize_text(path: Path) -> bool:
    if path.suffix in {".rs", ".toml", ".md"}:
        return True
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("text/"):
        return True
    try:
        with path.open("rb") as fh:
            chunk = fh.read(4096)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


entries = []
for root, dirs, files in os.walk(src, topdown=True, followlinks=False):
    root_path = Path(root)
    rel_root = root_path.relative_to(src)

    kept_dirs = []
    for name in sorted(dirs):
        candidate = root_path / name
        rel = str((rel_root / name).as_posix())
        if excluded(rel, candidate):
            continue
        kept_dirs.append(name)
        entries.append((rel, candidate))
    dirs[:] = kept_dirs

    for name in sorted(files):
        candidate = root_path / name
        rel = str((rel_root / name).as_posix())
        if excluded(rel, candidate):
            continue
        entries.append((rel, candidate))

for rel, path in sorted(entries, key=lambda item: item[0]):
    dest = stage / rel
    if path.is_symlink():
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.readlink(path), dest)
        continue
    if path.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        os.chmod(dest, 0o755)
        os.utime(dest, (mtime, mtime), follow_symlinks=False)
        continue
    if path.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if should_normalize_text(path):
            with path.open("rb") as src_fh, dest.open("wb") as dest_fh:
                for chunk in iter(lambda: src_fh.read(65536), b""):
                    dest_fh.write(chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        else:
            shutil.copyfile(path, dest)
        mode = path.stat().st_mode
        perms = 0o755 if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) else 0o644
        os.chmod(dest, perms)
        os.utime(dest, (mtime, mtime), follow_symlinks=False)

for dirpath, dirnames, _ in os.walk(stage):
    current = Path(dirpath)
    os.chmod(current, 0o755)
    os.utime(current, (mtime, mtime), follow_symlinks=False)
    for name in dirnames:
        target = current / name
        if target.is_symlink():
            continue
        os.chmod(target, 0o755)
        os.utime(target, (mtime, mtime), follow_symlinks=False)
PY

tar --sort=name \
    --format=gnu \
    --mtime="@$MTIME" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -C "$STAGE" \
    -cf - . | xz -9 --threads=1 -c > "$OUT"

echo "Created $OUT"
BUILDSCRIPT

chmod +x /app/build.sh
echo "Build script created at /app/build.sh"
