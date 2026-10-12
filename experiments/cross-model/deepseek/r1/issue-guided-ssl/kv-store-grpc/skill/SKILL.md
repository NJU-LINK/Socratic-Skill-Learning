---
name: kv-store-grpc
description: Build a real Python gRPC stateful service end to end — author the .proto schema, generate Python bindings with grpc_tools.protoc, implement a stateful servicer over in-memory data, and launch it as a long-lived detached endpoint with application-level readiness probing and semantic smoke verification. Covers proto→codegen naming derivation, field-type mapping, stateful semantics (namespaces, overwrite, deletion, aggregates), and gRPC server lifecycle pitfalls.
---

# kv-store-grpc: end-to-end Python gRPC stateful service

## When to use

Trigger conditions (any task that combines these):

- A `.proto` schema must be authored with a named gRPC **service** and unary RPCs
  (possibly many methods, multi-field/nested/repeated/enum messages).
- Python bindings must be **generated** (`*_pb2.py`, `*_pb2_grpc.py`) and imported.
- A **stateful** in-memory server must preserve data across RPC calls and client
  channels (namespaces, deletes, conditional updates, aggregates, multi-key ops).
- The real server must be **left running** as an endpoint (tests arrive in a later
  shell), so lifecycle and readiness matter.

## The invariant pipeline: four human-authored layers

```
schema (.proto)  →  codegen (grpc_tools.protoc, generated)  →  semantics (servicer)  →  lifecycle (launch)
     axis rpc_api_structure                  —                      axis stateful_service_semantics    axis runtime_interaction_requirements
```

The middle is **generated**; never hand-write or edit `*_pb2*.py`. A variant is a
**slot refill in one layer**, never a rewrite: axis 1 → only the schema layer,
axis 2 → only the semantics layer, axis 3 → only the lifecycle layer.

## Step 1 — Schema layer (axis: rpc_api_structure)

Write `service.proto` with `syntax = "proto3";`. Field types follow the mapping
table in `references/proto_field_map.md` (string/int32/int64/bool/enum/repeated/
map/nested message → proto syntax). See `templates/service.proto.tmpl` for a
concrete fill with slot markers.

The templates are the v01 fill wrapped in slot markers. **Instantiate with
`scripts/materialize.sh <out_dir>`** — it strips the SLOT fill-guide header
and every inline SLOT annotation deterministically, writing
`<out_dir>/kv-store.proto` and `<out_dir>/server.py`. Do NOT hand-strip
template markers: the iteration-2 fresh-solver trajectory showed manual
stripping is error-prone (an `awk` cut silently dropped the
`syntax = "proto3";` line).

**Topology rule: the frozen package tree (e.g. `/skill`) is read-only —
never edit templates in place.** The variant recipe is the executable ramp:
copy `service.proto.tmpl` + `server.py.tmpl` into a scratch dir you can
write, refill the SLOT-marked lines IN THE COPIES (service name, RPC list,
message fields per `references/proto_field_map.md`, generated-module names
per the derivation rule, port, handler semantics per step 3), then run
`materialize.sh <out_dir> <scratch_tmpl_dir>` (equivalently
`KV_TMPL_DIR=<scratch_tmpl_dir> materialize.sh <out_dir>`). With explicit
template sources the script checks only structural family invariants
(syntax + ≥1 service + ≥1 rpc; `class` + `add_<X>Servicer_to_server` +
`ThreadPoolExecutor` + `wait_for_termination`); with the default frozen
sources it asserts the COMPLETE v01 fill (all four RPC lines). If the task
requires different output file names than the materialized
`kv-store.proto`/`server.py`, rename them and re-derive the module names per
the derivation rule. v01's exact messages/fields are the fill shown in the
template — they are the seed's concrete form, not the family shape.

Rules that matter:

- RPC line syntax: `rpc Method(RequestType) returns (ResponseType);` inside
  `service <Name> { ... }`.
- Every request/response message must be defined at file scope (or imported);
  proto3 fields are implicitly present and default-initialized.
- Keep field numbers stable; the wire format and generated code depend on them.

## Step 2 — Generation layer (invariant)

One command, from the directory containing the proto:

```bash
cd /app && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. kv-store.proto
```

