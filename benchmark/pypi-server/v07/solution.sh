#!/bin/bash
set -euo pipefail

root=/app
package_dir="$root/package-src"
dist_dir="$root/dist"
simple_dir="$root/simple/vector-ops"

rm -rf "$dist_dir"
mkdir -p "$dist_dir" "$simple_dir"
python3 -m build --no-isolation --sdist --wheel --outdir "$dist_dir" "$package_dir"

python3 - "$dist_dir" "$simple_dir" <<'PY'
from html import escape
from pathlib import Path
import sys

dist_dir = Path(sys.argv[1])
simple_dir = Path(sys.argv[2])
artifacts = sorted(path.name for path in dist_dir.iterdir() if path.is_file())
if not artifacts:
    raise SystemExit("no distribution artifacts were built")

links = "\n".join(
    f'<a href="../../dist/{escape(name)}">{escape(name)}</a><br/>'
    for name in artifacts
)
(simple_dir / "index.html").write_text(
    f"<!DOCTYPE html>\n<html><body>\n{links}\n</body></html>\n",
    encoding="utf-8",
)
PY

pkill -f "http.server 8080" 2>/dev/null || true
nohup python3 -m http.server 8080 --bind 127.0.0.1 --directory "$root" \
    >/tmp/vector-ops-index.log 2>&1 &

for _ in $(seq 1 40); do
  if curl -fsS http://localhost:8080/simple/vector-ops/ >/dev/null 2>&1; then
    exit 0
  fi
  sleep 0.25
done

cat /tmp/vector-ops-index.log >&2 || true
exit 1
