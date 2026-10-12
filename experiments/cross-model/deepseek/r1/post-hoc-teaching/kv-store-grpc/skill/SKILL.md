---
name: kv-store-grpc
description: >-
  Build and deploy a real Python gRPC stateful store service from a protobuf
  spec: write the .proto (any unary RPC surface, incl. multi-field, nested,
  repeated, enum message shapes), generate bindings with grpc_tools.protoc,
  implement the servicer in Python with deterministic in-memory state
  semantics (namespaces, put/fetch/delete, aggregates, conditional or
  multi-key ops), and leave a live, detached, ready-to-serve gRPC endpoint
  that survives the agent shell for a pytest grader running in a separate
  shell. Covers concurrency bursts, repeated client channels, readiness and
  long-lived serving requirements.
---

# kv-store-grpc: build + run a Python gRPC stateful store

## 1. Family definition (what this skill is for)

The task family pairs a **protobuf/gRPC interface spec** with **deterministic
in-memory state semantics** and a **runtime requirement**: after your work, a
real gRPC server must be listening on a given port and stay alive so a pytest
grader (running in a **separate shell**, `run_tests_in_same_shell: false`) can
connect to it. The grading surface is typically: (a) files exist on disk
(`*.proto`, `*_pb2.py`, `*_pb2_grpc.py`, `server.py`), (b) `server.py` imports
cleanly and exposes a named class, (c) a client stub can reach the live
endpoint and observe exact semantics, (d) pinned `grpcio`/`grpcio-tools`
versions are installed system-wide.

### Family invariants (from anchor v01, directly verified)
- A `.proto` file (proto3) declaring service(s) and messages; Python bindings
  generated from it: proto file `kv-store.proto` -> modules `kv_store_pb2.py`
  and `kv_store_pb2_grpc.py` (**hyphens become underscores**; module prefix =
  proto basename).
- `_pb2_grpc.py` imports the pb2 module by absolute name
  (`import kv_store_pb2 as kv_store__pb2`), so generated files + server code
  must sit in one importable directory.
- A servicer class (anchor name: `Server`) subclassing
  `{Service}Servicer`; one method per RPC **named exactly like the RPC**;
  handlers return the generated response message.
- In-memory state stored on the servicer instance persists **across calls and
  across client channels/processes** (verified on v01: value written by one
  client was fetched by a fresh process/channel).
- Server must be **left running** on the specified port, bound to `0.0.0.0`,
  surviving the agent's shell exit (verified: detached process lived across
  many separate shells).
- Exact identifiers are contract: RPC names, message/field names, field
  types, **field numbers**, file names, port, class name.
- `server.py` must be import-safe: no blocking launch code at module level
  (grader may `import server` and instantiate the class directly).

### Declared variation axes (from spec.yaml — see §5 for per-axis guidance)
- **rpc_api_structure**: more RPCs per service; multi-field requests/responses;
  nested or repeated message fields; enums and other field combos; naming
  variations. Bindings/wiring must still come out correct.
- **stateful_service_semantics**: larger key spaces, multiple collections /
  namespaces, deletes, resets, conditional updates, aggregate reads,
  multi-key operations — deterministic, state preserved over a session.
- **runtime_interaction_requirements**: longer test windows, concurrent /
  closely spaced request bursts, startup-delay/readiness expectations,
  repeated channel creation, other conditions that kill a correct-but-fragile
  deployment (e.g., server dying with the agent shell).

## 2. Procedure (works for the whole family)

