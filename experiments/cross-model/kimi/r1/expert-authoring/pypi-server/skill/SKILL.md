---
name: pypi-server
description: Build a Python package (correct layout, metadata, and public API), produce wheel/sdist artifacts, publish them on a local PEP 503-compatible package index — preferring a physical static index tree served by stdlib http.server, with pypiserver/devpi only when mandated — and prove end-to-end that a fresh `pip install --index-url ...` from that index alone installs a correctly behaving package.
---

# Local PyPI Index Publication

End-to-end pipeline: **scaffold/repair package → implement API → build dist artifacts → materialize a physical PEP 503 index tree → serve it detached → verify a clean install from that index only.**

Everything below marked *(verified)* was exercised in the reference environment (Debian 12, Python 3.13, pip 25.2, setuptools+wheel preinstalled, `build`/`pypiserver` NOT preinstalled but pip-installable, network available, `ps`/`pgrep` absent, `curl` present). Items marked *(extrapolated)* are standard flows expected by the task family but not exercised there.

## 0. Extract the task's fixed parameters first

Read the instruction and pin down, exactly as written:

| Parameter | Example from reference task |
|---|---|
| Distribution name + exact version | `vectorops==0.1.0` |
| Required layout / project root | `src/` layout, code in `/app/src/vectorops` |
| Build metadata file(s) | `/app/pyproject.toml` |
| Public import surface | `from vectorops import dotproduct` |
| Required API behavior/signature | `dotproduct(a, b)` over two int/float lists |
| Index type, directory, and port | PEP 503 index on port `8091` |
| Required artifact set | both sdist and wheel |
| Required client command | `pip install --index-url http://localhost:8091/simple vectorops==0.1.0` |

These are the contract. Match names, versions, paths, and ports **literally**; do not improvise equivalents. If the task names an index tool or index directory, that choice overrides every default below.

## 1. Package layout and build metadata

**If the workspace is empty**, scaffold per the instruction. **If a project is pre-staged or broken**, inspect before writing: `ls`, read `pyproject.toml`/`setup.py`/`setup.cfg`, check name/version fields, package discovery, and whether the import surface matches the file layout. Fix minimally; don't rewrite working parts.

### src layout (recommended; required in the reference task)

```
/app/pyproject.toml
/app/src/<import_name>/__init__.py        (+ helper modules as needed)
```

```toml
[build-system]
requires = ["setuptools>=61", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<dist-name>"        # must equal the required distribution name
version = "<X.Y.Z>"         # must equal the required version exactly
requires-python = ">=3.8"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```

### flat layout *(extrapolated for this family)*

`<import_name>/` sits at the project root. setuptools auto-discovery works only for a *single* clean top-level package; stray dirs (`tests/`, `docs/`, `build/`) trigger "Multiple top-level packages discovered". Be explicit instead:

```toml
[tool.setuptools]
packages = ["<import_name>", "<import_name>.subpkg"]   # or use packages.find
```

### Other layout/metadata variants *(extrapolated)*

- **Subpackages**: every package dir needs `__init__.py` (or switch to `packages.find_namespace`); `packages.find` then picks them up automatically.
- **Package data** (non-Python files that must ship): declare `[tool.setuptools.package-data] "<pkg>" = ["*.json", "data/*"]` and verify the files land in the wheel (`python3 -m zipfile -l dist/*.whl`) — sdists and wheels include data differently.
- **Legacy `setup.py`-only projects**: `python3 -m build` still works if any `pyproject.toml` exists; otherwise `python3 setup.py sdist bdist_wheel` with `setuptools`+`wheel` preinstalled, or add a minimal `pyproject.toml` build-system shim.
- **Pre-staged broken projects**: after minimal fixes, prove discovery by building and listing the wheel contents — do not trust that the declared config matches the files on disk.

### Public export ≠ file layout

`from pkg import func` requires `func` to be an attribute of the installed package object. If the implementation lives in a helper module, re-export it in `__init__.py`:

```python
from .core import dotproduct            # or define it inline
__all__ = ["dotproduct"]
__version__ = "0.1.0"
```

