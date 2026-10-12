#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Deterministic Tarball Build Script — Reference Template
#
# Adaptable to any source tree + .distignore + output path.
# Override via environment:
#   SRC          — source tree root        (default: /app/src)
#   OUT          — output archive path     (default: /app/release.tar.zst)
#   MTIME        — epoch seconds           (default: $SOURCE_DATE_EPOCH or 946684800)
#   DISTIGNORE   — ignore-file name        (default: .distignore)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SRC="${SRC:-/app/src}"
OUT="${OUT:-/app/release.tar.zst}"
MTIME="${SOURCE_DATE_EPOCH:-946684800}"
DISTIGNORE="${DISTIGNORE:-.distignore}"

STAGING=$(mktemp -d)
FILELIST=$(mktemp)
trap 'rm -rf "$STAGING" "$FILELIST"' EXIT

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Enumerate + Exclude → Stage
# ═══════════════════════════════════════════════════════════════════════════════
python3 - "$SRC" "$STAGING" "$DISTIGNORE" << 'PYEOF'
import os, sys, re, shutil

src_root   = sys.argv[1]
staging    = sys.argv[2]
ignore_name = sys.argv[3]

# ── Parse ignore file ────────────────────────────────────────────────────────
ignore_path = os.path.join(src_root, ignore_name)
patterns = []
if os.path.exists(ignore_path):
    with open(ignore_path) as f:
        for line in f:
            line = line.rstrip('\n').rstrip('\r')
            if not line or line.startswith('#'):
                continue
            negate = line.startswith('!')
            if negate: line = line[1:]
            dir_only = line.endswith('/')
            if dir_only: line = line[:-1]
            if not line: continue
            anchored = line.startswith('/') or '/' in line
            if line.startswith('/'): line = line[1:]

            # glob → regex
            rx, i, n = '', 0, len(line)
            while i < n:
                c = line[i]
                if c == '*' and i+1 < n and line[i+1] == '*':
                    if i+2 < n and line[i+2] == '/':
                        rx += '(?:.+/)?'; i += 3
                    else:
                        rx += '.*'; i += 2
                elif c == '*':   rx += '[^/]*'; i += 1
                elif c == '?':   rx += '[^/]';  i += 1
                else:            rx += re.escape(c); i += 1

            patterns.append(dict(regex=re.compile(rx), negate=negate,
                                 dir_only=dir_only, anchored=anchored))

def is_ignored(relpath, is_dir):
    result = False
    for p in patterns:
        if p['dir_only'] and not is_dir: continue
        if p['anchored']:
            matched = p['regex'].fullmatch(relpath)
        else:
            matched = p['regex'].fullmatch(relpath.rsplit('/',1)[-1])
        if matched: result = not p['negate']
    return result

# ── Recursive walk ───────────────────────────────────────────────────────────
def walk(src, prefix):
    full = os.path.join(src, prefix) if prefix else src
    try: entries = sorted(os.listdir(full))
    except OSError: return
    subdirs = []
    for name in entries:
        fp = os.path.join(full, name)
        rp = os.path.join(prefix, name) if prefix else name
        if os.path.islink(fp):
            if is_ignored(rp, False): continue
            dst = os.path.join(staging, rp)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.symlink(os.readlink(fp), dst)
        elif os.path.isdir(fp):
            if is_ignored(rp, True): continue
            os.makedirs(os.path.join(staging, rp), exist_ok=True)
            subdirs.append(name)
        elif os.path.isfile(fp):
            if os.stat(fp).st_mode & 0o777 == 0o600: continue
            if is_ignored(rp, False): continue
            dst = os.path.join(staging, rp)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(fp, dst)
    for d in subdirs:
        walk(src, os.path.join(prefix, d) if prefix else d)

walk(src_root, '')
PYEOF

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Normalize permissions + line endings
# ═══════════════════════════════════════════════════════════════════════════════
find "$STAGING" -type d -exec chmod 0755 {} +

find "$STAGING" -type f -print0 | while IFS= read -r -d '' file; do
    is_exec=false
    [ -x "$file" ] && is_exec=true
    [ "$(head -c2 "$file" 2>/dev/null)" = '#!' ] && is_exec=true
    $is_exec && chmod 0755 "$file" || chmod 0644 "$file"

    mime=$(file --mime-type -b "$file")
    case "$mime" in text/*) sed -i 's/\r$//' "$file" ;; esac
done

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: Sorted file list
# ═══════════════════════════════════════════════════════════════════════════════
(cd "$STAGING" && find . -mindepth 1 -print0 | sort -z) > "$FILELIST"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: Deterministic tar + zstd
# ═══════════════════════════════════════════════════════════════════════════════
tar --create --file=- \
    --directory="$STAGING" \
    --sort=name \
    --owner=0:0 --group=0:0 \
    --mtime="@${MTIME}" \
    --format=gnu \
    --null --no-recursion --files-from="$FILELIST" \
  | zstd -19 --long --no-check --single-thread \
    > "$OUT"
