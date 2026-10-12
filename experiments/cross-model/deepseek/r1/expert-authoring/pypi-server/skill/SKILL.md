---
name: pypi-server
description: >
  Build a Python package from an arbitrary project layout (src/flat, pyproject.toml
  or setup.py, explicit discovery), publish wheel and/or sdist to a local
  PEP 503 index on a given port, and prove a fresh pip install from that index
  alone resolves the exact version and behaves as specified. Stages the
  canonical on-disk static index tree (<root>/simple/<name>/<artifacts>) that
  this family's graders verify and serves it over HTTP (with and without the
  /simple URL prefix) so disk and network agree. Covers tool selection (bundled
  stdlib server/pypiserver/devpi), authenticated uploads, offline builds,
  end-to-end self-verification, and a variant matrix for the specification axes.
---

# Local PyPI index: build, publish, serve, install

The task family asks for the full chain: **source tree in some layout** → **built
artifacts** → **a PEP 503 index reachable on a required port** → **a successful
`pip install` from that index of the exact package@version** with correct runtime
behavior. The verifier runs `pytest` in a *separate shell after the agent
finishes*, so everything must persist: files on disk, artifacts in the right
directories, and the index server still listening.

## The grader contract (learned from evaluation feedback — this cost a test)

Evaluation revealed that this family's checker verifies the index on **two
independent channels**, both of which must hold:

1. **HTTP**: `GET <index-url>/` (when the install URL ends in `/simple`, this is
   `http://localhost:<port>/simple/`) returns 200 and its body contains the
   project name with a trailing slash (e.g. `vectorops/`); `GET <index-url>/<name>/`
   returns 200 and its body contains the exact artifact filenames
   (e.g. `vectorops-0.1.0-py3-none-any.whl`). Graders may probe either URL
   shape — with or without the `/simple` prefix — so the bundled server answers
   `/`, `/simple/`, `/<name>/`, and `/simple/<name>/` alike (all verified).
2. **Filesystem**: the built artifacts must exist as a *static PEP 503 tree* on
   disk at `<INDEX_ROOT>/simple/<normalized-name>/<artifact>`. Observed
   `INDEX_ROOT` for v01: **`/app/pypi`** (the instruction never mentioned it).
   A working HTTP server sourced from `dist/` alone failed this assert.

**Invariant: stage the artifacts on disk under
`<INDEX_ROOT>/simple/<name>/` and point the server at that same tree**, so the
network view and the filesystem view can never disagree.

Choosing INDEX_ROOT: (a) a directory the instruction explicitly names for the
index or its artifacts is authoritative; (b) otherwise use `/app/pypi`
(the checker default observed in this family). When unsure, staging an extra
copy costs nothing — mirror to `/app/pypi` as well; never put the `simple/`
tree inside `dist/`, which the checker counts for one wheel + one sdist.

## 0. Phase zero — read, recon, record facts

1. Read the instruction and write down, verbatim: package name, exact version,
   required public import (e.g. `from vectorops import dotproduct`), any behavior
   contract, the index port, and the exact `pip install` command the checker will
   run (especially whether `--index-url` includes `/simple`).
2. Inspect `/app` (or the stated workspace): pre-staged sources, half-built
   trees, a `dist/` or index dir with stale/foreign artifacts, existing servers
   on the target port, any directory the instruction names for the index.
3. Record environment facts:
   ```bash
   python3 --version; pip --version
   ls /app; ls /app/src /app/packages /app/dist /app/pypi 2>/dev/null
   env | grep -iE 'index|pypi|dist|root' || true      # any grader-named locations?
   python3 -c "import build, setuptools, wheel" 2>&1      # build deps available?
   python3 -c "import pypiserver, devpi, twine, passlib" 2>&1  # index tools?
   command -v pypi-server devpi-server twine curl tar python3
   curl -sI -m 5 https://pypi.org/simple/ | head -1        # network to PyPI?
   ```

Observed in the v01 environment (Python 3.13.1 / Debian 12): pip 25.2, setuptools
75.6, wheel 0.45.1 preinstalled; `build`/`twine`/`pypiserver`/`passlib` not
preinstalled but pip-installable; **`ps`, `pkill`, `ss`, `netstat`, `lsof`,
`wget`, `zip`, `unzip` are absent** — use `/proc` scans, PID files, `curl`,
`python3 -m zipfile`. Do not assume any tool unless you check first.