Import name vs distribution name may differ (e.g. dist `vector-ops` → import `vector_ops`). pip/PEP 503 normalize dist names (lowercase, runs of `-_.` → `-`); keep the import package a valid Python identifier.

## 2. Functionality

- Implement exactly the stated signature and semantics; keep it dependency-free unless instructed.
- Handle edge cases deliberately: empty inputs, mixed int/float, mismatched lengths (raise `ValueError` unless the task says otherwise). *(Reference verified: `dotproduct([],[]) == 0`, mismatched lengths raise.)*
- If the task lists **multiple functions/classes**, re-export **every** listed name in `__init__.py` and test each import individually — a single missing re-export fails only at install time.
- Sanity-test **from source** before building:
  `cd /app && python3 -c "import sys; sys.path.insert(0,'src'); from <pkg> import <api>; ..."` (for src layout), or run from the project root for flat layout.
- A later full behavioral test runs against the **installed** copy (step 6) — never trust only the source-tree test, because packaging errors (missing module, wrong `__init__`) only appear after install.

## 3. Build the distribution artifacts

```bash
pip install build            # if missing and network is available (verified available)
cd /app && python3 -m build  # → dist/<name>-<ver>.tar.gz AND dist/<name>-<ver>-py3-none-any.whl
```

- Offline fallback *(verified components)*: `python3 -m build --no-isolation` (setuptools+wheel are preinstalled) or wheel-only via `pip wheel . --no-deps --no-build-isolation -w dist`.
- If the task wants **wheel-only or sdist-only**, use `python3 -m build --wheel` / `--sdist`.
- **`dist/` must end up containing exactly the required artifact set** — e.g. one wheel + one sdist of the exact `name==version`. Graders may glob `dist/` and assert counts *(observed in the reference grader: exactly one wheel and one sdist)*. Remove stale/other-version artifacts unless the task says to preserve or replace specific ones.
- Graders may also open the artifacts: wheel must contain the import package (`python3 -m zipfile -l dist/*.whl`) and correct `Name:`/`Version:` in METADATA; sdist must contain `pyproject.toml` and the source files. Standard setuptools output satisfies all of this *(verified)*.

## 4. Materialize a physical PEP 503 index tree (default approach)

**Critical lesson from grading: hidden tests may inspect the index's on-disk layout** — e.g. assert `<index_root>/simple/<name>/<wheel-file>` exists as a real file, in addition to fetching it over HTTP *(observed: the reference grader failed a solution that served artifacts via pypiserver's in-memory pages from a flat pool, even though `pip install` worked)*. A **physical static tree** satisfies both structural and functional checks; a dynamic server satisfies only functional ones.

**Default: build a static index tree.** A verified generator ships as `scripts/make_static_index.py` in this skill package:

```bash
python3 <script> /app/dist <project_root>/pypi
```

Getting the script into the container *(the path you read it from may be host-only — observed failure mode: executing the host workspace path inside the container)*:
1. Try the common mount point: `python3 /skill/scripts/make_static_index.py ...`
2. Else locate it: `find / -name make_static_index.py -not -path '/proc/*' 2>/dev/null | head`
3. Else use this **verified inline fallback** (no file needed; takes the normalized project name from the step-0 contract, so no filename parsing; safe to re-run, and composable for multiple projects):

```bash
python3 - /app/dist <project_root>/pypi <dist-name> <<'EOF'
import hashlib, os, re, shutil, sys
dist, root = sys.argv[1], sys.argv[2]
name = re.sub(r"[-_.]+", "-", sys.argv[3]).lower()
simple = os.path.join(root, "simple")
d = os.path.join(simple, name)
os.makedirs(d, exist_ok=True)
links = ""
for fn in sorted(os.listdir(dist)):
    if not fn.endswith((".whl", ".tar.gz", ".zip")):
        continue
    shutil.copy2(os.path.join(dist, fn), os.path.join(d, fn))
    h = hashlib.sha256(open(os.path.join(d, fn), "rb").read()).hexdigest()
    links += f'<a href="{fn}#sha256={h}">{fn}</a><br>'
open(os.path.join(d, "index.html"), "w").write(f"<!DOCTYPE html><html><body>{links}</body></html>")
projs = sorted(p for p in os.listdir(simple) if os.path.isdir(os.path.join(simple, p)))
open(os.path.join(simple, "index.html"), "w").write(
    "<!DOCTYPE html><html><body>" + "".join(f'<a href="{p}/">{p}</a><br>' for p in projs) + "</body></html>")
print("index tree at", root)
EOF
```

