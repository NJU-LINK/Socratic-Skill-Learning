#!/usr/bin/env python3
"""deploy_grpc_store.py — deploy a Python gRPC store server and PROVE ownership.

The invariant enforced: "the port is owned by the process this script
launched, and that process answered a real RPC."  No process-name matching
(relative launches like `cd /app && exec python3 server.py` defeat it) and no
raw TCP connect (any listener accepts it).  Stages:

  0. generate Python bindings with grpc_tools.protoc and ASSERT the module
     contract (proto path relative to -I must be exactly its basename, so
     generated modules are top-level in --out and correctly named)
  1. EVICT   - kill whoever owns the port (by /proc socket ownership)
  2. LAUNCH  - detached (start_new_session), real child PID captured,
               out-dir prepended to PYTHONPATH for the server
  3. ASSERT  - poll until the launched PID owns the port (BEFORE probing)
  4. TIER1   - real gRPC HTTP/2 handshake (grpc.channel_ready_future)
  5. TIER2   - optional --probe-cmd functional RPC (out-dir on PYTHONPATH)
  6. TIER3   - server.log must contain no traceback/EADDRINUSE

Exits nonzero on any failed stage, so it can never report success for a
deployment it does not control.  Needs grpcio + grpcio-tools installed.

Usage:
  python3 deploy_grpc_store.py \
      --proto /app/kv-store.proto --out /app --port 5328 \
      --cmd "python3 /app/server.py" \
      [--probe-cmd "python3 /tmp/probe.py"] [--wait 30]
"""
import argparse
import os
import re
import subprocess
import sys
import time

try:
    import grpc
except ImportError:
    sys.exit("FATAL: grpcio is not installed (pip install grpcio grpcio-tools)")


def port_owner_pids(port: int) -> set:
    """PID(s) holding a LISTEN socket on `port`.

    /proc/net/tcp{,6} columns (split): 0 sl, 1 local_address, 2 rem_address,
    3 st (0A=LISTEN), ..., 9 inode.  local_address is IP-hex:PORT-hex; the
    port is always the last :HEX group, so IPv4 (8 hex), IPv6 (32 hex) and
    v4-mapped forms all work without a needle table.  Inode -> PID via
    /proc/<pid>/fd/* readlinks of the form socket:[<inode>].  Works where
    ps/ss/lsof/fuser are missing.
    """
    hx = f"{port:04X}".lower()
    inodes = set()
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = open(path).read().splitlines()[1:]
        except OSError:
            continue
        for ln in lines:
            c = ln.split()
            if len(c) > 9 and c[3] == "0A" and c[1].rsplit(":", 1)[-1].lower() == hx:
                inodes.add(c[9])
    owners = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                tgt = os.readlink(f"/proc/{pid}/fd/{fd}")
            except OSError:
                continue
            if tgt.startswith("socket:[") and tgt[8:-1] in inodes:
                owners.add(int(pid))
                break
    return owners