### Step 1 — Read the task like a contract
Inventory before writing anything:
- Proto file **path/name** (defines module prefix) and syntax (assume proto3;
  check for `optional` keywords and `oneof` groups — they CHANGE the Python
  contract: `optional` scalars gain `HasField`/`ClearField` (absent != zero
  on the REQUEST side), and `oneof` members are read via
  `request.WhichOneof("group")` (member name or `None`).  If any field is
  `optional`/`oneof`, every handler touching it MUST route through
  `HasField`/`WhichOneof` — paragraph in §3/presence rule + mandatory
  battery cases in §4.  Message-typed fields always have presence;
  `repeated`/`map` signal emptiness only by length.
- Every service, RPC, message; every field: name, type, **number**, repeated?
  nested? enum? map?
- Port to listen on; server class name; file names for generated bindings;
  exact pinned grpc versions to install.
- Each RPC's semantics in prose — translate to code *exactly* (see §3).
  Note defaults for missing keys/absent namespaces.

### Step 2 — Install pinned gRPC (system-wide)
```bash
python3 -m pip install grpcio==<PIN> grpcio-tools==<PIN>
python3 -c "import grpc, grpc_tools; print(grpc.__version__)"   # sanity
```
- Anchor used `grpcio==1.73.0` / `grpcio-tools==1.73.0`; a cp313 wheel exists
  (verified on Python 3.13.1). Installed this way it is "system-wide" (no
  venv) and importable by the grader.
- If the pinned version has no wheel for the env's Python, pip falls back to a
  source build (needs C++ toolchain, slow/fragile): pre-check wheel
  availability with
  `pip download grpcio==<PIN> --no-deps -d /tmp/w -q` and inspect the file; if
  missing, look for a compatible manylinux wheel (e.g., older pin) or build —
  but keep the exact pin installed **somehow** since the grader may version-check.

### Step 3 — Write the .proto
proto3 skeleton (anchor form; extend per task):
```proto
syntax = "proto3";
package kvstore;                       // package name is your choice

service KVStore {                      // service name must match task
  rpc Put(PutRequest) returns (PutResponse);
  rpc Fetch(FetchRequest) returns (FetchResponse);
  // ... every RPC from the task, names verbatim
}

message PutRequest {
  string namespace = 1;                // field NUMBER must match task
  string key = 2;
  int32 value = 3;
}
message PutResponse { int32 value = 1; }
// ... one message per request/response type, fields/numbers verbatim
```
Rules that matter:
- RPC method names become (a) stub methods camelCased by protoc and
  (b) servicer handler names — copy them exactly.
- proto3 enums: first member must be value 0. Numeric field types: `int32`,
  `int64`, `uint32`, `float`, `double`, `bool`, `string`, `bytes`.
- Multi-field, nested, repeated, enum, map constructs all work in the same
  file — see §5 for Python-side handling.

### Step 4 — Generate bindings
```bash
python3 -m grpc_tools.protoc -I <DIR-CONTAINING-PROTO> \
    --python_out=<OUT> --grpc_python_out=<OUT> <path/to/proto>
# -> <OUT>/<name>_pb2.py, <OUT>/<name>_pb2_grpc.py
```
**The layout contract: proto location × output location × module name are
one contract.** protoc derives the generated file path AND the Python module
name from the proto's path *relative to -I*, preserving directory components.
The family rule: the proto must sit at the TOP LEVEL of `-I`, i.e. `-I` is
its CONTAINING directory — never `--out` by default.  Then generated modules
are top-level in `--out` and named from the proto basename (`-` and `.` both
map to `_`: `kv-store.proto` and `kv.store.proto` BOTH -> `kv_store_pb2` —
a collision to avoid; use the task's exact name).  If the task puts the proto
in a subdir but wants bindings flat elsewhere (e.g. proto
`/app/protos/kv-store.proto`, bindings in `/app`), use
`-I /app/protos --python_out=/app`: the -I-relative path is then exactly the
basename and the output is flat.

A wrong `-I` is a SILENT failure: protoc exits 0, but `-I /app` with proto
`/app/protos/kv-store.proto` writes `/app/protos/kv_store_pb2.py` and the
`_pb2_grpc.py` gets `import protos.kv_store_pb2 as ...`; the grader's
`import kv_store_pb2` then `ModuleNotFoundError`s while all your logs look
clean.  So ASSERT the contract after generation — never trust protoc's exit
code alone:

```bash
# the generated import line must name the module TOP-LEVEL (no package prefix).
# The pb2 import is NOT the first line (grpc/warnings come first) — grep for it:
grep -nF "import ${MOD}_pb2" "$OUT"/*_pb2_grpc.py
#   flat OK:    1:import kv_store_pb2 as kv_store__pb2
#   broken:     1:import protos.kv_store_pb2 as protos__kv_store__pb2
# smoke import from a grader-like process:
python3 -c "import sys; sys.path.insert(0, '$OUT'); import kv_store_pb2, kv_store_pb2_grpc; print('importable OK')"
```
The deploy helper does this automatically (stage 0: module-name contract
check + import smoke); if you generate manually, run both checks yourself.
- Sibling protos: if the proto `import`s other protos, keep ALL of them at
the top level of `-I` and pass every one of them to protoc (imports use
root-relative names like `"common.proto"`); well-known types resolve
implicitly.
- Keep proto + generated files + server.py importable from the same sys.path
for both your server and the grader's client (which likely does
`cd /app` / `PYTHONPATH=/app`).

### Step 5 — Implement server.py
Structure that is import-safe, thread-safe, and live (anchor-verified):
```python
import threading
from concurrent import futures
import grpc
import kv_store_pb2
import kv_store_pb2_grpc

class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self):
        # State lives HERE (on the instance) so it persists and is
        # unit-testable: grader can instantiate Server() directly.
        self._data = {}                 # namespace -> {key -> value}
        self._lock = threading.RLock()  # guards all mutations

    def Put(self, request, context):
        with self._lock:
            ns = self._data.setdefault(request.namespace, {})
            ns[request.key] = request.value
            return kv_store_pb2.PutResponse(value=request.value)
    # ... one handler per RPC (see §3 for semantics patterns)

def serve(port: int = 5328) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port(f"0.0.0.0:{port}")   # 0.0.0.0, not 127.0.0.1
    server.start()
    return server

if __name__ == "__main__":
    serve().wait_for_termination()   # ONLY in __main__ guard
```
- **`__main__` guard is mandatory**: the grader may `import server`; an
  unconditional `serve()` at module level would hang their import.
- `max_workers` >= expected concurrency (16 is safe); `RLock` makes bursts
  atomic (verified: 8 threads × 100 puts => exact total 800).
- If multiple services are in the proto, subclass each
  `{Service}Servicer` (or one class per service) and call every
  `add_{Service}Servicer_to_server`.

### Step 6 — Launch, keep alive, verify

> **Reusable helper**: `scripts/deploy_grpc_store.py` in this skill package
> automates steps 4+6 for any variant and enforces two invariants:
> **the generated module layout obeys the protoc contract** (stage 0: `-I`
> is the proto's containing dir, outputs are flat top-level `*_pb2*` files,
> verified via import-line check + a grader-like import smoke test) and
> **the port is owned by the process this script launched, and that process
> answered a real RPC**. It evicts the port's current owner by
> `/proc/net/tcp{6}` socket-inode ownership (never by process name —
> relative launches like `cd /app && exec python3 server.py` defeat name
> matching), launches the server detached (`start_new_session=True`) and
> captures the real child PID, asserts the launched PID owns the port
> **before** any readiness probe, then probes in tiers: (1) real gRPC
> handshake via `grpc.channel_ready_future` (distinguishes gRPC from a bare
> TCP listener), (2) optional functional RPC through the generated stubs via
> `--probe-cmd` — the helper puts the out-dir on `PYTHONPATH` (and cwd) for
> the probe, so probe scripts can `import <name>_pb2` regardless of how they
> are invoked (no `cd`/`PYTHONPATH=` gymnastics needed in the probe command),
> (3) `server.log` must not contain traceback/EADDRINUSE (log is truncated
> per deployment). Any failed stage exits nonzero with the log tail.
>
> **Where to find the helper inside the container**: the skill package may
> be mounted read-only, commonly at `/skill` — try
> `python3 /skill/scripts/deploy_grpc_store.py --help` first; if not,
> `find / -name deploy_grpc_store.py 2>/dev/null`; if the package is not
> reachable at all (the host workspace path is NOT visible inside `/app`),
> recreate the file from the full source embedded in **Appendix A** at the
> end of this document (it is compact and self-contained). The battery
> skeleton `scripts/verify_battery.py` (see §4) lives in the same scripts/
> directory. Do not waste
> calls hunting: one `find` or a direct `/skill` attempt settles it.
>
> Usage (probe needs no PYTHONPATH — the helper injects it):
> ```bash
> python3 deploy_grpc_store.py \
>   --proto /app/kv-store.proto --out /app --port 5328 \
>   --cmd "python3 /app/server.py" \
>   --probe-cmd "python3 /tmp/probe.py"
> ```

```bash
# Preferred: recreate/run the helper (Appendix A implements ALL of this).
# If you must go fully manual, keep this exact ordering — each step's code is
# in Appendix A's port_owner_pids() + main():
#   1) EVICT port owner via /proc/net/tcp{6} LISTEN inode -> /proc/<pid>/fd
#      socket:[inode] readlinks; kill it; wait until port is free.
#   2) LAUNCH detached: python3 -c 'import subprocess,sys; p=subprocess.Popen(\
#      sys.argv[1].split(), start_new_session=True, stdout=open(LOG,"wb"), \
#      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL); print(p.pid)' \
#      "python3 /app/server.py"   # capture the printed PID
#   3) ASSERT: port_owner(port) must contain that PID — do this BEFORE probing.
#   4) TIER1: grpc.channel_ready_future(ch).result(timeout=10) — a raw TCP
#      connect proves only that SOMEONE listens.
#   5) TIER2: one real RPC via generated stubs, run with PYTHONPATH=<outdir>.
#   6) TIER3: grep server.log for 'traceback|address already in use|EADDRINUSE';
#      fail on a match (log was truncated per deployment).
```
Then run your own end-to-end battery **in a fresh `task_shell` call** (proof
of cross-shell survival) exercising every RPC and every semantic edge (see §4
template). Re-run a second time from another fresh shell to prove state
persists across channels/processes — and confirm the endpoint answers with
*your* semantics, not merely a TCP accept.

## 3. Turning semantic prose into code (stateful-service patterns)

Map the task's prose to handlers with a lock-protected in-memory structure.
Patterns (anchor + reasoned extrapolation):
- **Namespaced dict store**: `dict[str, dict[str, int]]`; `setdefault` on put.
- **Missing-key default** (anchor: Fetch returns 0): read via
  `ns.get(key, DEFAULT)`; absent namespace treated same as empty (`dict.get(ns, {})`).
- **Delete** (anchor: return removed value + `success` bool): pop; on missing
  key/namespace return `success=False` + zero value — **do not raise**.
- **Aggregate reads** (anchor: ListNamespaceTotal): compute from current
  state under lock (`sum(ns.values())`); absent/empty -> 0. Mirror the
  response field's declared type exactly. If building the response ever
  raises `ValueError: Value out of range` (int32/int64 overflow), treat it
  as a **bug beacon**, not a prompt to alter output: the task's own
  reference could not return an out-of-range field, so no legal test can
  expect one. The divergence means your computation disagrees with the
  reference — wrong namespace scope, mishandled delete/reset, wrong key
  set, or a stored value that violates the spec's value domain. Never
  clamp, saturate, or downcast; find the scope bug instead.
- **Resets**: clear one namespace or all, return ack message per spec.
- **Conditional updates** (e.g. compare-and-swap, put-if-absent): check then
  mutate inside one lock hold so the check+set is atomic.
- **Multi-key/aggregate ops**: request has repeated keys -> loop; response has
  repeated `Entry{key,value}` or a total/count field -> fill accordingly.
- **Larger key spaces / many namespaces**: plain dicts scale fine; do not
  pre-size or serialize to disk (unless the task says so — it doesn't;
  "in memory" is the invariant).
- **Flat vs namespaced stores**: the family seed describes a FLAT store
  (one dictionary of values keyed by strings); namespaces are v01's
  elaboration. On flat variants every probe/battery write lands directly in
  the grader's world — follow §4 probe hygiene (collision-proof
  identifiers, self-cleaning writes, tier-4 final default read) or your own
  verification pollutes the graded state.

