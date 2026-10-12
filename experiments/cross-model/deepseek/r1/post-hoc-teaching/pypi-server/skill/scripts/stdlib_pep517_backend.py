#!/usr/bin/env python3
"""Minimal PEP 517 build backend using ONLY the Python stdlib.

Purpose: makes a package **source-only publishable with zero build
dependencies**. Copy or symlink this file to the project root as `backend.py`
and declare:

    [build-system]
    requires = []            # isolation env installs NOTHING - backend is stdlib only
    build-backend = "backend"
    backend-path = ["."]

Then a bare index containing only the sdist installs with the plain,
unmodified command `pip install --index-url http://localhost:PORT/simple
<dist>==<ver>` — fully offline, no setuptools/hatchling/etc. needed anywhere.

Verified end-to-end in the anchor environment (pip 25.x, fresh venv, bare
static index containing ONLY the .tar.gz, plain command, import from the
installed copy) for BOTH promised configurations [v01]:
- flat layout:  PKG_DIR = "mypkg"        -> wheel 'mypkg/__init__.py', sdist has mypkg/
- src layout:   PKG_DIR = "src/mypkg"    -> wheel 'mypkg/__init__.py' (NOT src-prefixed),
                                            sdist has src/mypkg/

Adjust NAME / VERSION / PKG_DIR (and WHEEL_TAG if needed) for the target
project. NAME is the *distribution* name (index URL, filenames, pip
requirement); the import package is the basename of PKG_DIR — dist name and
import name may differ (e.g. dist `vec_ops`, package dir `vecops`), the wheel
entries follow the import package automatically.

Traps that WILL bite otherwise:
- If the sdist is ever built by setuptools instead of this backend, add
  `include backend.py` to MANIFEST.in (setuptools does not auto-include
  root-level non-package files).
- PEP 517 sdists must contain `<name>-<ver>/PKG-INFO`; without it,
  `python -m build` (>= 1.6) rejects the sdist. This backend emits it.
- src layout: wheel entries must be relative to the INSTALL ROOT, and the
  sdist must contain the whole package tree. This backend strips the
  `src/` prefix from wheel entries (`_pkg_strip`) and includes the top-level
  source dir in the sdist (`_sdist_items`), then raises loudly if the wheel
  would be empty or src-prefixed — guard against the silent
  "install succeeds, import fails" failure mode.
"""
import base64
import hashlib
import io
import os
import tarfile
import zipfile

NAME = "vecpure"            # distribution name (must match [project] name)
VERSION = "0.1.0"           # exact required version
PKG_DIR = "vecpure"         # import-package directory, relative to project root
                            #   flat: "mypkg"   src: "src/mypkg"
WHEEL_TAG = "py3-none-any"

DIST_INFO = f"{NAME}-{VERSION}.dist-info"

METADATA = (
    "Metadata-Version: 2.1\n"
    f"Name: {NAME}\n"
    f"Version: {VERSION}\n"
)
WHEEL = (
    "Wheel-Version: 1.0\n"
    "Generator: stdlib-backend\n"
    "Root-Is-Purelib: true\n"
    f"Tag: {WHEEL_TAG}\n"
)


def _b64(data: bytes) -> str:
    # wheel RECORD hashes: sha256, urlsafe base64, no padding
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def _write_dist_info(metadata_directory):
    d = os.path.join(metadata_directory, DIST_INFO)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "METADATA"), "w", encoding="utf-8") as f:
        f.write(METADATA)
    with open(os.path.join(d, "WHEEL"), "w", encoding="utf-8") as f:
        f.write(WHEEL)
    return DIST_INFO


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    # pip may import this module in-process, so keep imports stdlib-only
    return _write_dist_info(metadata_directory)


def _pkg_strip():
    # wheel entries are relative to the INSTALL ROOT, not the project root:
    # src layout ("src/mypkg") -> strip "src" => entries are "mypkg/...";
    # flat layout ("mypkg")    -> strip "."  => entries are "mypkg/...".
    return os.path.dirname(PKG_DIR) or "."


def _pkg_files():
    if not os.path.isdir(PKG_DIR):
        raise RuntimeError(f"PKG_DIR={PKG_DIR!r} does not exist (called from {os.getcwd()})")
    for root, _, files in os.walk(PKG_DIR):
        for fn in sorted(files):
            p = os.path.join(root, fn)
            yield p, os.path.relpath(p, _pkg_strip())


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    os.makedirs(wheel_directory, exist_ok=True)
    wheel_path = os.path.join(wheel_directory, f"{NAME}-{VERSION}-{WHEEL_TAG}.whl")
    records = []
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as z:
        pkg_rels = []
        for abs_path, rel in _pkg_files():
            data = open(abs_path, "rb").read()
            z.writestr(rel, data)
            records.append((rel, _b64(data), len(data)))
            pkg_rels.append(rel)
        # loud self-checks: never ship a silently-broken wheel
        if not pkg_rels:
            raise RuntimeError(f"no files found under PKG_DIR={PKG_DIR!r}; wheel would be empty")
        bad = [r for r in pkg_rels if r.startswith("src/") or r.startswith("/")]
        if bad:
            raise RuntimeError(f"wheel entries not install-root-relative: {bad}")
        for fn, content in (("METADATA", METADATA), ("WHEEL", WHEEL)):
            rel = f"{DIST_INFO}/{fn}"
            data = content.encode("utf-8")
            z.writestr(rel, data)
            records.append((rel, _b64(data), len(data)))
        rec_lines = [f"{p},sha256={h},{s}" for p, h, s in records]
        rec_lines.append(f"{DIST_INFO}/RECORD,,")  # RECORD's own row: no hash/size
        z.writestr(f"{DIST_INFO}/RECORD", "\n".join(rec_lines) + "\n")
    return os.path.basename(wheel_path)


def _sdist_items():
    # include the top-level dir that CONTAINS the package: "src" for src layout,
    # the package dir itself for flat layout; never the literal "src/mypkg".
    top = os.path.dirname(PKG_DIR) or PKG_DIR
    for item in sorted(os.listdir(".")):
        if item == top or item in ("pyproject.toml", "backend.py",
                                   "MANIFEST.in", "README.md", "PKG-INFO"):
            yield item


def build_sdist(sdist_directory, config_settings=None):
    os.makedirs(sdist_directory, exist_ok=True)
    sdist_path = os.path.join(sdist_directory, f"{NAME}-{VERSION}.tar.gz")
    base = f"{NAME}-{VERSION}"
    with tarfile.open(sdist_path, "w:gz") as t:
        for item in _sdist_items():
            t.add(item, arcname=f"{base}/{item}")
        info = tarfile.TarInfo(f"{base}/PKG-INFO")  # required by PEP 517 validators
        data = METADATA.encode("utf-8")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return os.path.basename(sdist_path)