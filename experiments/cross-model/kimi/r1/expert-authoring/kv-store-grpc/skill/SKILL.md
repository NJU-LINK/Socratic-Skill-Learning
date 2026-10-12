---
name: kv-store-grpc
description: >
  Build and leave running a stateful in-memory Python gRPC service (key-value /
  namespaced-store style) from a precise spec: install pinned grpcio packages,
  author the .proto with exact service/RPC/message/field definitions, generate
  Python bindings, implement the servicer with correct cross-call state
  semantics, launch it detached on the required port, and self-verify with a
  real gRPC client before finishing.
---

# kv-store-grpc

## Family contract (invariants)

Every task in this family asks for the same pipeline, with exact identifiers dictated by the instruction:

1. Install pinned `grpcio` / `grpcio-tools` system-wide (pip as root is fine).
2. A `.proto` file at an exact path with an exact service, RPC set, messages, field names, field numbers, and field types.
3. Generated `*_pb2.py` and `*_pb2_grpc.py` modules at exact paths with exact names.
4. A server file (e.g. `/app/server.py`) exposing a servicer class with an exact name (e.g. `Server`), listening on an exact port.
5. In-memory state that persists across RPC calls and across client channels (single long-lived process), with deterministic per-RPC semantics (defaults for missing keys, overwrite/delete/aggregate contracts, isolation between namespaces or collections).
6. The server **left running** — tests execute after the agent finishes, possibly in a different shell.

What varies (per spec axes): number/shape of RPCs and fields (multi-field, nested, `repeated`, enums, naming), state semantics (deletes, resets, conditional updates, aggregates, multi-key ops, multiple namespaces/collections), and runtime demands (longer test windows, concurrent bursts, startup/readiness requirements, repeated channel creation).

Grader surface (observed from v01 test names — expect analogous checks in variants): proto file exists with the right content, the pinned packages are actually installed (`pip show`/`import`), generated modules exist, the server file exists, a real server answers on the port, and full behavioral semantics hold over the wire. So both the *artifacts* and the *running process* are graded — a perfect server with a misnamed file fails, and perfect files with a dead server fail.

## Workflow

### 1. Extract the exact contract first

Before writing anything, list verbatim from the instruction: proto path, syntax/package, service name, every RPC name + request/response message names, every field (name, number, type, repeated/map/enum qualifiers), generated module filenames, server path, servicer class name, port, and every stated behavioral rule (missing-key default, overwrite vs reject, delete return values, aggregate scope, namespace isolation). Treat these as test assertions — copy names and numbers character-for-character.

### 2. Install dependencies

```bash
pip install grpcio==<PIN> grpcio-tools==<PIN>   # use the versions the task pins
```

Keep `grpcio` and `grpcio-tools` on the same version: generated `*_pb2_grpc.py` performs a grpc-version compatibility check at import time. If the task pins no version, pick a recent matched pair.

### 3. Author the proto

- `syntax = "proto3";` unless told otherwise; add `package` only if specified.
- Field numbers and types exactly as specified; numbers unique per message.
- proto3 cheat-sheet (all patterns verified with grpcio-tools 1.73.0 / protobuf 6.x):

| Spec says | proto syntax | Python handling |
|---|---|---|
| list of scalars/msgs | `repeated int32 nums = 1;` | ctor `pb.M(nums=[1,2])`; mutate with `.extend()` / `.append()` / `.add()` for msg items — plain assignment `m.nums = [...]` raises `AttributeError` |
| string-keyed dict | `map<string, int32> m = 2;` | ctor `pb.M(m={"a":1})`; mutate `m.m["b"] = 2`; iterate `dict(m.m)` |
| enum | `enum Color { RED = 0; GREEN = 1; }` — **first value must be `= 0`** | compare `resp.color == pb.Color.Value("GREEN")`; top-level values also at `pb.GREEN`; unset enum reads as the zero value |
| nested message | `message Inner { ... }` then `Inner child = 6;` | ctor `pb.M(child=pb.Inner(x=1))`; presence via `m.HasField("child")` |
| one-of | `oneof choice { string s = 7; int32 i = 8; }` | read `req.WhichOneof("choice")` → field name or `None` |
| explicit presence | `optional int32 maybe = 9;` | `req.HasField("maybe")` works; note `HasField` on a *plain* (non-optional) scalar raises `ValueError` |