Concrete handler patterns for variant semantics (all atomic under one lock
hold; construct messages from the task's generated module):
```python
# Multi-key read: loop under ONE lock hold, build repeated entries
def GetMany(self, request, context):
    with self._lock:
        return pb2.GetManyResponse(entries=[
            pb2.Entry(key=k, value=self._data.get(k, 0)) for k in request.keys])

# Conditional update (compare-and-set): check + set atomic under one lock
def CompareAndSet(self, request, context):
    with self._lock:
        cur = self._data.get(request.key, 0)
        if cur == request.expected:
            self._data[request.key] = request.value
            return pb2.CasResponse(success=True, previous=cur)
        return pb2.CasResponse(success=False, previous=cur)

# Increment / read-modify-write: read + write under one lock
def Increment(self, request, context):
    with self._lock:
        cur = self._data.get(request.key, 0) + request.delta
        self._data[request.key] = cur
        return pb2.IncrResponse(value=cur)

# Resets: clear one scope or everything, returning an ack per spec
def ResetNamespace(self, request, context):
    with self._lock:
        self._data.pop(request.namespace, None)   # or .clear() if kept
        return pb2.Empty()
```
The pattern behind every one: **compute from current state under the lock**
and mirror the response fields the task declares; never cache aggregates or
assume a clean start.

**Presence reads vs value reads — decide per RPC from the prose.** The
family already distinguishes them (v01: `Fetch` returns 0 for missing =
value read, but `Delete` reports `success=false` for missing = presence
read).  The rule:
- prose says "if the key EXISTS / is ABSENT" -> membership test
  (`key in ns`), never the value — a stored 0 is existence;
- prose says "the current value is X; a missing key counts as 0" ->
  `ns.get(key, 0)`;
- conditional ops (put-if-absent, compare-and-set, delete-if) are where
  the two diverge: `if ns.get(key, 0) == 0` treats a stored 0 as absent
  and silently succeeds where the reference fails.  If 0 is a legal
  stored value, the battery MUST include `Put(k, 0)` followed by running
  the conditional op twice and asserting both outcomes (see §4).
- `optional`/`oneof` request fields are presence on the REQUEST side:
  e.g. an "update if provided" RPC is `if request.HasField("new_value"):
  ...`; reading `request.new_value != 0` conflates absent with zero:
```python
def Update(self, request, context):
    with self._lock:
        cur = self._data.get(request.key, 0)
        if request.HasField("new_value"):   # presence, NOT value != 0
            self._data[request.key] = request.new_value
            cur = request.new_value
        return pb2.UpdateResponse(value=cur)  # absent -> unchanged, key not created
```

General rule: **read the task's exact wording on edge cases** (missing key,
absent namespace, overwrite, delete-missing, empty aggregate) and encode each
one literally; graders test these branch points, not just happy paths.

