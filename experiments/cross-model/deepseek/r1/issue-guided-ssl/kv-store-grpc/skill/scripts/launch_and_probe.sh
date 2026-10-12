#!/usr/bin/env bash
# launch_and_probe.sh — detach a gRPC server and prove it SERVES, not just listens.
#
# Usage: launch_and_probe.sh <server_py> <port> [ready_timeout_sec] [probe_rpc]
#   probe_rpc: optional RPC method name to use as the readiness oracle
#              (default: a benign read-like unary method — Fetch/Get/List/… —
#              of the first service found in the generated *_pb2_grpc module
#              next to the server; falls back to the first unary method).
#              REQUIRED when the service has no read-like method: the
#              all-default fallback request could otherwise perform a real
#              write on a stateful store.
# Env: KV_LOG=<logfile>           (default /tmp/kvserver.log)
#      KV_CLEAN_BY_NAME=1         opt-in basename sweep (see step 1)
#      KV_PROBE_DIRS=<dirs>       colon-separated dirs to scan for generated
#                                 *_pb2_grpc.py modules (default: server dir);
#                                 set when bindings live outside the server dir
#
# Lifecycle guarantees, in order:
#   1. Stale-server reclamation: DEFAULT reclaims only the OWNER of the
#      LISTEN socket on :<port> (inode resolution in /proc/net/tcp and
#      /proc/net/tcp6 — a name proxy is never used by default; opt-in
#      KV_CLEAN_BY_NAME basename sweep skips PIDs owning other LISTEN ports).
#   2. Verify-and-wait after kill: loop until the port leaves LISTEN
#      (escalate to SIGKILL on a stubborn owner) BEFORE relaunching.
#   3. Post-launch verification: the new PID is alive (kill -0) AND owns the
#      LISTEN socket on :<port> (inode match). Dump the log and abort loudly
#      otherwise (e.g. "address already in use" buried in the log).
#   4. Readiness oracle = a REAL probe RPC succeeding. Channel READY is only
#      a fast-fail precondition: READY proves the HTTP/2 transport handshake,
#      NOT servicer registration or handler safety. A READY server with a
#      missing/typo'd add_<Service>Servicer_to_server answers UNIMPLEMENTED
#      and is correctly rejected here. Probe requests are built via
#      method.input_type._concrete_class() so nested message definitions work.
#      Probes are READ-ONLY BY DEFAULT and the script ENFORCES it: auto mode
#      only ever calls case-folded benign-prefixed unary methods
#      (Fetch/Get/List/Read/Query/Peek/Count/Has/Exists — any case); if no
#      such method exists, it FATALs with 'pass probe_rpc' BEFORE any RPC
#      fires (no mutator fallback, ever). Explicit probe_rpc matches the
#      declared name exactly and tolerates per-candidate UNIMPLEMENTED like
#      auto mode; the round verdict (all candidates failed definitively) is
#      global, so an unwired server still fast-fails ~1s.
set -euo pipefail

server_py="${1:?usage: launch_and_probe.sh <server_py> <port> [ready_timeout_sec] [probe_rpc]}"
port="${2:?}"
timeout_sec="${3:-20}"
probe_rpc="${4:-}"
log="${KV_LOG:-/tmp/kvserver.log}"
server_dir="$(cd "$(dirname "$server_py")" && pwd)"
base="$(basename "$server_py")"
port_hex=$(printf '%04X' "$port")