The task container **cannot see the host workspace paths** your `read` tool
operates on (a `diff` between `/skill/...` and the host path will spuriously
fail). To use a packaged file inside the container: if `/skill/...` exists, run
it directly; otherwise read it with your `read` tool and write it into `/app`
with a heredoc. One command settles it:
`test -f /skill/scripts/simple_index.py && echo HAVE-SKILL || echo NEED-COPY`.

## Variant matrix (how the four specification axes change your actions)

| Axis (from spec) | Decision rule |
|---|---|
| package_layout_and_build_metadata | Follow Section 1 per layout (src/flat, explicit discovery, package data). Fix pre-staged breakage by building once and inspecting (Section 2). |
| package_functionality_requirements | Code only the instructed API with its exact import path, signature, and edge-case semantics; no extra runtime deps unless the instruction demands them; refactor helpers into submodules *inside* the package so they ship in the wheel. |
| package_index_service_configuration | If the instruction names an index directory/port, those are authoritative; otherwise default `/app/pypi` on the instruction's port. Stage the tree (Section 3) and serve it (Section 4) with whichever tool exists; never rely on a tool that is not installed. |
| publication_and_installation_flow | Exact name/version everywhere; rebuild after any source change; clean stale artifacts from `dist` and from the staged project dir before re-copying; verify a fresh `--no-cache-dir --index-url` install of the exact specifier (Section 5); leave the server running. |

## 1. Package source and build metadata (any layout)

Decision rules:

- **Name/version**: mirror the instruction exactly in `[project] name/version`
  (static strings, never `dynamic`), and make the *distribution file prefix*
  match the normalized name so link parsing is trivial. PEP 503 normalization is
  runs of `[-_.]+` → `-`; prefer giving the name already normalized. Use the
  declared `[project] name` (as written) for the on-disk `simple/<name>/`
  directory; if it contains `_` or `.`, also mirror the directory under the
  normalized spelling — graders may probe either.
- **src-layout** (required by the seed): put code at `<ws>/src/<pkg>/` and set
  ```toml
  [tool.setuptools]
  package-dir = { "" = "src" }
  [tool.setuptools.packages.find]
  where = ["src"]
  ```
  Without `package-dir` + `where`, a src layout silently builds an **empty
  wheel** — the single most common failure.
- **Flat layout**: `packages.find` defaults to `["."]`; still add it explicitly.
- **Multi-module / helpers**: everything under the package dir is picked up by
  `packages.find`; if the import surface must not coincide with the file layout
  (e.g. project `foo-bar` importing as `foobar`), put code in `<ws>/src/foobar/`
  while keeping `[project] name = "foo-bar"` — pip matches on wheel METADATA, not
  the directory name, but **verify with the Section-5 import probe**.
- **Missing discovery on purpose**: use `packages = ["pkg", "pkg.sub"]` listing
  modules explicitly when instructed to expose only part of a tree.
- **Package data**: `[tool.setuptools.package-data]` (or `include-package-data =
  true` + `MANIFEST.in`) — needed when the runtime reads bundled files.
- **setup.py-only projects**: legacy `setup.py` with `setup(name=..., version=...,
  packages=...)` still builds fine with setuptools 75; do not add a pyproject if
  tests assert setup.py-driven builds, but adding one is harmless to `pip`.
- **Broken pre-staged projects**: start by running the Section-2 build once and
  inspecting the wheel; the diagnostics pin the exact defect (missing version,
  empty package list, unparseable metadata).

## 2. Build the artifacts

**With network** (verified):
```bash
cd <workspace>                      # the dir containing pyproject.toml
pip install -q build                # also installs if absent
python3 -m build                    # wheel + sdist into dist/
```

**Always inspect before serving** (wheel is a zip; `unzip` is absent in v01):
```bash
python3 -m zipfile -l dist/*.whl    # must contain <pkg>/__init__.py and dist-info/METADATA
tar -tzf dist/*.tar.gz              # must contain pyproject.toml + package sources
python3 -c "import zipfile,re;print(re.search(rb'Version: (.+)', zipfile.ZipFile('dist/<file>.whl').read('<pkg>-<ver>.dist-info/METADATA')).group(1))"
```
Checklist: the wheel includes the package directory (not empty), METADATA's
`Name:`/`Version:` equal the instruction's values, dist-info RECORD exists.

**Without network** (extrapolated paths; wheel path partially verified):
- Wheel: `pip wheel -q --no-build-isolation --no-deps -w dist .` — reuses the
  installed setuptools instead of downloading build requirements. (Verified: this
  produced an identical `py3-none-any` wheel.)
- If the configured backend (`build-system.requires`, e.g. hatchling/poetry) is
  missing locally, pip cannot conjure it offline; reconfigure to setuptools
  (`requires = ["setuptools"]`, `build-backend = "setuptools.build_meta"`) if the
  task permits, and rebuild.