**Filename-derivation rule** (encode this, not the seed's specific answer):
the Python module name = proto base name with every non-identifier character
replaced by `_`, plus `_pb2` / `_pb2_grpc`.
`kv-store.proto` → `kv_store_pb2.py` + `kv_store_pb2_grpc.py`.
Never write `from kv-store import ...` — hyphen is a syntax error.

**Generated-name rules** (both derive from the *service* name in the proto):
- servicer base class: `<ServiceName>Servicer`
- registrar: `add_<ServiceName>Servicer_to_server`
- client stub: `<ServiceName>Stub`

Escape hatch for unknown schemas (introspection, not needed for normal builds):
`kv_store_pb2.DESCRIPTOR.services_by_name['KVStore'].methods_by_name['Put']`.

Notes: recent grpc_tools versions may print a deprecation notice from the
entry point; it still emits the files. If it ever hard-fails, the same `-I/
--python_out/--grpc_python_out` flags work on the bundled `protoc` binary
(`python3 -m grpc_tools.protoc --help`). Script: `scripts/protoc_gen.sh`.

## Step 3 — Semantics layer (axis: stateful_service_semantics)

Implement the servicer as a class extending `<ServiceName>Servicer` over shared
state. v01's concrete semantics, generalized as a **leaf-operation table** —
a new semantic variant is a new table row, not a redesign:

| RPC | Operation | Return convention |
|---|---|---|
| Put | write `value` at `(namespace, key)`, overwriting | return the written value |
| Fetch | read `(namespace, key)` | missing key → default (0) |
| Delete | remove `(namespace, key)` | removed value with `success=true`; missing → `success=false, value=0` |
| ListNamespaceTotal | sum values in one namespace only | absent/empty namespace → 0 |

State notes:

- Namespace isolation = outer dict keyed by namespace, inner dict keyed by key.
- State lives in the servicer instance and persists across calls AND across
  client channels — do not reset anything per request or per channel.
- **Locking rule**: `grpc.server(ThreadPoolExecutor)` serves handlers
  *concurrently*. Any RPC that composes multiple dict operations
  (delete-and-check, conditional update, multi-key, aggregate) must hold a
  `threading.Lock`. Always taking the lock is harmless and is the safe default.
- **Scope boundary**: protobuf `int32` rejects out-of-range values at
  serialization time (ValueError on response construction). Aggregates/totals
  are bounded by 2^31−1 in this family. Verify handlers cannot craft bigger
  int32 responses (e.g., watch accumulation, use 64-bit fields for unbounded
  counters).

Template: `templates/server.py.tmpl` (materialize with `scripts/materialize.sh`;
see step 1). Each handler is one method named exactly like the RPC; `context`
parameter is required by the dispatching signature.

## Step 4 — Lifecycle layer (axis: runtime_interaction_requirements)

Three silent-failure guards, ordered by how commonly they kill correct code:

1. **`grpc.server()` requires a thread pool.**
   `grpc.server(futures.ThreadPoolExecutor(max_workers=16))` — calling it bare
   raises. Size ≥ 16 for cheap headroom against bursts of concurrent calls.
2. **After `start()`, you MUST block: `server.wait_for_termination()`.**
   gRPC's C-core threads do not keep the Python process alive; without this,
   `python3 server.py` exits immediately after `start()` and the port dies.
   This is the classic "correct implementation, dead endpoint" failure.
3. **Launch detached; prove the endpoint SERVES, not just listens.**
   Tests run in a shell that survives after yours is gone
   (`run_tests_in_same_shell: false`), so the server must outlive your shell:

   ```bash
   nohup python3 /app/server.py > /tmp/kvserver.log 2>&1 &
   ```

   Never rely on `ps`/process listing (may be unavailable in the container),
   and never kill by a NAME proxy — regex/glob over `/proc/*/cmdline` text or
   a basename sweep — by default: the property the launch actually needs is
   exactly one thing, "this process owns the LISTEN socket on :myport". The
   default reclamation is therefore port-owner-only: resolve the LISTEN inode
   for `:<port>` from `/proc/net/tcp` AND `/proc/net/tcp6` (state `0A`, hex
   port; gRPC's dual-stack listener appears only in tcp6 — observed
   in-container) → owning PID via `ls -l /proc/<pid>/fd | grep socket:[inode]`.
   If procfs hides the tables, fall back to a TCP-connect busy-check. A
   basename sweep (`KV_CLEAN_BY_NAME=1`) is opt-in only, and even then is
   conservative: it matches only plain `python3 <path>` / `python3 <path>
   <arg>` invocations (≤3 argv tokens, path must exist as a file —
   interpreter wrappers whose argv merely contains the basename text are
   never matched) and skips any PID that owns a LISTEN port other than the
   target. Kill the owner,
   then **verify-and-wait** until the port actually leaves LISTEN (SIGTERM,
   escalate SIGKILL on a stubborn owner) before relaunching; after relaunch
   verify `kill -0 $newpid` AND that the new PID owns the LISTEN socket, and
   fail loudly if the log shows `address already in use`.

   **Readiness oracle = a real probe RPC succeeding.**
   `grpc.channel_ready_future` reaching READY proves only the transport
   (HTTP/2 handshake) — a server can be READY yet answer every RPC with
   `UNIMPLEMENTED` (missing/typo'd `add_<Service>Servicer_to_server` or a
   handler-name mismatch), or be READY while a slow background state load is
   still in flight. So the launch script treats channel READY as a fast-fail
   precondition and then loops a benign unary call until it succeeds or the
   deadline expires. **Probes are read-only by default and the script
   ENFORCES it, not merely documents it**: auto mode only ever calls
   case-folded benign-prefixed unary methods
   (Fetch/Get/List/Read/Query/Peek/Count/Has/Exists — any case, so `rpc
   fetch` is auto-selected); if no such method exists in any generated
   module, the script FATALs with 'pass probe_rpc' BEFORE any RPC fires —
   there is no mutator fallback, ever. Probe rules:
   (1) build every request via `method.input_type._concrete_class()` — works
   for top-level AND nested message definitions (`getattr(pb2, msg_name)`
   breaks when the request message is nested, e.g. `message Wrapper {
   message PutRequest {...} }`, because a nested descriptor's name is not a
   module attribute); (2) explicit `probe_rpc` matches the declared RPC name
   exactly and is FATAL-if-absent (no service declares it) — but a
   per-candidate UNIMPLEMENTED is always tolerated, exactly as in auto mode:
   naming a probe narrows SELECTION, never terminates earlier; (3) EVERY
   service in EVERY generated module is swept — a multi-service proto that
   registers only one servicer still passes (UNIMPLEMENTED on one service
   moves to the next; the round verdict is global, so a server with no
   servicer at all still fast-fails in ~1s); (4) the module scan defaults to
   the server's directory — if bindings live elsewhere (out-of-dir codegen),
   set `KV_PROBE_DIRS=<colon-separated dirs>`. Honest caveat: a benign
   *name* can still side-effect if the variant's semantics are get-or-create
   (a `Get` that populates) — for such variants use a designated safe read
   (e.g. `Peek`) or an explicit `probe_rpc`. `endpoint ready` is printed
   only after a probe RPC returns. Script: `scripts/launch_and_probe.sh`.

## Verification (part of the Skill, not an afterthought)

`scripts/smoke_test.py` runs against the live endpooint over a **fresh channel**
and asserts every semantic branch: missing-key default, put-returns-written,
overwrite, namespace isolation, namespace-scoped totals, delete present
(`success=true` + removed value), delete absent (`success=false, value=0`).
Always add persistence-across-channels coverage: plant a value in one script
run, fetch it from a second fresh channel. The smoke-test assertions are the
final readiness oracle; the launch script's probe RPC only gates "the endpoint
serves at all".

**Import contract**: `server.py` and the client both import the generated
modules. Run both from the proto/codegen directory (cwd) or insert the directory
into `sys.path` explicitly in the client; a variant that renames the generated
files changes this contract.

## Local-edit property (variant → layer map)

| Spec axis | Layer to edit | What changes |
|---|---|---|
| rpc_api_structure | schema (`*.proto`) + rerun codegen | service/method names, message fields, types, nesting |
| stateful_service_semantics | semantics (`server.py` handlers) | leaf-operation table rows, extra state collections, defaults |
| runtime_interaction_requirements | lifecycle (launch/probe) | port, pool size, readiness policy, connection patterns |

## Evidence log (honesty about what was verified)

- **Variant instantiation ramp executed for the first time (iteration-3,
  lesson issue-3)**: `/skill` confirmed read-only (EROFS on touch) — the
  frozen-tree topology is real. Variant templates (`service KVStoreExtra`,
  fifth RPC `SumAll(SumAllRequest) returns (SumAllResponse)` with
  `int64 total = 1`, class/registrar and PORT refilled) were copied into a
  scratch dir and instantiated via `materialize.sh <out> <scratch>`: output
  had zero SLOT markers and passed the STRUCTURAL family assertions even
  though it contains none of the v01 needles (`service KVStore`,
  `add_KVStoreServicer_to_server`, …); the whole pipeline ran —
  protoc_gen.sh, launch_and_probe.sh auto-selected across the variant schema
  ('endpoint ready (probe KVStoreExtra.Fetch ok)'), and a direct client
  confirmed variant semantics (SumAll across namespaces = 3 with namespace
  isolation intact). Default v01 path is unchanged: materialize.sh with no
  explicit sources still asserts the COMPLETE seed (all four RPC lines, 4/4
  counted) and resolves sources to /skill/templates; the KV_TMPL_DIR env
  form was also verified. Honest calibration: both fresh solver evaluations
  (iterations 1 and 2) exercised v01 ONLY — this is the first execution of
  the variant path through the instantiation asset.
- **Identity-rule reaffirmation (self-inflicted incident, iteration-3)**: an
  ad-hoc cleanup loop `case "$cmdline" in */tmp/var_out/server.py*)` matched
  the task harness's python wrapper (argv0 python, command text contains the
  path) and SIGTERMed the enclosing shell (exit 143) — the same error class
  as the iteration-1 sweep bug. This is why the skill's opt-in sweep is
  restricted to plain `python3 <path>` invocations (≤3 argv tokens, real
  file) and the default reclamation is port-owner-only: substring cmdline
  matches are never identity.
