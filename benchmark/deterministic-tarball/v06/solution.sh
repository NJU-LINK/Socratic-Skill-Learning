#!/bin/bash
set -euo pipefail

cat >/app/build.sh <<'EOF'
#!/bin/bash
set -euo pipefail

export LC_ALL=C
export LANG=C
export TZ=UTC

src_root="/app/sdk"
output_path="/app/sdk-snapshot.tar.zst"
epoch="${SOURCE_DATE_EPOCH:-1704067200}"

tmp_root="$(mktemp -d)"
cleanup() {
    rm -rf "$tmp_root"
}
trap cleanup EXIT

stage_root="$tmp_root/stage"
mkdir -p "$stage_root/sdk"

python3 - "$src_root" "$stage_root/sdk" "$epoch" <<'PY'
import os
import stat
import sys
from pathlib import Path

src_root = Path(sys.argv[1])
dst_root = Path(sys.argv[2])
epoch = int(sys.argv[3])


def is_excluded(rel_parts, st_mode, is_symlink):
    if any(part == ".git" for part in rel_parts):
        return True
    if any(part in {"cache", "tmp", "__pycache__"} for part in rel_parts):
        return True
    if is_symlink:
        return False

    name = rel_parts[-1]
    if name.endswith((".tmp", ".pyc", ".o")):
        return True
    if stat.S_IMODE(st_mode) == 0o600:
        return True
    return False


def write_regular_file(src_path, dst_path, st_mode):
    data = src_path.read_bytes()
    is_text = b"\x00" not in data
    if is_text:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    is_executable = bool(st_mode & 0o111)
    has_shebang = data.startswith(b"#!")
    mode = 0o755 if (is_executable or has_shebang) else 0o644

    dst_path.write_bytes(data)
    os.chmod(dst_path, mode)
    os.utime(dst_path, (epoch, epoch))


def copy_tree(src_dir, dst_dir, rel_parts=()):
    os.chmod(dst_dir, 0o755)
    os.utime(dst_dir, (epoch, epoch))

    for entry in sorted(os.scandir(src_dir), key=lambda item: os.fsencode(item.name)):
        entry_src = Path(entry.path)
        entry_dst = dst_dir / entry.name
        entry_rel = rel_parts + (entry.name,)
        st = os.lstat(entry_src)
        is_symlink = stat.S_ISLNK(st.st_mode)
        is_dir = stat.S_ISDIR(st.st_mode)

        if is_excluded(entry_rel, st.st_mode, is_symlink):
            continue

        if is_symlink:
            os.symlink(os.readlink(entry_src), entry_dst)
            continue

        if is_dir:
            entry_dst.mkdir(exist_ok=False)
            copy_tree(entry_src, entry_dst, entry_rel)
            continue

        if stat.S_ISREG(st.st_mode):
            write_regular_file(entry_src, entry_dst, st.st_mode)


copy_tree(src_root, dst_root)
PY

members_file="$tmp_root/members.list"
python3 - "$stage_root" "$members_file" <<'PY'
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
members_file = Path(sys.argv[2])


def collect(path):
    st = os.lstat(path)
    rel = path.relative_to(root).as_posix()
    members = [rel]
    if stat.S_ISDIR(st.st_mode):
        for child in sorted(path.iterdir(), key=lambda item: os.fsencode(item.name)):
            members.extend(collect(child))
    return members


members = collect(root / "sdk")
with members_file.open("wb") as fh:
    for member in members:
        fh.write(member.encode("utf-8"))
        fh.write(b"\0")
PY

tar_path="$tmp_root/sdk-snapshot.tar"
tar \
    --format=posix \
    --pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    --no-recursion \
    --mtime="@${epoch}" \
    -C "$stage_root" \
    --null \
    --files-from "$members_file" \
    -cf "$tar_path"

zstd -19 --long --no-check --single-thread -f "$tar_path" -o "$output_path"
EOF

chmod +x /app/build.sh
/app/build.sh