## 4. Verification battery (write once per task, from the generated bindings)

**Use the shipped skeleton — do not hand-write battery boilerplate.**
`scripts/verify_battery.py` in this skill package (find it like the deploy
helper: `/skill/scripts/verify_battery.py` or `find / -name verify_battery.py`)
contains the full battery machinery done right and TESTED: real gRPC
handshake, import-safety (module import + servicer-subclass check),
concurrency burst with distinct per-thread keys, argparse/loading
boilerplate, and the tier-4 cleanup harness. You edit only its four marked
SLOT functions to the task's exact prose (`semantic_checks`,
`cleanup_keys`, `burst_worker`, `final_default_checks`); the shipped
content is the v01 semantics and doubles as a worked example:
```bash
cd <outdir> && PYTHONPATH=<outdir> python3 /skill/scripts/verify_battery.py \
    --port <PORT> --out <outdir> --module <prefix> --service <Service> \
    --prefix zzt_<task>
```
Hand-written batteries are the last hand-written failure surface: fresh
sessions have been observed failing them with a one-line syntax typo, and
— worse — the failed run's residue then contaminates the next run
("total is 1800, not 1600" was leftover keys from the failed run, not a
server bug). Encode these rules even if you cannot use the asset:

**Probe hygiene — the live server's state is a graded artifact, not a
workbench.** The grader observes the exact state your session leaves inside
the running process. v01 passed 6/6 with leftover probe namespaces resident
only because namespaces made the residue disjoint; on a FLAT variant (the
seed's shape) every probe write is directly in the grader's world, and
tests like "puts k1..k5 then lists all keys" or "Fetch('x') == 0 for a
missing x" fail on residue or collisions. Three rules:

1. **Never verify with generic identifiers.** No probe, battery, or helper
   may use names like `test`, `key`, `foo`, `default`, `1`, or the empty
   string/namespace. Use a collision-proof scheme with a per-task unique
   prefix, e.g. `zzt_<task_slug>_probe_<n>` — ugly enough that no grader
   key can collide, and stable enough to reuse across battery runs. Keep
   the prefix EXCLUSIVE to the battery: if a prefix was ever used with
   other keys (older battery versions, experiments), clean those once
   manually — pre-clean only knows the battery's own key universe.
2. **Leave a clean world (tier 4).** Any probe that writes must end its
   write/read cycle with Delete, then re-verify one default read as the
   FINAL battery step (e.g. Fetch a missing key -> spec default, empty
   aggregate -> 0). Deleting what you just wrote can never fail a correct
   implementation — Delete-missing returning its documented sentinel is
   itself part of the contract. Tier 4 therefore asserts: **the endpoint's
   observable state at shell-exit matches the task's described initial
   state** — the grader's first RPCs see exactly the world the task prose
   assumes exists.
3. **Make the battery idempotent.** Clean your keys BEFORE the run as well
   as AFTER (a crashed previous run must not poison this one), use distinct
   per-thread burst keys (`t{tid}_k{i}`), and never assume the store starts
   empty. If a run fails: fix the battery, then re-run — an unexpected
   aggregate value is usually YOUR residue, not a server bug; verify that
   hypothesis by listing/cleaning the namespace before touching the server
   code.
4. **Exercise both presence traps in every battery (mandatory patterns).**
   (a) If 0 is a legal stored value: `Put(k, 0)`, then run every
   conditional/presence RPC on k and assert the outcome that requires the
   key to EXIST (e.g. put-if-absent must fail on a stored 0; delete must
   succeed with `value=0`); also run the conditional on a fresh key with
   candidate value 0 (0 is a legal candidate). This single pair of tests
   separates presence reads from value reads. (b) If any request field is
   `optional`/`oneof`: call the RPC with the field ABSENT and with it = 0
   and assert the two outcomes differ per the prose (e.g. "update only if
   provided": absent -> unchanged and key not created; present 0 -> sets
   0). The shipped skeleton's SLOT-1 banner lists both patterns; a server
   that conflates presence with value fails exactly there (verified via a
   deliberately buggy server, see §7).

```python
# run with: cd /app && PYTHONPATH=/app python3 - <<'EOF' ... (or timeout 60)
import grpc
import kv_store_pb2, kv_store_pb2_grpc
stub = kv_store_pb2_grpc.KVStoreStub(grpc.insecure_channel("127.0.0.1:PORT"))
NS = "zzt_<task>_probe"        # collision-proof; NEVER 'test'/'key'/'foo'
# 1) every default/edge branch, 2) happy paths, 3) overwrite, 4) cross-namespace
# isolation (or flat-key isolation on non-namespaced variants), 5) delete
# existing + missing, 6) aggregates; then:
# 7) SAME checks from a SECOND fresh client process (state persistence),
# 8) concurrency burst (ThreadPool of clients doing N puts each; assert total),
# 9) import-safety: `cd /app && timeout 20 python3 - <<'EOF' ... import server;
#    s = server.Server()` — must not hang (use `timeout` so a blocked import
#    fails loudly); call handlers directly with constructed request messages
#    for unit-level checks, and finally
# 10) TIER 4 — self-clean (Delete every key/namespace the battery wrote) and
#    re-verify the default reads as the LAST assertions, then confirm the
#    server still answers (one more fresh-shell Fetch of a missing key).
```

## 5. Variation playbooks (spec-declared axes)

### 5.1 rpc_api_structure — richer protos
All of these are valid proto3 — copy the SHAPES, rename per task. The two
fields a grader cares about are names and numbers: both must match the task
exactly.
```proto
syntax = "proto3";
package kvstore;

enum Priority {                  // proto3 enums: FIRST MEMBER MUST BE VALUE 0
  PRIORITY_UNSPECIFIED = 0;
  LOW = 1;
  HIGH = 2;
}
message Meta { string owner = 1; Priority prio = 2; }   // nested message
message Entry { string key = 1; int64 value = 2; Meta meta = 3; }
message Item { string name = 1; repeated string tags = 2; }     // repeated
message Stats { map<string, int64> counts = 1; }                // map field
message GetManyRequest { repeated string keys = 1; }
message GetManyResponse { repeated Entry entries = 1; }
message UpdateRequest { string key = 1; optional int32 new_value = 2; }  // presence!
service KVStore {
  rpc GetMany(GetManyRequest) returns (GetManyResponse);
  rpc Ping(Empty) returns (Empty);            // empty message: message Empty {}
  rpc Watch(WatchRequest) returns (stream Event);   // server streaming
  rpc BatchPut(stream PutRequest) returns (BatchResponse);  // client streaming
}
```
Python-side mapping (generated module `pb2`):
- repeated -> Python `list`; build with `resp.entries.extend([...])` or
  construct entries then `resp.entries.append(e)`.
- nested -> message attribute; assign an instance: `e.meta = pb2.Meta(owner="x", prio=pb2.Priority.HIGH)`.
- enum -> `IntEnum` in the pb2 module; use `pb2.Priority.HIGH` (first member
  is the zero default, so a missing enum field reads as the first member).
- map -> Python `dict`; `pb2.Stats(counts={"a": 1})` or assign/set items.
- oneof -> `request.WhichOneof("group")` returns the set MEMBER NAME or
  `None`; setting one member clears the others. This is the only presence
  signal for the group — never try to infer the member from value equality.
- `optional` scalar -> presence contract on the request:
  `request.HasField("f")` / `ClearField("f")`; absent and 0 are
  distinguishable, and the default read is still 0 when unset.
- message-typed fields always have presence (`HasField` works);
  `repeated`/`map` only signal emptiness by length (`len(...) == 0`).
- stream RPCs: request-stream handler takes an *iterator*
  (`for req in request_iterator:`); response-stream handler **yields**
  responses instead of returning. Wire-up is identical
  (add_XServicer_to_server).
- `Empty` -> `message Empty {}`; construct `pb2.Empty()`.
- **More RPCs**: just more `rpc` lines + messages; servicer gets one handler
  per RPC; register once per service.
- **Multiple fields**: construct responses with keyword args
  (`pb2.Resp(a=..., b=...)`) or set attrs.
- **Nested messages**: field type is another message; assign an instance:
  `req.child = pb2.Child(x=1)` or build `pb2.Child(x=1)` inline.
- **Repeated fields**: Python lists; `req.keys.extend(["a","b"])` or assign a
  list. Return repeated via `resp.items.extend([...])`.
- **Enums**: generated as `IntEnum`; use `pb2.MyEnum.MEMBER`; proto3 requires
  a zero member; store/compare by name or value — both work.
- **Maps**: `map<string,int32>` -> dict attribute.
- **Naming variations**: whatever the proto file is named, module prefix
  follows it (`my-store.proto` -> `my_store_pb2.py`). If the task explicitly
  says "create `foo_pb2.py`", name the proto so that holds (`foo.proto`).
- **Unary-only in anchor; streaming RPCs (unlikely but possible)**: protoc
  and grpc.server support them with the same wiring. A request-stream handler
  takes a request *iterator*; a response-stream handler **yields** responses
  instead of returning. Verification: after generating, call the streaming
  stub method; assert the list of yielded messages.
- **Future verification procedure**: after protoc, run a client that (a)
  constructs one message of every type (nested/repeated/enum/map), (b) calls
  every stub method once, (c) asserts field-level round-trip equality.

### 5.2 stateful_service_semantics — richer behavior
Implement each semantic verbatim under the lock; deterministic means: same
call sequence => same observable state, regardless of channels or retries.
Multi-key ops must be atomic (one lock hold). Aggregate reads must reflect the
**current** state (compute, don't cache). Presence/absence defaults must match
the task. Verification: script the exact prose examples from the task as
assertions; run twice (two client processes) with identical outcomes.

### 5.3 runtime_interaction_requirements — staying healthy
- **Survives the agent shell**: `setsid nohup ... &` (or `nohup ... & disown`;
  the helper uses `start_new_session=True`). Always confirm via a *different*
  shell that (a) the process is alive
  (`ls /proc | grep '^[0-9]*$'` + scan `cmdline` — note `ps` may not exist in
  these containers), (b) the port is owned by that PID and answers a gRPC
  handshake (raw TCP connect confirms only *someone* listens).
- **Longer test windows / repeated channels**: stateless-on-the-wire server —
  each channel is independent; state lives in the servicer instance. Nothing
  extra needed beyond not exiting.
- **Bursts / concurrency**: `ThreadPoolExecutor(max_workers>=16)`; serialize
  state access with one `RLock`; avoid blocking work inside handlers.
- **Port ownership is the invariant — never trust names**: a stale server
  launched as `cd /app && exec python3 server.py`, `python3 -m server`, or a
  renamed entry file defeats any name-based killer, and a raw TCP connect
  proves only that *someone* accepts connections (a stale server passes it
  while your new server died with EADDRINUSE). Resolve port -> owning PID
  from facts: `/proc/net/tcp` and `/proc/net/tcp6` LISTEN rows (`0A` state;
  local address is IP-hex:PORT-hex, port is always the last `:HEX` group;
  inode is column index 9), mapped to PIDs via `/proc/<pid>/fd/*` readlinks
  of the form `socket:[<inode>]` (works where `ps`/`ss`/`lsof`/`fuser` are
  missing — those tools are not guaranteed in these containers). Kill
  whoever the port says owns it; **capture the launched PID** (a Python
  `subprocess.Popen(..., start_new_session=True)` launcher that prints
  `p.pid` — `setsid ... & $!` is also fine but less portable); assert
  `port_owner(port) == NEW_PID` and only then probe. A pass from a stale
  server is the failure mode, not a success.
- **Readiness is a tiered functional probe, ordered after the identity
  assert**: (1) real HTTP/2+gRPC handshake via
  `grpc.channel_ready_future(ch).result(timeout=...)` — distinguishes a gRPC
  endpoint from a bare TCP listener and catches half-dead servers;
  (2) one real RPC through the task's own generated stubs, preferring a
  side-effect-free read (e.g., Fetch a missing key expecting the spec's
  default) — wire it so deployment *fails* if the probe fails; the helper
  injects the out-dir onto `PYTHONPATH` (and uses it as cwd) for the probe,
  so probe scripts import the generated modules without manual env games;
  (3) grep `server.log` for `traceback|address already in use|EADDRINUSE`
  and exit 1 on a match (truncate the log per deployment so a previous
  failed run cannot poison the check). If the task defines a health-check
  RPC, implement it to return SERVING and use it as the tier-2 probe.
  `scripts/deploy_grpc_store.py` implements eviction + identity assert +
  all three tiers; verified by fault injection in the container (see §7).
  The full source is embedded in Appendix A — if the skill package is not
  mounted inside the container, recreate the file from there.
- **Grader in a separate shell**: the endpoint must be reachable as
  `127.0.0.1:PORT`/`localhost:PORT` from any process in the container — bind
  `0.0.0.0` (verified on anchor).

## 6. Failure modes & debugging quick reference

| Symptom | Cause / fix |
|---|---|
| `ModuleNotFoundError: kv_store_pb2` | generated files not on `sys.path`; put proto+pb2+server in one dir, run from there, or `PYTHONPATH=/app` |
| `ModuleNotFoundError` on a `*_pb2` module that actually exists | nested/package-qualified generation: the proto was NOT at the top level of `-I`, so protoc (exit 0!) emitted `<sub>/<name>_pb2.py` plus `import <sub>.<name>_pb2` in the grpc module. `-I` must be the proto's CONTAINING dir; check the `_pb2_grpc.py` import line is top-level and run an import smoke test (helper stage 0 does both) |
| Client import block / hang on `import server` | launch code outside `__main__` guard — move `serve()` call under `if __name__ == "__main__":` |
| `NotImplementedError` on RPC | servicer method name != RPC name (spelling/case) — copy verbatim |
| Port refused after launch | server crashed — read `server.log`; or wrong port — use task's exact port (helper: identity assert fails with log tail) |
| EADDRINUSE / wrong server answers | evict by **port ownership** (parse `/proc/net/tcp{6}` LISTEN inode -> `/proc/<pid>/fd` `socket:[inode]`), never by name; capture launched PID, assert it owns the port before probing (helper implements all of this) |
| Readiness says READY but endpoint is wrong | tiered probes, ordered after identity assert: gRPC handshake (`channel_ready_future`), one functional RPC via generated stubs (expect spec default), log grep for traceback/EADDRINUSE |
| Out-of-range int on response | `ValueError: Value out of range` is a **bug beacon**: your aggregation scope diverges from the reference (wrong namespace, missed delete/reset, wrong key set). Never clamp/saturate/downcast; fix the scope |
| Burst loses writes / wrong aggregates | missing lock or too few workers; use `RLock` + `max_workers>=16` |
| Unexpected aggregate in your own battery (e.g. total 1800 vs 1600) | almost always YOUR residue from a failed earlier run, not a server bug: clean the battery's namespaces/keys, re-run, and only touch server code if a clean run still fails; battery is idempotent (pre/post cleanup) by design |
| Server dead when tests run | launch wasn't detached; use `setsid nohup ... &` and verify from a fresh shell |
| `grpc` import fails / old version | install exact pins `grpcio==X grpcio-tools==X` with system `pip` |

## 7. Evidence ledger (honesty about what was verified)

- **Directly verified on v01** (anchor, Python 3.13.1, grpcio 1.73.0):
  pip install of pins; protoc generation of both files; hyphen->underscore
  module naming; all four RPC semantics incl. every edge branch (missing
  fetch=0, delete-missing success=false/value=0, empty-namespace total=0,
  overwrite); namespace isolation; state persistence across a fresh process
  and channel; 800-put concurrent burst with exact total; import-safety of
  server.py (`import server` + direct `Server()` instantiation); detached
  process survival across many separate shells; `ps` absent -> `/proc` scan.
- **Teacher-taught (lesson 1-1, port ownership & evidence quality)**: name
  matching cannot control a port — resolve owner via `/proc/net/tcp{6}`
  LISTEN inode (`0A` state; port is the last `:HEX` group — this is a
  freeform extension of the taught IPv4 needle table that also covers IPv6
  and v4-mapped addresses) mapped through `/proc/<pid>/fd` `socket:[inode]`
  readlinks; capture the launched PID via a `start_new_session=True` Python
  launcher; assert identity before probing; tiered readiness (gRPC handshake
  -> functional stub RPC -> log assertion) so "READY" means "the process I
  launched owns this port and answered my RPC"; `ValueError: Value out of
  range` on aggregates is a bug beacon, never an excuse to clamp.
- **Fault-injection verified on the helper (direct container evidence)**:
  (a) a stale server launched as `cd /app && exec python3 server.py`
  (relative path, defeats name matching) was evicted by ownership and the
  identity assert confirmed the new PID owned the port; (b) a plain TCP
  listener passed the identity assert but FAILED the gRPC-handshake tier
  (exit 1) — a raw connect would have printed READY; (c) a server raising at
  import failed the identity assert with the traceback tail (exit 1);
  (d) per-deployment log truncation was added after a failed run's traceback
  was observed poisoning the next run's log assertion.
- **Teacher-taught (lesson 2-2, the other two silent contracts)**:
  (1) *protoc's `-I` decides the module name, not the file location* —
  generated file path and Python module name derive from the proto's path
  relative to `-I`, directories preserved; the contract is that the proto
  sits at the TOP LEVEL of `-I` (its containing dir), so outputs are flat
  and named from the basename (`-`/`.` -> `_`; `kv-store.proto` and
  `kv.store.proto` collide on `kv_store_pb2`); a wrong `-I` fails silently
  (protoc exit 0, nested files, package-qualified import, grader
  `ModuleNotFoundError`). Assert, don't trust: import-line check + import
  smoke test.  (2) *The live server's state is a graded artifact*: the seed
  is a FLAT store; namespaces are v01's elaboration — on flat variants
  probe writes live in the grader's world. Never verify with generic
  identifiers (`test`/`key`/`foo`/`1`/empty); use `zzt_<task>_probe_<n>`;
  probes that write must self-clean with Delete (Delete-missing returning
  its sentinel is contract, so cleaning can never fail a correct
  implementation) and end with a default-read re-verification = **tier 4: at
  shell-exit, the endpoint's observable state matches the task's initial
  state**.
- **Iteration-2 fault injections for the two contracts (direct container
  evidence)**: (a) split-directory layout — proto at `OUT/protos/x.proto`
  with old-style `-I OUT` generated nested `OUT/protos/x_pb2*.py` with
  `import protos.x_pb2` while protoc exited 0; the helper's
  `check_generated_layout` rejected it (nested-file branch) and also
  rejected a hand-built flat file with a package-qualified import
  (content branch); new-style `-I dirname(proto)` produced flat top-level
  modules, check passed, import smoke OK; (b) full v01 deploy: stage 0
  contract check + smoke import green, and a hygienic battery (zzt_
  identifiers, self-cleaning, final default reads) ended with the store
  back in its initial state (tier-4 clean); (c) unchanged stages re-verified
  (tier-1 rejects plain TCP listener; identity assert catches
  crash-at-import; probe runs without PYTHONPATH).
- **Iteration-1 evaluation evidence (direct, from the eval trajectory)**:
  the fresh solver reproduced the skill's procedure end-to-end and passed
  6/6 hidden tests. Two frictions surfaced: (a) the eval container had no
  host workspace path and the solver never checked for a `/skill` mount, so
  it re-typed the entire 254-line bash helper by hand (token-expensive,
  transcription-fragile); (b) the tier-2 probe command failed until the
  solver added `PYTHONPATH=/app` — `cd <dir> && python3 <path>/probe.py`
  does NOT put `<dir>` on `sys.path` (script dir is, cwd is not, for
  path-invoked scripts), and the old helper ran the probe without injecting
  the out-dir. Fixed in iteration 2: the helper is now a compact
  single-file Python script (`scripts/deploy_grpc_store.py`, ~230 lines,
  no nested-heredoc quoting traps), its full source is embedded in
  Appendix A so it is usable even when the package mount is unreachable,
  SKILL.md now tells the solver where to look (`/skill` first, then `find`),
  and tier 2 injects the out-dir into `PYTHONPATH` + cwd for the probe.
- **Iteration-2 fault injections (direct container evidence, new helper)**:
  (a) a stale relative-exec server AND a previously deployed server were
  bound to the same port simultaneously — both were evicted by ownership
  and the identity assert confirmed the new PID alone owned the port;
  (b) a plain TCP listener passed identity but failed the gRPC-handshake
  tier (exit 1); (c) a crash-at-import server failed identity with the
  traceback tail (exit 1); (d) a probe command with NO PYTHONPATH succeeded
  via the helper's injection (the exact eval friction); (e) per-deployment
  log truncation verified. Full v01 deploy + semantic battery green.
- **Iteration-2 evaluation evidence (direct, from the eval trajectory)**:
  6/6 hidden tests passed with near-perfect skill transfer — `/skill` found
  on the first attempt, `scripts/deploy_grpc_store.py` executed directly
  from the package mount, hygienic `zzt_*` identifiers used throughout,
  the helper's tier-2 probe passed without manual PYTHONPATH, and tier-4
  cleanup + final default-read checks were performed in fresh shells. The
  single recurring failure surface was the solver's HAND-WRITTEN battery:
  a one-line syntax typo (`stub.Delete(...) for i in range(200)` — a
  comprehension used as a statement) killed run 1, and the failed run's
  residue then contaminated run 2's aggregate assert (1800 vs 1600; the
  solver diagnosed its own leftovers correctly, but a weaker model could
  have 'fixed' a correct server). Iteration-3 response: ship
  `scripts/verify_battery.py` — an idempotent battery skeleton owning all
  generic machinery (handshake, import-safety incl. the
  servicer-subclass check, threading with distinct per-thread keys,
  pre/post cleanup, tier-4 slot), with only four marked semantic slots
  (v01 defaults doubling as the worked example) — plus §4 rules: clean
  BEFORE and AFTER, keep the prefix exclusive, and treat an unexpected
  aggregate as YOUR residue until proven otherwise.
- **Iteration-3 battery validation (direct container evidence)**: the
  shipped `verify_battery.py` (a) passed a fresh full run, (b) passed a
  second identical run (idempotency: zero residue), (c) passed over a
  simulated crashed-run residue consisting of its own key universe
  (pre-clean removed the battery's a/x/z/b* keys before semantic checks;
  tier-4 final totals zero), and (d) correctly FAILED loudly on foreign
  keys under its prefix (keys no battery run ever writes, added by an
  external probe) — confirming the prefix-exclusivity rule rather than
  masking it.
- **Synthetic in-family variant vS1 ("trap variant") — directly verified
  (not v01)**: authored in-container: FLAT (non-namespaced) store, service
  `TrapStore` (8 RPCs), `optional int32 new_value` on Update, presence-
  conditional SetIfAbsent, nested `Entry{key,value,Meta}` with enum
  `Priority` + `repeated tags`, AttachMeta/GetMeta/ListAll. Deployed via
  the helper (`--module trap_store --service TrapStore --port 5338`)
  with the module-layout contract verified. The battery (slots filled with
  zero-key + HasField cases) passed: (a) fresh run, (b) idempotent re-run,
  (c) run over crashed-run residue (pre-clean removed all 10 injected
  entries incl. stale meta; tier-4 `ListAll` empty). Adversarial proof:
  a deliberately buggy server conflating presence with value (stored 0
  treated as absent in SetIfAbsent; `new_value != 0` instead of HasField)
  FAILED the battery at exactly the stored-0 conditional assert — the trap
  tests have teeth. This flips the following §7/§5 items from extrapolation
  to directly exercised: optional-field presence (HasField), presence-read
  conditionals with stored zero, nested/repeated/enum message handling,
  naming variation (different file/module/service/port), flat-store hygiene.
- **Reasoned extrapolation** (still not locally exercised): map fields,
  oneof groups (WhichOneof), streaming RPCs, multi-key batch ops,
  increment/CAS at scale, health-check RPCs — each
  with a concrete mechanism (§5) and a future verification procedure: use
  the vS1 recipe (author a small variant, run helper + battery, inject a
  buggy server to prove the test distinguishes). Lock-based atomicity and
  ownership-based eviction are the load-bearing generalizations.

## Appendix A — deploy_grpc_store.py (canonical helper, full source)

This is the exact content of `scripts/deploy_grpc_store.py`. If the skill
package is not mounted inside the container, recreate the file from this
block (`cat > /tmp/deploy_grpc_store.py <<'PYEOF' ... PYEOF`) and run
`python3 /tmp/deploy_grpc_store.py ...`. It is deliberately small: one
language, no nested heredocs, no quoting traps, re-typeable without errors.

The block below is byte-for-byte the shipped script, so extracting it yields
the tested artifact.

```python
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
```