- **Template instantiation made deterministic (iteration-3)**: the
  iteration-2 fresh-solver trajectory (6/6 hidden tests, single attempt) was
  green but exposed a friction: the solver burned 3 tool calls stripping the
  templates' SLOT header markers — its first `awk '/^service KVStore/…'` cut
  silently dropped the `syntax = "proto3";` line (an invalid proto), the sed
  attempt mangled blank lines, and it ended hand-writing a python cleaner.
  The package now ships `scripts/materialize.sh <out_dir>`, which strips the
  SLOT fill-guide header and every inline SLOT annotation deterministically
  (asserting the materialized proto still contains the syntax/service/RPC
  essentials). Directly verified in-container: one command produced
  artifact-free `/app/kv-store.proto` + `/app/server.py` (zero SLOT markers,
  syntax preserved, no dangling annotation continuations after the template's
  wait_for_termination annotation was made SLOT-tagged on both lines), and
  the one-line flow `materialize.sh → protoc_gen.sh → py_compile` plus
  launch_and_probe + smoke stayed green, including a reclaim/relaunch over a
  live server.
- **Observation-only probe policy (directly verified, iteration-2 lesson
  issue-2)**: probes are read-only by default and the script ENFORCES it.
  (a) mutator-only schema (`rpc Store`/`Touch`; the server writes a marker
  file on every handler call): the default run FATALed 'no benign read-like
  unary method ... pass probe_rpc explicitly' BEFORE any RPC fired (marker
  files absent; launched pid stopped), and an explicit `probe_rpc=Store` run
  succeeded — 'endpoint ready (probe Svc.Store ok)' — with the write marker
  appearing only then; (b) lowercase `rpc fetch(FetchRequest)` (legal proto;
  the generated stub method is `fetch`) was auto-selected — 'endpoint ready
  (probe Svc.fetch ok)' — via case-folded benign matching; (c) a two-service
  proto with `probe_rpc=Fetch` where only the SECOND service registers
  `Fetch` swept past the first service's UNIMPLEMENTED — 'endpoint ready
  (probe Beta.Fetch ok)' — while a bare unwired server with the same
  explicit probe still fast-failed in ~1s (per-candidate UNIMPLEMENTED is
  always tolerated; the round verdict is global).