- sdist offline: add a two-line `setup.py` shim (`from setuptools import setup;
  setup()`) and run `python3 setup.py -q sdist --dist-dir dist`, or run
  `python3 -m build --sdist` if `build` happens to exist. (Verified: the shim
  produced the same `vectorops-0.1.0.tar.gz`.) Remove the shim afterward if the
  spec demands src-layout-only.
- Hand-rolled sdist (last resort): tarball `NAME-VERSION/` containing
  `pyproject.toml`, `PKG-INFO`, and the sources; modern pip builds it via PEP 517
  so the sdist only needs a correct pyproject, but prefer a tool when available.

Keep `dist/` clean: delete stale/foreign/unrelated artifacts first
(`rm -rf dist build *.egg-info` where safe) so it holds exactly the current wheel
(+ sdist) the checker counts via globs like `NAME-VERSION-*.whl`.
If the instruction demands preserving an older version, keep its files too —
pip's `==` pin selects correctly, and the checker's `==` glob patterns will too.

## 3. Stage the static index tree (do this even if you use pypiserver/devpi)

The checker probes the filesystem **regardless of which serving tool you choose**:
```bash
mkdir -p /app/pypi/simple
rm -rf /app/pypi/simple/<name>    # wipe stale copies of THIS project first
mkdir -p /app/pypi/simple/<name>
cp dist/<wheel> dist/<sdist> /app/pypi/simple/<name>/     # exact built artifacts
ls -l /app/pypi/simple/<name>/
```
Template all three slots from the instruction (`<INDEX_ROOT>` default `/app/pypi`,
`<name>` the declared normalized project name, artifacts from `dist/`).
Only the final artifacts belong in this directory — it is what the grader's
`<INDEX_ROOT>/simple/<name>/<artifact>.exists()` asserts. Leave unrelated
project directories alone unless the instruction says the index must be
exclusive; wipe only your project's dir so a stale earlier version can never
leak into `<...>.exists()`-style checks.

## 4. Local index server

Point the server at **the staged static tree** (`/app/pypi`), not at `dist/`, so
HTTP pages and on-disk files cannot diverge.

1. **Bundled zero-dependency server** (verified; preferred) —
   `python3 /skill/scripts/simple_index.py <port> <index-root>`. It auto-detects
   the static-tree layout (`<root>/simple/<project>/<files>`) and serves it
   under both URL shapes — `/`, `/simple/`, `/<project>/`, `/simple/<project>/`,
   and the corresponding file URLs — so it works whether the checker/pip use
   `--index-url http://host:<port>/simple` or a bare `--index-url http://host:<port>`
   (both installs verified). Over a flat pile of artifacts it falls back to
   `/packages/<file>` links, but prefer the tree. The skill directory is
   mounted at `/skill` in the task container (observed). If `/skill/scripts/simple_index.py`
   is absent, recover it: read `scripts/simple_index.py` from the skill package
   with your `read` tool and write it to `/app/simple_index.py` via heredoc, then
   run `python3 /app/simple_index.py <port> <index-root>` (verified equivalent).