- Unset proto3 scalars deserialize as `0` / `""` / `false`; unset enums as the zero value. A client omitting a field is indistinguishable from sending the default — implement "missing" semantics server-side, not via presence, unless the spec declares `optional`.
- `package` affects only the wire path (`/pkg.Service/Method`); Python module and class names are unchanged (verified).
- Proto field names may be Python keywords (`from`, `type`, ...): protoc accepts them, but `msg.from` is a `SyntaxError` in your code — construct with `pb.M(**{"from": v})` and read with `getattr(msg, "from")` (verified).
- If the spec ever declares `stream`: server-streaming handlers `yield` responses in a loop; client-streaming handlers consume `request_iterator` (e.g. `sum(r.n for r in request_iterator)`). Default to unary otherwise.

### 4. Generate bindings

```bash
cd /app && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <file>.proto
```

- protoc maps the proto basename to Python module names by replacing `-` and `.` with `_`: `kv-store.proto` → `kv_store_pb2.py` + `kv_store_pb2_grpc.py` (verified with grpcio-tools 1.73.0). Confirm the emitted filenames match the required ones.
- If the task ever requires module names that differ from what protoc emits, generate, then rename the files and fix the `import X_pb2 as ...` line at the top of `*_pb2_grpc.py`.
- Never hand-edit generated files otherwise; regenerate after any proto change.
- Sanity check: `cd /app && python3 -c "import <mod>_pb2, <mod>_pb2_grpc"`.

### 5. Implement the server

Template (adapt names/types to the contract):

```python
import threading
from concurrent import futures
import grpc
import kv_store_pb2 as pb          # generated modules
import kv_store_pb2_grpc as pbg

class Server(pbg.KVStoreServicer):  # exact class name from the task
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}             # e.g. namespace -> {key: value}

    def Put(self, request, context):
        with self._lock:
            self._data.setdefault(request.namespace, {})[request.key] = request.value
            return pb.PutResponse(value=request.value)
    # ... implement EVERY rpc in the service ...

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    pbg.add_KVStoreServicer_to_server(Server(), server)
    bound = server.add_insecure_port("[::]:<PORT>")
    assert bound != 0, "port bind failed"
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
```

Non-negotiable rules:

- **State ownership**: create all state in `__init__` of the servicer instance, never inside a handler and never per-channel. One process = one store; any number of client channels then observe the same state.
- **Locking**: gRPC dispatches handlers on a thread pool. Guard every read-modify-write (and multi-step reads like aggregates) with one `threading.Lock` held for the *whole* operation, so concurrent bursts cannot corrupt, lose updates, or observe half-applied multi-key writes.
- **Never raise out of a handler**: an uncaught exception reaches clients as `UNKNOWN` and leaves a traceback in the log. Catch expected bad input and return the spec'd default response instead.
- Build a fresh response message per call; never share or mutate response objects across calls.
- Bind `"[::]:<PORT>"` (dual-stack; verified to accept both `127.0.0.1` and `localhost`/`::1` clients). Check the returned bound port is non-zero.
- Run the server from the directory containing the generated modules (or put it on `PYTHONPATH`) so `import *_pb2` resolves.
- **Import-safety**: `serve()` must run only under `if __name__ == "__main__":`. A grader may `import server` to inspect the class or unit-call handlers; a top-level `serve()` hangs that import forever (verified) and, if the live server is already bound, crashes it with a port conflict. For the same reason, handlers should not depend on the `context` argument — direct calls with a dummy context must work.

Translate behavioral prose into handler logic with these patterns (all inside one lock acquisition):

| Spec phrase | Handler pattern |
|---|---|
| "returns D for a missing key" | `store.get(ns, {}).get(key, D)` — never `store[ns][key]` |
| "creates or overwrites" | plain assignment `ns[key] = value` |
| "increments / adds / accumulates" | `ns[key] = ns.get(key, 0) + delta` (read-modify-write — lock mandatory) |
| "conditional update (only if …)" | evaluate the condition *inside* the lock, then write or return the rejection contract |
| "delete returns removed value + flag" | `if key in ns: return ok(ns.pop(key)) else: return miss_contract` |
| "reset / clear (namespace or all)" | `self._data.pop(ns, None)` or `self._data.clear()` |
| "aggregate over scope" | compute from current store contents only, e.g. `sum(ns.values())`; absent scope → spec'd default (usually 0) |
| "multi-key op (mget/mset/swap)" | apply *all* keys under one lock acquisition so concurrent clients never observe a partial result |
| "namespaces are isolated" | never let one namespace's handler touch another's dict; aggregates must not cross scopes |

### 6. Launch detached and keep it alive