- **Fresh-solver evaluation of the frozen skill (iteration-1, corroborating
  evidence)**: a separate model instance solved a freshly reset v01 using
  ONLY the skill snapshot — 6/6 hidden tests passed on the first attempt
  (22 tool calls, no errors); it used the assets verbatim (template copies,
  protoc_gen.sh, launch_and_probe.sh → 'endpoint ready (probe KVStore.Fetch
  ok)', smoke_test.py twice, cross-process persistence, tcp6 inode port-owner
  verification) and reported a clean server log. Nothing in that trajectory
  contradicted the package; nothing was reopened.
- **Probe service sweep (directly verified, iteration-2)**: a proto with TWO
  services (`Alpha` with benign `Ping`, `Beta` with benign `Fetch`) where the
  server registers ONLY `Beta`: the old probe would have FATAL'd on
  `Alpha.Ping` → UNIMPLEMENTED; the new probe swept to `Beta.Fetch` and
  reported 'endpoint ready (probe Beta.Fetch ok)', and a direct client
  confirmed both `Beta.Store`/`Beta.Fetch` work. Fast-fail preserved: a bare
  `grpc.server` with NO servicer still exits FATAL in ~1s (all candidates
  UNIMPLEMENTED → immediate), not after the readiness deadline.
- **KV_PROBE_DIRS + kill-on-probe-failure (directly verified, iteration-2)**: a
  variant with proto+server in one dir and generated bindings in a separate
  out dir failed loudly without `KV_PROBE_DIRS` ('FATAL: no *_pb2_grpc.py
  modules found in <server_dir>', launched pid stopped) and succeeded with
  `KV_PROBE_DIRS=<gen dir>`; the probe used the out-dir modules and a direct
  client verified the variant. On any probe FATAL the just-launched PID is
  killed before exit, so a failed launch never leaves a listening-but-broken
  server behind to masquerade as ready.
- **Directly verified on v01** (this environment): grpcio/grpcio-tools 1.73.0
  install on Python 3.13.1; `kv-store.proto` → `kv_store_pb2(.py)` +
  `kv_store_pb2_grpc.py` via the entry-point command; servicer with the four
  RPCs passes an all-branch smoke test against a live detached server on port
  5328; state persists across fresh client channels; `wait_for_termination`
  keeps the process alive (dead without it is Teacher-taught gRPC-C-core
  behavior, consistent with observed process behavior).
- **Directly verified on the lifecycle fix**: two consecutive
  `launch_and_probe.sh` runs with a live absolute-path server
  (`python3 /app/server.py`): each run logged the killed stale PID (401, 574
  — argv token `/app/server.py` matched by per-token basename identity), the
  new PID was verified alive (`kill -0`) and the owner of the LISTEN socket on
  :5328, and smoke stayed green. Also verified the oracle distinguishes
  transport from serving: a bare `grpc.server` on the port with NO servicer
  registered reaches channel READY but the probe RPC fails with
  `UNIMPLEMENTED` and the script exits FATAL.
- **Empirically discovered mechanism (this environment)**: `grpc.server` +
  `add_insecure_port("0.0.0.0:<port>")` creates an IPv6 dual-stack LISTEN
  socket that appears in `/proc/net/tcp6` only — `/proc/net/tcp` is empty for
  it. The port-owner primitive must scan both tables (verified live: new PID
  matched the tcp6 socket inode); a connect-based busy-check covers sandboxes
  that hide `/proc/net/tcp*` entirely.
- **Nested-message probe (directly verified)**: a variant schema with
  `message Wrapper { message ReadRequest {...} ... }` and
  `rpc Read(Wrapper.ReadRequest)` generated bindings via protoc_gen.sh;
  `getattr(pb2, 'ReadRequest')` raises AttributeError (nested descriptor
  names are not module attributes) while `method.input_type._concrete_class()`
  constructs the request; a full launch_and_probe.sh run against that variant
  auto-selected the benign `Read` method over the mutator `Write`, probed
  through the nested request — 'endpoint ready (probe NestedSvc.Read ok)' —
  and a direct client call returned the expected value.
- **Calibration against the Teacher lesson (corrected mechanism, Teacher's
  false-negative claim retracted)**: measurement showed the glob
  `*/server.py *` DOES match the argv token `/app/server.py` (the string
  contains the substring `/server.py`; every absolute-path token ends with
  `/<basename>`), so the original pattern covered the documented
  absolute-path case. The old pattern's real defect was SCOPE, not false
  negatives: it matched `.../server.py` in every directory on the machine and
  checked nothing about port ownership. The interim fix (unconditional
  same-basename sweep in launch_and_probe.sh) mirrored that defect
  destructively — it would kill an unrelated `python3 /data/server.py` — and
  was corrected: default reclamation is port-owner-only (inode resolution),
  the basename sweep is opt-in (`KV_CLEAN_BY_NAME=1`) and skips PIDs owning
  other LISTEN ports. Demonstrated in-container: an unrelated
  `python3 /tmp/other/server.py` LISTENing on :6000 survived a default
  reclaim of the :5328 owner, and is also spared by the opt-in sweep.
- **Teacher-taught / domain knowledge**: thread-pool requirement of
  `grpc.server`, C-core thread daemonization semantics, int32 serialization
  bounds, proto3 implicit defaults, channel-READY-vs-servicing distinction.
- **Reasoned extrapolation (not locally exercised)**: behavior for enums,
  repeated/map/nested fields, streaming RPCs, and multi-key/conditional
  semantics follows from the mapping table and locking rule but was not
  exercised on v01; verify each variant by extending the smoke test with the
  variant's leaf-operation rows before trusting it.