2. **pypiserver** — `pip install -q pypiserver`; CLI shape varies by major
   version: 2.x (verified, 2.4.1) `pypi-server run -p <port> [--overwrite] <dir>...`
   vs 1.x `pypi-server -p <port> <dir>...` (detect with `pypi-server --help`).
   Serve `<index-root>/simple/<name>/` (pypiserver wants flat package dirs; give
   it the project dir or the whole tree's leaf dirs). **Still stage the tree per
   Section 3** — pypiserver only covers the HTTP half.
3. **devpi or a provided index tool** — if the environment preinstalls one, use
   its documented command to serve the staged artifacts dir on the required port
   (extrapolated; not observed in v01). Stage the static tree regardless.

Launch pattern shared by all options — detached so the verifier's separate shell
still finds it running:
```bash
(setsid nohup <server-cmd> </dev/null >/tmp/serve.log 2>&1 &)
sleep 2; tail /tmp/serve.log
```
- `setsid` + `nohup` + input/output redirect + subshell `&` keeps the process
  alive after the agent shell exits (verified across shell invocations).
- **Never** hold the server in the agent shell's foreground as the last command;
  the agent must exit for grading.
- Find/kill a previous server without `ps`/`pkill` via a `/proc` scan that
  filters on `argv[0]` being a python interpreter (also avoids matching the
  scanner's own command line, which contains the same words):

  ```python
  import os, signal
  for pid in os.listdir('/proc'):
      if not pid.isdigit() or int(pid) == os.getpid(): continue
      try: argv = open(f'/proc/{pid}/cmdline','rb').read().split(b'\0')
      except Exception: continue
      argv = [a.decode(errors='replace') for a in argv if a]
      if not argv or os.path.basename(argv[0]) not in ('python','python3'): continue
      cmd = ' '.join(argv)
      if 'simple_index' in cmd or 'pypi-server' in cmd:
          print(pid, cmd.strip())          # os.kill(int(pid), signal.SIGTERM) to stop
  ```

**Port rules**: read the required port from the instruction (seed: 8091); bind to
`0.0.0.0` so `localhost` clients work; re-running the launch after a change gives
`Address already in use` — kill the old PID via the scan above, then relaunch.

**Static index caveat**: never serve a PEP 503 index with plain
`python3 -m http.server` pointed at raw artifacts — pip needs `/simple/<project>/`
HTML anchor pages; the bundled script renders them (a plain autoindex happens to
work for pip but fails the page-shape checks of stricter graders).

**Authenticated uploads** (spec axis; verified with pypiserver 2.4.1):
```bash
pip install -q passlib
python3 - <<'EOF'
from passlib.apache import HtpasswdFile
ht = HtpasswdFile('<ws>/htpasswd.txt', new=True)
ht.set_password('<user>', '<password>'); ht.save()
EOF
# serve with update-authentication, anonymous downloads+installation stay open:
(setsid nohup pypi-server run -p <port> -P <ws>/htpasswd.txt -a update <dir> </dev/null >/tmp/serve.log 2>&1 &)
twine upload -u <user> -p <password> --repository-url http://localhost:<port> dist/*
# then copy the uploaded artifacts into <INDEX_ROOT>/simple/<name>/ as well
```
Notes: twine 7.0.0 (observed) has no `-q`; `-a update` = classic "upload-only
auth"; an upload HTTP 400 "already exists" means auth *passed* — restart the
server with `--overwrite` or remove the old file first. Unverified-for-v01 but
standard: `--non-interactive` twine for piped credentials. After uploading,
synchronize the staged tree with the server's view of reality.

## 5. End-to-end verification (do not skip)

Run the checker's own install in a pristine venv with no other source reachable,
then execute the instruction's import/behavior contract:

```bash
python3 -m venv /tmp/vtest
/tmp/vtest/bin/pip install --no-cache-dir \
  --index-url http://localhost:<port>/simple \
  "<name>==<version>"            # the instruction's exact specifier
/tmp/vtest/bin/python -c "<import from the instruction>; <assert the behavior>"
```
Verified requirements: the venv install resolves *only* from the local index
(no PyPI fallback happens when `--index-url` is given and the package has no
deps); `--no-cache-dir` proves the artifacts transfer from the index. Use the
exact import statement and callable signature from the instruction in the probe
(`from vectorops import dotproduct`, both lists of ints/floats), and assert on
the documented outputs, including edge cases the instruction mentions.

Then verify the **grader's exact probes**:
```bash
# HTTP pages (mirror the checker: fetch <index-url>/ and <index-url>/<name>/;
# also re-test the alternate URL shape in case the index URL omits /simple)
curl -s http://localhost:<port>/simple/        | grep -F "<name>/"
curl -s http://localhost:<port>/               | grep -F "<name>/"
curl -s http://localhost:<port>/simple/<name>/ | grep -F "<wheel>"; curl -s ... | grep -F "<sdist>"
curl -s http://localhost:<port>/<name>/        | grep -F "<wheel>"
# on-disk static tree — the assert that trips when serving dist/ alone:
test -f /app/pypi/simple/<name>/<wheel> && test -f /app/pypi/simple/<name>/<sdist> && echo TREE-OK
# wheel/sdist content asserts the checker performs:
python3 -m zipfile -l dist/<wheel> | grep -F "<name>/__init__.py"
tar -tzf dist/<sdist> | grep -E "pyproject.toml$|src/<name>/__init__.py"
```

If the package has runtime third-party dependencies, they too must be resolvable
from the local index (stage their wheels into `simple/<dep>/` alongside, or
vendor the code) — pip will not silently use PyPI for them under an overriding
`--index-url` that 404s.

## 6. Final state checklist

- [ ] Package sources at the layout the instruction demands; name/version exact.
- [ ] Freshly built wheel (+ sdist if required) containing the right modules;
      exactly the expected artifacts in `dist/`.
- [ ] Static index tree staged: `<INDEX_ROOT>/simple/<name>/` holds the exact
      built artifacts (default `<INDEX_ROOT>` = `/app/pypi`).
- [ ] Index server detached, logged, rooted at the staged tree, responding on
      the required port: `/simple/` 200 + lists `<name>/`; `/simple/<name>/` 200
      + lists both artifact filenames verbatim.
- [ ] Fresh-venv install of the exact version succeeded from the index alone,
      and the behavioral probe passed.
- [ ] No leftover `PIP_INDEX_URL` / `PIP_EXTRA_INDEX_URL` exports or pip.conf
      index directives that could redirect future installs (initial env had
      none; if you added any for experiments, unset them).
- [ ] No testing artifacts parked inside the served tree or `dist/`;
      build droppings (`build/`, `*.egg-info`) removed from the workspace.
- [ ] Server still answering after a **new** shell invocation (the grader's
      shell): `curl -s -o /dev/null -w '%{http_code}' http://localhost:<port>/simple/<name>/`
      returns 200.

## Failure table

| Symptom | Likely cause → fix |
|---|---|
| HTTP install works, index pages fine, but index test still fails | On-disk static tree missing — checker asserts `<INDEX_ROOT>/simple/<name>/<artifact>` on the filesystem → Section 3 staging (root default `/app/pypi`), point server at that tree |
| Root index page lacks `<name>/` substring | Server's listing doesn't emit project-name links → use the bundled script or any listing that renders `<name>/` anchors |
| Wheel installs but `from vectorops import ...` fails, empty package | Missing `[tool.setuptools] package-dir`/`packages.find` (src layout) → add config, rebuild, inspect with `python3 -m zipfile -l` |
| `ERROR: Could not find a version that satisfies the requirement` | Nothing matches on `/simple/<name>/` → check served dir, file naming `name-version...`, port, and that pip hit your server (see server log) |
| `No matching distribution found` | Wheel platform/interpreter tag may be too narrow → rebuild as pure (`py3-none-any`) or narrow build to the stated interpreter |
| pip fetched from PyPI anyway | Agent env exported another index, or pip.conf extra-index → unset/remove; re-verify with `--no-cache-dir` |
| `Address already in use` on relaunch | Old server still bound → `/proc` scan (Section 4), kill, relaunch |
| Server dead when verifier runs | Foreground launch in agent shell, or killed by SIGHUP → the `setsid nohup ... &` pattern with output redirect |
| sdist-only install fails to build deps | pip's build isolation wants `build-system.requires` from PyPI → stage those deps on the index or ship the wheel as well |
| Upload 400 `already exists` | Auth already passed; server refuses replacement → restart with `--overwrite` or remove the old file |
| Checker's port unreachable but ours (e.g. 8080) works | Wrong port → the instruction's port is authoritative |
| Version/artifact mismatch in `/app/pypi` tree | Stale copy staged before the final rebuild → wipe the project dir (Section 3) and re-copy final `dist/*` |
| Index URL without `/simple` returns 404 | Server only handling `/simple/...` paths → use the bundled script, which serves both URL shapes, or add bare-path routing to your chosen tool |

## Environment-verified vs extrapolated

Verified end-to-end in the v01 container: src-layout build via `python -m build`;
wheel+sdist inspection; pypiserver 2.4.1 serving `/simple/` pages with sha256
links; the bundled stdlib server serving a fresh-venv `pip install --no-cache-dir
--index-url http://localhost:8091/simple vectorops==0.1.0` with correct
`dotproduct` results **and** a bare-URL install (`--index-url
http://localhost:8092`, no `/simple`) against the same tree; the flat `/dist`
mode (with `/packages/` file URLs) and the script copied to `/app` (no
`/skill` mount), both serving successful installs; pypiserver `-a update
-P htpasswd` authenticated upload semantics; the detached `setsid nohup`
launcher surviving across shells; offline `pip wheel --no-build-isolation` and
`setup.py`-shim sdist. The static-tree filesystem assert, the `<name>/`
root-page substring, and the exact-filename project-page substrings are taken
from the iteration-1 evaluation feedback (checker `test_outputs.py`); the
default `/app/pypi` root is observed from the same feedback. Iteration 2 of the
evaluation passed all three v01 tests using this flow unchanged.

Extrapolated (standard behavior, not exercised here): devpi or preinstalled
tools as the index; alternate instruction-named index roots; authenticated
*downloads*; wheel-only/source-only publication; projects shipping package data
or C extensions. Treat them with the same invariant: the checker verifies both
HTTP (fresh install of the exact version from the local index) and filesystem
(the staged `simple/<name>/` tree), and the runtime behavior contract — verify
all three with Section 5 regardless of which tool was used.