# Identity primitive: PID owning the LISTEN socket on :$port (or empty).
# Scans BOTH /proc/net/tcp (IPv4) and /proc/net/tcp6 (IPv6/dual-stack): gRPC's
# add_insecure_port can create a dual-stack socket that only ever appears in
# tcp6 (observed in-container on v01).
port_owner_pid() {
  local inode p
  inode=$(awk -v hex="$port_hex" '
    FNR>1 && $4=="0A" { split($2,a,":"); if (a[2]==hex) { print $10; exit } }
  ' /proc/net/tcp /proc/net/tcp6 2>/dev/null | head -1)
  [ -n "$inode" ] || return 1
  for p in /proc/[0-9]*; do
    if ls -l "$p/fd" 2>/dev/null | grep -q "socket:\[$inode\]"; then
      echo "${p#/proc/}"
      return 0
    fi
  done
  return 1
}

# True iff at least one of the TCP tables carries a data row (procfs usable).
tcp_tables_have_data() {
  awk 'FNR>1 { n++ } END { exit (n>0 ? 0 : 1) }' /proc/net/tcp /proc/net/tcp6 2>/dev/null
}

# True iff something answers TCP on :$port (fallback busy-check when procfs
# hides the tables; a successful connect proves a LISTEN socket exists).
port_busy_by_connect() {
  python3 - "$port" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
    print("busy")
    s.close()
except OSError:
    pass
PY
}

# True iff pid $1 owns a LISTEN socket on a port OTHER than :$port
# (used by the opt-in basename sweep to spare unrelated live servers).
# Defined BEFORE the sweep below — the sweep calls it.
pid_has_other_listen() {
  local pid="$1" fdlink ino hit
  for fdlink in $(ls -l "/proc/$pid/fd" 2>/dev/null | grep -o 'socket:\[[0-9]*\]'); do
    ino="${fdlink#socket:[}"; ino="${ino%]}"
    hit=$(awk -v ino="$ino" -v hex="$port_hex" '
      FNR>1 && $4=="0A" { split($2,a,":"); if ($10==ino && a[2]!=hex) { print 1; exit } }
    ' /proc/net/tcp /proc/net/tcp6 2>/dev/null)
    if [ -n "$hit" ]; then
      return 0
    fi
  done
  return 1
}

# --- 1. stale-server reclamation ---
# DEFAULT: reclaim only the process that owns the LISTEN socket on :$port —
# the one property the launch actually needs. A basename sweep is a NAME
# proxy and is never the default: it would destroy an unrelated
# `python3 /data/server.py` that shares the basename (destructive over-match,
# the mirror image of the original over-matching glob). Opt-in via
# KV_CLEAN_BY_NAME=1; even then it is conservative: (a) only plain
# `python3 <path>` / `python3 <path> <arg>` invocations (<=3 argv tokens,
# path must exist as a file) — interpreter wrappers whose argv merely
# CONTAINS the basename text are never matched; (b) any PID that owns a
# LISTEN port OTHER than :$port is skipped (never touch a live unrelated
# server).
if [ -n "${KV_CLEAN_BY_NAME:-}" ]; then
  echo "note: KV_CLEAN_BY_NAME set — sweeping same-basename python server invocations (conservative)"
  for p in /proc/[0-9]*; do
    [ "$p" = "/proc/$$" ] && continue
    cmdline=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null) || continue
    argv0=$(printf '%s' "$cmdline" | awk '{print $1}')
    case "$argv0" in *python*) ;; *) continue ;; esac
    set -- $cmdline
    [ $# -ge 2 ] && [ $# -le 3 ] || continue
    for tok in "${2:-}" "${3:-}"; do      # ${n:-} keeps set -u happy for 2-token argv
      [ -n "$tok" ] || continue
      if [ "${tok##*/}" = "$base" ] && [ -f "$tok" ]; then
        if pid_has_other_listen "${p#/proc/}"; then
          echo "skip: pid ${p#/proc/} owns another LISTEN port (live server elsewhere)"
        else
          echo "WARN: opt-in sweep: killing pid ${p#/proc/} argv token '$tok'"
          kill "${p#/proc/}" 2>/dev/null || true
        fi
        break
      fi
    done
  done
fi

# --- 2. verify-and-wait: reclaim the :$port owner, then wait until the
# port actually leaves LISTEN before relaunching (never sleep 1 blindly) ---
wait_port_free() {
  local deadline=$((SECONDS + 15)) owner
  if ! tcp_tables_have_data; then
    echo "note: /proc/net/tcp* empty (hidden sandbox); using TCP connect as busy-check"
  fi
  owner=$(port_owner_pid || true)
  if [ -n "$owner" ]; then
    echo "reclaiming :$port: killing owner pid $owner"
    kill "$owner" 2>/dev/null || true
    deadline=$((SECONDS + 5))   # grace period before SIGKILL escalation
  fi
  while true; do
    owner=$(port_owner_pid || true)
    if [ -n "$owner" ]; then
      if [ $SECONDS -ge $deadline ]; then
        echo "escalating: SIGKILL port owner $owner"
        kill -9 "$owner" 2>/dev/null || true
        deadline=$((SECONDS + 5))
      fi
      echo "port :$port still owned by pid $owner; waiting for release"
    elif port_busy_by_connect | grep -q busy; then
      if [ $SECONDS -ge $deadline ]; then
        echo "FATAL: :$port answers TCP but owner is undetectable; cannot reclaim blindly"
        exit 1
      fi
      echo "port :$port answers TCP but no /proc owner found; waiting"
    else
      break
    fi
    sleep 1
  done
}
wait_port_free
echo "port :$port free"

# --- 3. launch + post-launch verification (alive AND bound) ---
cd "$server_dir"
nohup python3 "$server_py" > "$log" 2>&1 &
newpid=$!
echo "launched $server_py pid=$newpid log=$log"

sleep 1
if ! kill -0 "$newpid" 2>/dev/null; then
  echo "FATAL: server pid $newpid died at launch:"
  cat "$log" 2>/dev/null || true
  exit 1
fi

bound=""
procfs_usable=""
if tcp_tables_have_data; then procfs_usable=1; fi
deadline=$((SECONDS + 15))
while [ -z "$bound" ]; do
  if [ -n "$procfs_usable" ]; then
    owner=$(port_owner_pid || true)
    if [ -n "$owner" ] && [ "$owner" = "$newpid" ]; then
      bound=1
      break
    fi
    if [ -n "$owner" ] && [ "$owner" != "$newpid" ]; then
      echo "FATAL: :$port owned by pid $owner, not new pid $newpid"
      cat "$log" 2>/dev/null || true
      exit 1
    fi
  fi
  if ! kill -0 "$newpid" 2>/dev/null; then
    echo "FATAL: server pid $newpid died before binding :$port:"
    cat "$log" 2>/dev/null || true
    exit 1
  fi
  if [ $SECONDS -ge $deadline ]; then
    if [ -n "$procfs_usable" ]; then
      echo "FATAL: pid $newpid never bound :$port (owner=${owner:-none}):"
      cat "$log" 2>/dev/null || true
      exit 1
    else
      # No socket tables: bind ownership undecidable here; the RPC oracle
      # below is the decisive check.
      echo "warn: cannot prove bind ownership (no /proc/net/tcp* data)"
      break
    fi
  fi
  sleep 1
done
echo "pid $newpid alive and LISTENing on :$port"

# --- 4. readiness oracle: a REAL probe RPC must succeed ---
# Generated-module locations: server_dir by default; a variant that keeps
# bindings elsewhere (out-of-dir codegen) sets KV_PROBE_DIRS=<colon-separated dirs>.
probe_dirs="${KV_PROBE_DIRS:-$server_dir}"
if python3 - "$port" "$timeout_sec" "$log" "$probe_dirs" "$probe_rpc" <<'PY'
import glob, importlib, os, sys, time, grpc
port, timeout = int(sys.argv[1]), float(sys.argv[2])
log, probe_dirs, probe_rpc = sys.argv[3], sys.argv[4], sys.argv[5]

mods = []
for d in probe_dirs.split(":"):
    if not d:
        continue
    sys.path.insert(0, d)
    mods.extend(sorted(glob.glob(os.path.join(d, "*_pb2_grpc.py"))))
mods = sorted(set(mods))
if not mods:
    sys.exit("FATAL: no *_pb2_grpc.py modules found in %s" % probe_dirs)

# Load every module pair; keep their descriptors for the service sweep.
pairs = []
for m in mods:
    sys.path.insert(0, os.path.dirname(m))
    grpc_mod_name = os.path.basename(m)[:-3]   # e.g. kv_store_pb2_grpc
    pb2_mod_name = grpc_mod_name[:-5]          # strip trailing '_grpc'
    pairs.append((importlib.import_module(pb2_mod_name),
                  importlib.import_module(grpc_mod_name)))

ch = grpc.insecure_channel("localhost:%d" % port)
deadline = time.time() + timeout
# Precondition: transport READY (fast-fail; proves only the HTTP/2 handshake).
try:
    grpc.channel_ready_future(ch).result(timeout=min(5.0, timeout))
except Exception as e:
    print("--- server log ---")
    print(open(log).read() if os.path.exists(log) else "(no log)")
    sys.exit("FATAL: channel never reached READY (%s) — transport only; servicer unknown" % e)

BENIGN_PREFIXES = ("fetch", "get", "list", "read", "query", "peek", "count", "has", "exists")

def benign(name):
    # Case-folded: proto rpc names may legally be lowerCamel/lowercase
    # (`rpc fetch(...)`), and the generated stub keeps the declared name.
    return name.lower().startswith(BENIGN_PREFIXES)

# Oracle: sweep EVERY service in EVERY generated module. A multi-service
# proto may register only one servicer, so UNIMPLEMENTED on one service must
# move on to the next candidate rather than fail the launch. Requests are
# built via method.input_type._concrete_class() (works for top-level AND
# nested message definitions).
#
# Candidate policy is OBSERVATION-ONLY in auto mode: only benign-prefixed
# unary methods are candidates — a mutator fallback would perform a real
# write on a stateful store. If no benign method exists anywhere, FATAL
# before any RPC fires, telling the operator to pass probe_rpc explicitly.
# Explicit probe_rpc matches the declared name exactly and tolerates
# per-candidate UNIMPLEMENTED exactly like auto mode (the round verdict is
# global, below).
candidates = []
for pb2, grpc_mod in pairs:
    for svc_name in pb2.DESCRIPTOR.services_by_name:
        svc = pb2.DESCRIPTOR.services_by_name[svc_name]
        unary = [m for m in svc.methods if not m.client_streaming and not m.server_streaming]
        if probe_rpc:
            m = next((x for x in unary if x.name == probe_rpc), None)
        else:
            m = next((x for x in unary if benign(x.name)), None)
        if m is not None:
            candidates.append((pb2, grpc_mod, svc_name, m))
if not candidates:
    if probe_rpc:
        sys.exit("FATAL: no unary method '%s' in any service to probe" % probe_rpc)
    sys.exit("FATAL: no benign read-like unary method (fetch/get/list/read/query/peek/count/has/exists) found in any service; pass probe_rpc explicitly")

last_code = None
while time.time() < deadline:
    round_codes = []
    for pb2, grpc_mod, svc_name, method in candidates:
        try:
            stub = getattr(grpc_mod, svc_name + "Stub")(ch)
            request = method.input_type._concrete_class()
            getattr(stub, method.name)(request, timeout=2)
            print("endpoint ready (probe %s.%s ok)" % (svc_name, method.name))
            sys.exit(0)
        except grpc.RpcError as e:
            last_code = e.code()
            round_codes.append(e.code())
            # UNIMPLEMENTED is ALWAYS per-candidate (a service may simply
            # not be registered); the round verdict below is global — an
            # explicit probe_rpc gets the same tolerance as auto mode.
            if e.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                continue   # transport flake / slow init: retry all candidates
        except Exception as e:
            sys.exit("FATAL: probe call raised %r" % (e,))
    if round_codes and all(c not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)
                           for c in round_codes):
        # Every candidate failed on a definitive non-transport code
        # (e.g. UNIMPLEMENTED everywhere = nothing serves): fail fast.
        print("--- server log ---")
        print(open(log).read() if os.path.exists(log) else "(no log)")
        sys.exit("FATAL: every probe candidate failed: %s" % sorted(set(round_codes), key=str))
    time.sleep(0.5)

print("--- server log ---")
print(open(log).read() if os.path.exists(log) else "(no log)")
sys.exit("FATAL: no probe RPC succeeded before deadline (last code: %s)" % last_code)
PY
then
  :
else
  rc=$?
  echo "FATAL: readiness probe failed; stopping launched pid $newpid"
  kill "$newpid" 2>/dev/null || true
  exit "$rc"
fi