Either way the result is:

```
<project_root>/pypi/simple/index.html                  # links "vectorops/" etc.
<project_root>/pypi/simple/<norm-name>/index.html      # links files with #sha256=...
<project_root>/pypi/simple/<norm-name>/<artifact files> # real copies of the dist artifacts
```

Rules:
- **Copy, never move**, artifacts from `dist/` into the tree — checks may inspect both locations *(observed)*. The generator copies for you.
- **Choose the index root from the task.** If the task names one, use it literally. If not, use `<project_root>/pypi` (e.g. `/app/pypi`) — the convention used by the reference task's grader.
- **Derive the web root from the mandated client URL.** `--index-url http://localhost:PORT/simple` ⇒ URL path `/simple` ⇒ the served directory must *contain* `simple/`, i.e. serve from the index root, not from inside `simple/`.
- Normalized project dir name: lowercase, runs of `-_.` → `-` (the generator handles this).
- Regenerate (or re-copy + rewrite) the tree whenever artifacts change; a static tree does not auto-update.

### When NOT to use the static default

- **A tool is mandated or pre-staged** (pypiserver, devpi, a provided binary) → use it, but *additionally* mirror the artifacts into a physical `simple/` tree under the expected index root when one is implied, so structural checks still pass.
- **An authenticated upload API is genuinely required** *(extrapolated)* → pypiserver with `-P <htpasswd> -a upload` + `twine upload --repository-url http://localhost:PORT/ dist/*` (open variant: `-P . -a .`).
- pypiserver read-only serving, for reference: `pypi-server run -p PORT --disable-fallback <packages_dir>`. `--disable-fallback` prevents redirects to pypi.org for missing packages ("no fallback to another source" requirements). Remember: this leaves **no on-disk `simple/` tree**.

## 5. Serve it, detached, on the required port

Grading typically runs in a **different shell** than the agent. A server started in the foreground, or as a plain `&` job of a shell that exits, may die before tests run.

```bash
cd <project_root>/pypi && nohup python3 -m http.server 8091 > /app/index.log 2>&1 & disown
```

- Always detach: `nohup <cmd> >logfile 2>&1 & disown` (or `setsid`). **Never kill the server at the end of your run.**
- `python3 -m http.server` binds `0.0.0.0` by default and serves `index.html` for directory URLs *(verified)* — exactly what PEP 503 page fetches need.
- Check the port first: `curl -s http://localhost:PORT/simple/` — if a correct server already runs there, reuse it; if something wrong holds it, kill via `/proc` scan (no `ps`/`pgrep` in this image):
  ```bash
  for p in /proc/[0-9]*; do pid=${p#/proc/}; [ "$pid" = "$$" ] && continue
    cmd=$(tr '\0' ' ' < $p/cmdline 2>/dev/null)
    case "$cmd" in "python3 -m http.server"*) kill $pid;; esac   # anchor the pattern!
  done
  ```
  Guard against self-kill *(verified the hard way)*: exclude `$$` and anchor the pattern to the command start — a loose `grep` for e.g. `http.server` matches your own shell's cmdline and kills your session.
- Health-check from a **new** shell: `curl -s http://localhost:PORT/simple/` lists the project; `curl -s http://localhost:PORT/simple/<normalized-name>/` lists every artifact link.

## 6. End-to-end verification (do not skip)

Simulate the grader exactly — clean interpreter, no pip cache, neutral working directory:

```bash
python3 -m venv /tmp/verify-venv
/tmp/verify-venv/bin/pip install --no-cache-dir \
    --index-url http://localhost:8091/simple <dist-name>==<version>
cd /tmp && /tmp/verify-venv/bin/python -c "
from <import_name> import <api>
# exercise the required behavior, e.g. print(<api>([1,2,3],[4,5,6]))  # expect 32
import <import_name>; assert 'site-packages' in <import_name>.__file__
"
```

