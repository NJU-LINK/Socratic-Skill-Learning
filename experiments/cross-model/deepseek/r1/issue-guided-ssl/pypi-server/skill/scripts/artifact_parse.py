"""Shared artifact-filename parsing for the pypi-server pipeline.

Three textual forms of a distribution name exist and must NEVER be confused:

1. Authored name : as declared in pyproject.toml/setup.py; appears verbatim in
   the wheel's .dist-info/METADATA as "Name: ..." (e.g. `vector-ops`).
2. PEP 503 page name : runs of [-_.]+ -> '-', lowercased (e.g. `vector-ops`);
   this is the URL/directory space (/simple/vector-ops/).
3. PEP 427 wheel-filename form : non-alphanumeric-dot runs -> '_'
   (e.g. `vector_ops-0.1.0-py3-none-any.whl`). Sdist filenames are
   backend-dependent: setuptools emits underscore-escaped names
   (email_validator-2.1.1.tar.gz), other backends/eras emit hyphens
   (python-dateutil-2.9.0.tar.gz) -- never guess which.

RULE: never build a glob by interpolating the distribution name. Enumerate the
files that exist, parse each filename, normalize the PARSED distribution with
PEP 503, and join on that normalized key.
"""
import re
from pathlib import Path


def normalize(name: str) -> str:
    """PEP 503 normalized name: runs of [-_.]+ -> single '-', lowercased."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_artifact(fn: str):
    """Return (distribution, version) parsed from a wheel or sdist filename,
    or None if unparseable.

    wheel: {dist}-{ver}-{pytag}-{abitag}-{plat}.whl (greedy dist, tags never
           contain '-')
    sdist: {name}-{version}.{tar.gz,zip} with version starting at a digit
    (greedy name; ambiguous only for pathological names ending in
    version-like segments -- acceptable, see pgk 'packaging' precedent)."""
    m = re.match(r"^(.+)-([^-]+)-([^-]+)-([^-]+)-([^-]+)\.whl$", fn)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^(.+)-([0-9][^-]*)\.(tar\.gz|zip)$", fn)
    if m:
        return m.group(1), m.group(2)
    return None


def pick_files(dist_dir, norm_name: str, version: str, kind: str):
    """Return the sorted files in dist_dir whose PARSED distribution
    normalizes (PEP 503) to norm_name and whose parsed version == version.

    kind: 'wheel' (.whl) or 'sdist' (.tar.gz/.zip).
    Unparseable files are excluded here; a separate composition check handles
    debris (warn by default, STRICT_DIST=1 fatal)."""
    hits = []
    for f in sorted(Path(dist_dir).iterdir()):
        if not f.is_file():
            continue
        pv = parse_artifact(f.name)
        if pv is None:
            continue
        dist, v = pv
        if normalize(dist) != norm_name or v != version:
            continue
        if kind == "wheel" and f.name.endswith(".whl"):
            hits.append(f)
        elif kind == "sdist" and f.name.endswith((".tar.gz", ".zip")):
            hits.append(f)
    return hits


def parse_meta_name(metadata_text: str):
    """Extract the authored 'Name:' from METADATA text, or None."""
    m = re.search(r"(?m)^Name:\s*(.*)$", metadata_text)
    return m.group(1).strip() if m else None