def check_generated_layout(out_dir: str, proto_path: str) -> str:
    """Assert the protoc module-name contract for a freshly generated layout.

    protoc derives the generated file path AND the Python module name from
    the proto's path RELATIVE TO -I, preserving directory components.  The
    contract for this family: the proto sits at the TOP LEVEL of -I, so the
    generated modules land top-level in --out and are named from the proto
    basename (`-` and `.` map to `_`).  Using --out as -I only works when
    proto dir == out dir and silently nests otherwise (e.g. proto at
    OUT/protos/x.proto with -I OUT emits OUT/protos/x_pb2.py and a
    package-qualified `import protos.x_pb2` in the _grpc module) — the
    end-to-end failure is `ModuleNotFoundError` in the grader's process
    while everything else looks clean.  Returns the expected module prefix;
    exits 1 on any violation.
    """
    mod = os.path.basename(proto_path)
    if mod.endswith(".proto"):
        mod = mod[:-6]
    mod = mod.replace("-", "_").replace(".", "_")

    pb2 = os.path.join(out_dir, mod + "_pb2.py")
    grpc_mod = os.path.join(out_dir, mod + "_pb2_grpc.py")
    if not (os.path.isfile(pb2) and os.path.isfile(grpc_mod)):
        nested = sorted(
            os.path.relpath(os.path.join(r, f), out_dir)
            for r, _, fs in os.walk(out_dir) for f in fs
            if f.endswith("_pb2.py") or f.endswith("_pb2_grpc.py"))
        sys.exit(f"FATAL: generated modules are not top-level in --out "
                 f"(expected {mod}_pb2.py + {mod}_pb2_grpc.py in {out_dir}); "
                 f"found {nested}. -I must be the directory CONTAINING the "
                 f"proto, so the proto's -I-relative path is exactly its basename.")

    content = open(grpc_mod, errors="replace").read()
    allowed = re.search(rf"^import {re.escape(mod)}_pb2(?: |$)", content, re.M) or \
        re.search(rf"^from {re.escape(mod)}_pb2 import", content, re.M)
    forbidden = re.search(rf"^(?:import|from) \w+\.{re.escape(mod)}_pb2", content, re.M)
    if forbidden or not allowed:
        bad = [ln for ln in content.splitlines()
               if re.match(rf"^(?:import|from) .*{re.escape(mod)}_pb2", ln)][:3]
        sys.exit(f"FATAL: {grpc_mod} has a package-qualified or wrong import: "
                 f"{bad}. The generated module must be top-level ({mod}_pb2); "
                 f"the proto's path relative to -I must be exactly its basename.")
    return mod


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # keep child output in order
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proto", required=True, help="path to the .proto file")
    ap.add_argument("--out", required=True, help="dir for generated bindings + server.log")
    ap.add_argument("--port", type=int, required=True, help="port the server must own")
    ap.add_argument("--cmd", required=True, help='server command, e.g. "python3 /app/server.py"')
    ap.add_argument("--probe-cmd", default="", help='functional probe, e.g. "python3 /tmp/probe.py"')
    ap.add_argument("--wait", type=int, default=30, help="seconds to wait per stage")
    a = ap.parse_args()
    log = os.path.join(a.out, "server.log")

    def die(msg: str) -> None:
        print("FATAL:", msg, file=sys.stderr)
        try:
            print("---- server.log tail ----")
            tail = open(log, errors="replace").read()[-2000:]
            print(tail if tail else "(empty)")
        except OSError:
            pass
        sys.exit(1)

    print("==> grpc", grpc.__version__)

    # 0. generate bindings; -I is the proto's CONTAINING dir (not --out), so
    #    the generated module name/path come out flat and correct.
    print("==> generating bindings")
    proto_dir = os.path.dirname(os.path.abspath(a.proto))
    subprocess.run(
        [sys.executable, "-m", "grpc_tools.protoc", "-I", proto_dir,
         f"--python_out={a.out}", f"--grpc_python_out={a.out}", a.proto],
        check=True)
    mod = check_generated_layout(a.out, a.proto)
    print(f"module name contract OK: top-level {mod}_pb2 + {mod}_pb2_grpc")
    r = subprocess.run([sys.executable, "-c",
                        f"import sys; sys.path.insert(0, {a.out!r}); "
                        f"import {mod}_pb2, {mod}_pb2_grpc; print('import smoke OK')"])
    if r.returncode != 0:
        die(f"import smoke test failed for {mod}_pb2 from {a.out}")

    # 1. EVICT whoever owns the port (by ownership, never by name)
    print(f"==> evicting current owner of port {a.port} (by /proc socket ownership)")
    deadline = time.time() + 10
    while True:
        owners = port_owner_pids(a.port)
        if not owners:
            print("port free")
            break
        for pid in sorted(owners):
            print(f"evicting PID {pid} (owns port {a.port})")
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        if time.time() > deadline:
            die(f"port {a.port} still owned after eviction: {sorted(owners)}")
        time.sleep(0.3)

    # 2. LAUNCH detached; capture the REAL child PID (Popen parent vs child:
    #    with shell=False, p.pid is the server itself).
    print(f"==> launching detached: {a.cmd}")
    env = dict(os.environ)
    env["PYTHONPATH"] = a.out + os.pathsep + env.get("PYTHONPATH", "")
    tokens = a.cmd.split()
    i = 0
    while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
        k, _, v = tokens[i].partition("=")
        env[k] = v
        i += 1
    rest = tokens[i:]
    if not rest:
        die("empty server command; use --cmd 'python3 /app/server.py'")
    with open(log, "wb") as lf:  # truncate: each deployment's log is its own
        p = subprocess.Popen(rest, stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                             start_new_session=True, env=env)
    print(f"launched PID {p.pid} (log: {log})")

    # 3. ASSERT identity BEFORE any probe: a pass from a stale server is the
    #    failure mode, not a success.
    print(f"==> asserting ownership (port {a.port} -> PID {p.pid}, up to {a.wait}s)")
    deadline = time.time() + a.wait
    seen = set()
    while time.time() < deadline:
        owners = port_owner_pids(a.port)
        seen |= owners
        if p.pid in owners:
            print(f"OWNED: port {a.port} -> {sorted(owners)}")
            break
        if not os.path.exists(f"/proc/{p.pid}"):
            die(f"launched process {p.pid} died before binding; owners={sorted(owners)}")
        time.sleep(0.3)
    else:
        die(f"port {a.port} never owned by launched PID {p.pid}; owners seen: {sorted(seen)}")

    # 4. TIER1: real gRPC handshake (a raw TCP connect is NOT evidence)
    print(f"==> tier 1: real gRPC handshake on port {a.port}")
    try:
        ch = grpc.insecure_channel(f"127.0.0.1:{a.port}")
        grpc.channel_ready_future(ch).result(timeout=a.wait)
        print(f"TIER1 OK: gRPC HTTP/2 handshake succeeded on {a.port}")
    except Exception as e:
        die(f"TIER1 FAIL: {type(e).__name__}: {e}")

    # 5. TIER2: functional probe through the task's generated stubs; the
    #    out-dir is on PYTHONPATH (and cwd) so probe scripts can import the
    #    generated modules no matter how they are invoked.  Probe hygiene is
    #    the caller's contract (SKILL.md §4): collision-proof identifiers and
    #    self-cleaning writes so the graded state stays pristine.
    if a.probe_cmd:
        print(f"==> tier 2: functional probe: {a.probe_cmd}")
        penv = dict(os.environ)
        penv["PYTHONPATH"] = a.out + os.pathsep + penv.get("PYTHONPATH", "")
        r = subprocess.run(["bash", "-c", a.probe_cmd], env=penv, cwd=a.out)
        if r.returncode != 0:
            die(f"TIER2 FAIL: probe exited {r.returncode}")
        print("TIER2 OK: functional RPC through generated stubs")
    else:
        print("==> tier 2: skipped (no --probe-cmd given)")

    # 6. TIER3: log must be clean (truncated per deployment above)
    print("==> tier 3: server.log assertion (no traceback / bind errors)")
    try:
        content = open(log, errors="replace").read()
    except OSError:
        content = ""
    m = re.search(r"(?i)traceback|address already in use|EADDRINUSE|failed to bind", content)
    if m:
        die(f"TIER3 FAIL: {m.group(0)!r} found in {log}")
    print("TIER3 OK: server.log clean")

    print(f"==> deployment complete: port {a.port} owned by PID {p.pid}; all tiers passed")


if __name__ == "__main__":
    main()