Tests run after the agent's commands finish (observed: `run_tests_in_same_shell: false`), so the process must be fully detached:

```bash
cd /app && nohup python3 server.py > server.log 2>&1 & echo $! > server.pid
```

- Plain `nohup ... &` keeps `$!` = the python PID (verified). Prefixing `setsid` detaches the session even harder, but then `$!` is the setsid wrapper, not python — find the real PID by scanning `/proc/*/cmdline` if you need it (verified behavior).
- **Minimal container** (verified): no `ps`, `ss`, `netstat`, `lsof`, `curl`, `pkill`. Check liveness via the port (below) and `/proc/<pid>` or `kill -0 <pid>`; kill via the bash builtin `kill <pid>`.
- Never leave the server in a foreground/blocking command; never rely on a shell that will exit.

### 7. Self-verify with a real gRPC client (mandatory)

Write a throwaway client in `/tmp` (import the generated modules via `sys.path.insert(0, "/app")`) and assert all of the following:

1. **Readiness with retry** (tolerates slow startup):
   ```python
   ch = grpc.insecure_channel(f"localhost:{PORT}")
   grpc.channel_ready_future(ch).result(timeout=10)   # retry the whole check a few times if it raises
   ```
2. **Happy path**: every RPC in the service round-trips with expected values.
3. **Every stated edge semantic**: missing-key defaults, overwrite behavior, delete-missing contract, aggregate of absent/empty scope, isolation between namespaces/collections.
4. **Cross-channel persistence**: open a *second, fresh* channel and confirm previously written state is visible (proves state is server-side, not per-channel).
5. **Burst** (when concurrency is in scope): fire N parallel calls from threads (e.g. puts/increments to the same key) and assert the final state reflects all of them — shakes out missing locks.
6. **End state**: server still alive and port still accepting connections as the very last check; `server.log` free of tracebacks.
7. **Artifact self-audit** (mirrors the grader surface): every required file exists at its exact path; `python3 -c "import grpc; print(grpc.__version__)"` matches the pin; generated modules import cleanly from their directory; the server file contains the exact servicer class name and `import server` returns promptly (import-safety).

Verification hygiene:

- Probe only with invented keys/namespaces under an unusual prefix (e.g. `__selfcheck__`) so leftover probe state cannot collide with anything the grader asserts on.
- If the spec includes a reset/clear RPC, end verification by calling it.
- Do **not** restart the server after successful verification — the running, verified process is the deliverable; a last-minute relaunch only adds risk.

If any check fails, fix, **restart the server** (`kill $(cat /app/server.pid)`, relaunch), and re-run the whole client — stale processes serving old code are a common silent failure.

## Pitfalls

| Symptom | Cause / fix |
|---|---|
| Tests find nothing listening | server ran in foreground then shell exited, or not detached → relaunch with `nohup ... &`; verify port from a *separate* command |
| `port open` but RPCs fail with old behavior | stale server process still bound → kill PID, relaunch, re-verify |
| State resets between calls | store initialized inside handler or server restarted → state in `__init__`, one process |
| Lost updates under burst | no lock around read-modify-write → `threading.Lock` held for the whole op |
| Client gets `UNKNOWN`, traceback in server.log | handler raised (e.g. `KeyError` from `store[ns][key]`) → use `.get` with spec'd defaults, never raise |
| `ModuleNotFoundError: *_pb2` | server launched from wrong cwd, or expected filename has hyphens — protoc emits underscored module names |
| Import-time grpc version error | grpcio/grpcio-tools version mismatch → install matched pinned pair |
| protoc/compile errors on enum | proto3 requires first enum value `= 0` |
| `AttributeError: Assignment not allowed` | reassigning a `repeated`/`map` field → set in constructor or mutate with `.extend()` / `.add()` / `m[k] = v` |
| `ValueError` from `HasField` | called on a plain proto3 scalar → only valid for `optional` scalars and message fields; use `WhichOneof` for oneofs |
| Test/import of `server.py` hangs or crashes | `serve()` at module top level → keep it behind `if __name__ == "__main__":` (verified: top-level serve blocks import indefinitely) |
| `SyntaxError` around a field access | proto field name is a Python keyword → use `getattr(msg, "from")` / `**{"from": v}` |
| Client can't connect on `127.0.0.1` | bound to a specific interface → bind `"[::]:PORT"` |
| Integer serialization error | aggregate exceeded int32 → sum is over stored int32 values; keep totals within int32 or use int64 if the spec allows |