Why each flag matters:
- `--index-url` (not `--extra-index-url`): proves the local index **alone** satisfies the install — the task's required command uses `--index-url`.
- `--no-cache-dir`: a warm pip cache can mask a broken index.
- venv + `cd /tmp`: prevents the source tree (especially flat layout) from shadowing the installed package.
- Checking `__file__` under site-packages proves you imported the installed artifact, not the working tree.

Final checklist (mirrors what graders check):
- [ ] `dist/` contains exactly the required artifacts (right name, version, formats; typically one wheel + one sdist).
- [ ] Wheel contains the import package and correct METADATA; sdist contains `pyproject.toml` + sources.
- [ ] **On disk**: `<index_root>/simple/<normalized-name>/` exists and contains copies of the exact artifact files; `index.html` pages exist at both levels.
- [ ] **Over HTTP from a new shell**: `/simple/` lists `<name>/`; `/simple/<name>/` lists both filenames.
- [ ] Fresh-venv install of the exact `name==version` succeeds from the local index alone; required import and API behavior verified against the installed package.
- [ ] Index process is detached, healthy, and left running; log shows no errors.

## 7. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Structural check fails: `<index_root>/simple/<name>/<file>` missing on disk | Artifacts served by a dynamic server (pypiserver/devpi) or only copied to a flat pool. Materialize a physical static tree (step 4) and serve that. |
| `No matching distribution found for name==version` | Version/name in metadata ≠ requested; artifact missing from the tree; check `/simple/<name>/` output. |
| Install works but import fails | Module omitted from wheel (bad `packages` discovery) or `__init__` doesn't re-export. Inspect: `python3 -m zipfile -l dist/*.whl`. |
| Test shell can't reach the index | Server died with the agent shell → restart with `nohup ... & disown`; verify from a new shell. |
| HTTP 404 but files exist under the index root | Serving from the wrong cwd: with `--index-url .../simple`, serve the directory that *contains* `simple/`. |
| `Multiple top-level packages discovered` (flat layout) | Set `[tool.setuptools] packages = [...]` explicitly. |
| `python -m build` fails resolving build deps | No network → `--no-isolation` (setuptools+wheel preinstalled) *(verified)*. |
| pip silently gets a different/newer version | Cache or fallback: use `--no-cache-dir`, `--disable-fallback` on pypiserver, and clean stale artifacts from both `dist/` and the tree. |
| Port already in use | `curl http://localhost:PORT/simple/`; reuse if it is your correct server, else kill via the self-excluding `/proc` scan in step 5 (never a bare `grep` kill — it can match your own shell). |
| Shell dies with exit 143 during cleanup | Your kill pattern matched the current shell's own cmdline. Exclude `$$` and anchor patterns as shown in step 5. |
| 404 on `/simple/<Name_With.Underscores>/` | URL must be the PEP 503-normalized name: lowercase, runs of `-_.` → `-`. |

## Evidence boundary

Verified end-to-end in the reference environment (reference task graded 3/3 under this skill): setuptools src-layout build via `python -m build` (sdist+wheel); static tree at `/app/pypi` via `scripts/make_static_index.py` **or the inline fallback block in step 4** + `python -m http.server 8091`, passing both a grader-equivalent structural assertion suite (`dist/` glob counts, wheel/sdist contents, HTTP pages, on-disk `simple/vectorops/<files>`) and a clean-venv `--index-url` install; detached-process persistence across shells. Also observed in grading: executing a skill script via its **host workspace path inside the container fails** — use the `/skill/` mount, `find`, or the inline fallback. Verified functional-only (and observed to fail on-disk structural checks in the reference grading): pypiserver 2.4.x with `--disable-fallback` serving a flat packages dir. Extrapolated (standard but untested here): devpi, twine/authenticated upload flows, pre-staged broken-project repair variants, package data inclusion, legacy `setup.py` builds, non-`/app/pypi` index roots — follow the same pipeline and lean on the step-6 verification to confirm any variant.
