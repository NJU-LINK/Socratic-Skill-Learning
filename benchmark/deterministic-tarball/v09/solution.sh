#!/bin/bash
set -euo pipefail

cat > /app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

workspace=/app/workspace
output=/app/project.tar.gz
epoch="${SOURCE_DATE_EPOCH:-1609459200}"
stage_dir="$(mktemp -d)"
trap 'rm -rf "$stage_dir"' EXIT

STAGE_DIR="$stage_dir" WORKSPACE="$workspace" EPOCH="$epoch" python3 <<'PY'
import os
import stat
from pathlib import Path

workspace = Path(os.environ["WORKSPACE"])
stage_dir = Path(os.environ["STAGE_DIR"])
epoch = int(os.environ["EPOCH"])
project_root = stage_dir / "project"

project_root.mkdir(mode=0o755)
os.utime(project_root, (epoch, epoch), follow_symlinks=False)

exclude_dirs = {"build", ".deps", "cache", "credentials"}


def looks_like_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def normalized_mode(src: Path, st: os.stat_result) -> int:
    if src.is_dir():
        return 0o755
    if not src.is_file():
        return stat.S_IMODE(st.st_mode)
    if st.st_mode & 0o111:
        return 0o755
    try:
        with src.open("rb") as handle:
            return 0o755 if handle.read(2) == b"#!" else 0o644
    except OSError:
        return 0o644


for root, dirnames, filenames in os.walk(workspace, topdown=True, followlinks=False):
    dirnames[:] = sorted(name for name in dirnames if name not in exclude_dirs)
    filenames = sorted(filenames)

    root_path = Path(root)
    rel_root = root_path.relative_to(workspace)
    dest_root = project_root / rel_root

    if rel_root != Path('.'):
        dest_root.mkdir(exist_ok=True)
        os.chmod(dest_root, 0o755)
        os.utime(dest_root, (epoch, epoch), follow_symlinks=False)

    for name in dirnames:
        src_dir = root_path / name
        dest_dir = dest_root / name
        if src_dir.is_symlink():
            target = os.readlink(src_dir)
            os.symlink(target, dest_dir)
            continue
        dest_dir.mkdir(exist_ok=True)
        os.chmod(dest_dir, 0o755)
        os.utime(dest_dir, (epoch, epoch), follow_symlinks=False)

    for name in filenames:
        if name.endswith('.bak'):
            continue

        src_path = root_path / name
        dest_path = dest_root / name

        if src_path.is_symlink():
            os.symlink(os.readlink(src_path), dest_path)
            continue

        st = src_path.lstat()
        mode = normalized_mode(src_path, st)

        data = src_path.read_bytes()
        if src_path.suffix != '.patch' and looks_like_text(data):
            text = data.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
            dest_path.write_text(text, encoding='utf-8', newline='')
        else:
            dest_path.write_bytes(data)

        os.chmod(dest_path, mode)
        os.utime(dest_path, (epoch, epoch), follow_symlinks=False)
PY

tar --format=posix \
    --sort=name \
    --pax-option=delete=atime,delete=ctime \
    --numeric-owner \
    --owner=1000 \
    --group=1000 \
    --mtime="@${epoch}" \
    -cf - -C "$stage_dir" project | gzip -n -9 > "$output"
EOF

chmod +x /app/build.sh
