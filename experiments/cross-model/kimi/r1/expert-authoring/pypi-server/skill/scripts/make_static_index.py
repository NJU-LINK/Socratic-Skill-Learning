#!/usr/bin/env python3
"""Generate a static PEP 503 "simple" index from a directory of dist artifacts.

Usage:
    python3 make_static_index.py DIST_DIR INDEX_ROOT [--name FORCE_NAME]

- Copies every *.whl, *.tar.gz, and *.zip from DIST_DIR into
  INDEX_ROOT/simple/<normalized-project-name>/
- Writes index.html files that pip's PEP 503 resolver understands
  (project list at simple/index.html, per-project file lists with
  #sha256= fragments).
- --name forces all artifacts under one project name (use when a
  filename does not parse cleanly).

Serve the result with any static file server, e.g.:
    cd INDEX_ROOT && nohup python3 -m http.server 8091 --bind 0.0.0.0 & disown
Then: pip install --index-url http://localhost:8091/simple <project>
"""
import argparse
import hashlib
import html
import os
import re
import shutil
import sys

ARTIFACT_SUFFIXES = (".whl", ".tar.gz", ".zip")


def normalize(name: str) -> str:
    """PEP 503 normalized project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def split_filename(fn: str):
    """Return (project-name, version) parsed from an artifact filename.

    Wheels:   {distribution}-{version}-...  where distribution never
              contains '-' (escaped as '_'), so version is exactly part 2.
    Sdists:   {name}-{version}.tar.gz — split at the last '-' that is
              followed by a digit (PEP 625 names escape '-' as '_').
    """
    if fn.endswith(".whl"):
        parts = fn[:-4].split("-")
        if len(parts) < 2:
            raise ValueError(f"cannot parse wheel filename: {fn}")
        return parts[0], parts[1]
    base = re.sub(r"\.(tar\.gz|zip)$", "", fn)
    parts = base.split("-")
    for i in range(len(parts) - 1, 0, -1):
        if parts[i] and parts[i][0].isdigit():
            return "-".join(parts[:i]), "-".join(parts[i:])
    raise ValueError(f"cannot parse project/version from filename: {fn}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dist_dir", help="directory containing built artifacts")
    ap.add_argument("index_root", help="output root; 'simple/' is created inside")
    ap.add_argument("--name", help="force this project name for all artifacts")
    args = ap.parse_args()

    simple = os.path.join(args.index_root, "simple")
    files = [f for f in sorted(os.listdir(args.dist_dir))
             if f.endswith(ARTIFACT_SUFFIXES) and os.path.isfile(os.path.join(args.dist_dir, f))]
    if not files:
        sys.exit(f"no artifacts (*.whl, *.tar.gz, *.zip) found in {args.dist_dir}")

    projects = {}
    for fn in files:
        name = normalize(args.name) if args.name else normalize(split_filename(fn)[0])
        dest_dir = os.path.join(simple, name)
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(os.path.join(args.dist_dir, fn), os.path.join(dest_dir, fn))
        projects.setdefault(name, []).append(fn)

    with open(os.path.join(simple, "index.html"), "w") as f:
        f.write("<!DOCTYPE html><html><head><title>Simple Index</title></head><body>")
        for name in sorted(projects):
            f.write(f'<a href="{name}/">{html.escape(name)}</a><br>')
        f.write("</body></html>")

    for name, fns in projects.items():
        d = os.path.join(simple, name)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(f"<!DOCTYPE html><html><head><title>Links for {html.escape(name)}</title>"
                    '</head><body><meta name="pypi:repository-version" content="1.0">')
            for fn in sorted(fns):
                with open(os.path.join(d, fn), "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
                f.write(f'<a href="{fn}#sha256={digest}">{html.escape(fn)}</a><br>')
            f.write("</body></html>")
        print(f"{name}: {', '.join(sorted(fns))}")

    print(f"Static index written under {simple}")
    print(f"Serve with: cd {args.index_root} && nohup python3 -m http.server <PORT> & disown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
