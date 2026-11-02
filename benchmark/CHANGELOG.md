# Benchmark release changes

## 2026-11-02

- Fix `pypi-server/v15/run-tests.sh`: use a quoted, neutral temporary-venv
  path and update its contract in `scorer-manifest.json`. A replacement during data
  sanitization for release had introduced an unquoted space, causing the
  runner to exit before pytest started. The task, reference solution, and
  three test assertions are unchanged. Reported in
  [issue #1](https://github.com/NJU-LINK/Socratic-Skill-Learning/issues/1).
- Replace invalid sanitized Docker image/container fallback names in 12
  `docker-compose.yaml` files with lowercase `stb-` names, and use matching
  neutral log-directory defaults. Explicit `T_BENCH_*` overrides are retained.
  The SSL harness does not use these Compose files.

`source-manifest.json` is the frozen benchmark-preparation record. Its
`localSha256` values describe files at preparation time, before release data
sanitization and subsequent fixes; they are not checksums of today's
packaged files. `scorer-manifest.json` binds the current test runners used
by the harness. Published experiment records and paper-scope membership
are not rewritten by these release fixes.
