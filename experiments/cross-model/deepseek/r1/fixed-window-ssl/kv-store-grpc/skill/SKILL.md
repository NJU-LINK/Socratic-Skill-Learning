---
name: kv-store-grpc
description: >
  Build and hand over a real Python gRPC stateful key-value store: author the
  proto file from a service/message spec, generate protobuf + gRPC bindings,
  implement a thread-safe in-memory servicer with the specified per-RPC
  semantics, launch it detached on the required port, and verify the full
  semantics table through the generated stubs before leaving exactly one live
  server process running for the grader.
---

# kv-store-grpc

## When to use

A task that asks you to build a *real, running* Python gRPC service in a fixed
work directory (e.g. `/app`): write `<name>.proto`, generate `<name>_pb2.py`
and `<name>_pb2_grpc.py`, implement a servicer class, and LEAVE THE SERVER
RUNNING so a separate grader process can call it. Typical shape (v01):
"Build a real Python gRPC namespaced integer store … leave the real gRPC
server running", pytest parser, tests run in a fresh shell
(`run_tests_in_same_shell: false`), so nothing survives except files and OS
processes.

## Family invariants (grounded by v01, expected in every variant)

- Concrete artifacts in the task workdir: `*.proto`, generated
  `<proto_filename_normalized>_pb2.py` + `_pb2_grpc.py`, and a `server.py`
  exposing a class with the exact name the spec gives (v01: `Server`).
- The generated **_pb2 module name derives from the proto FILENAME** after
  dash/underscore normalization (`kv-store.proto` → `kv_store_pb2`), **never
  from the `package` line**. The package line only affects fully-qualified
  service paths inside generated code; top-level message classes stay
  importable from the module root (`kv_store_pb2.PutRequest`). [v01 direct +
  teacher-taught; generalizes to rpc_api_structure variants]
- Unary RPCs with deterministic in-memory semantics; state persists across
  calls AND across client channels for the process lifetime.
- A single long-lived process serving an insecure gRPC endpoint on a fixed
  TCP port; the grader arrives after you finish, via a fresh shell, and
  connects to that port.
- Exact package versions are pinned by the task (`grpcio==1.73.0`,
  `grpcio-tools==1.73.0`); "system-wide" = `pip install` as root in the
  container works. v01 ran on Python 3.13.1; pip also pulled protobuf 6.33.6
  which worked fine with generated code. [v01 direct]

## Spec-declared variation (spec.yaml axes)

| Axis | v01 seed | May vary to |
|---|---|---|
| `rpc_api_structure` | 1 service, 4 unary RPCs, flat string/int32 fields | more methods; multi-field requests/responses; nested or repeated message fields; enums; naming variations. Invariant: generated bindings and servicer wiring must match the spec exactly. |
| `stateful_service_semantics` | flat dict namespace→{key:int}, overwrite-on-set, fetch-missing→0, delete, per-namespace sum | larger key spaces; multiple collections/namespaces; deletes/resets/conditional updates; aggregate or multi-key reads. Invariant: deterministic behavior, state preserved over the session. |
| `runtime_interaction_requirements` | one insecure server, short unary sequence, light load | longer test windows; bursts of concurrent/near-simultaneous calls; startup delays/readiness checks; repeated channel creation by clients. Invariant: one real endpoint that stays healthy and responsive throughout. |

The semantics you must implement are ALWAYS stated in the task text; extract
an exact semantics table (every RPC: inputs → observable outputs, including
missing-key and empty-collection cases) before writing any code. Namespaces
are isolated; "empty" and "absent" are observably identical (`0`,
`success=false`).

## Procedure (verified end-to-end on v01, iterated twice)

### 0. Skill assets inside the container (cheap, saves a big heredoc)

The skill package is mounted READ-ONLY at `/skill` inside the task container
(SKILL.md + scripts/). Copy assets from there directly: `cp /skill/scripts/gate.py
/app/`. Host workspace paths (the ones the `read` tool prints) are NOT visible
inside the container — `cp` from them fails with `cannot stat`; never do that.
[direct: iteration-2 cp from /skill worked; iteration-1 fresh solver's
cp-from-host-path failed and forced a ~2.3k-token re-emission of both scripts]
If `/skill` is absent, recreate the asset via heredoc from its contents.

Container state does NOT persist across iterations: everything pip-installed
in a previous iteration (pyyaml, etc.) is gone, and minimal containers lack
`ps`/`ss`. Therefore every bundled/repeated validation must be
standard-library-only or self-provisioning inside the same command (see
`scripts/bindings_probe.py`), and multi-step checks must use `set -e` or
per-segment `rc=$?` capture — otherwise a crash in segment 1 can be masked
by a later segment's success and the tool call reports green while its only
real validation never ran. [direct: three iterations of this exact
masking pattern — probe TypeError abort, `exit $?` re-reading echo's
status, `import yaml` crash hidden by a later `test`]

When a self-written check fails, ask FIRST whether the check's assertion is
part of the artifact's actual contract (checker vs. artifact): a failed
check is ambiguous evidence until you read what it asserted against what
the artifact is. Fix the check, not the artifact. [direct: four
checker-side failures vs zero artifact-side failures in this dialogue —
regex demanding same-line content, TypeError-vs-AttributeError, missing
pyyaml, over-asserting that the description contains the family name]

### 1. Environment
```bash
pip install grpcio==1.73.0 grpcio-tools==1.73.0   # exact versions from task
python3 --version; python3 -c "import grpc; print(grpc.__version__)"
```
If the task pins different versions, use those.

### 2. Author the proto (write via shell heredoc — tool write may be
workspace-only; the task dir is often outside it)
`syntax = "proto3";`, `service … { rpc X(Req) returns (Resp); }`, message
fields with exact names, types and field numbers from the spec. Field numbers
matter (`string namespace = 1;`). Package line is optional and cosmetic for
imports.

### 3. Generate bindings
```bash
cd /app
python3 -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto
```
Outputs `kv_store_pb2.py`, `kv_store_pb2_grpc.py` (filename-derived names).
Check the generated `_grpc.py` for the `<Service>Stub` and
`add_<Service>Servicer_to_server` symbols you must reference.

### 4. Server implementation
- `class Server(<file>_pb2_grpc.<Service>Servicer)` — one method per RPC,
  named exactly as the RPC (gRPC dispatches by method name).
- **Thread safety**: guard ALL state with one `threading.Lock`, covering both
  mutations and aggregate reads. Unlocked `sum(self._store.values())` races a
  concurrent `Put` → `RuntimeError: dictionary changed size during
  iteration`. [v01 verified: 40 workers × 40 ops burst, zero errors under
  lock]
- Delete-by-key-presence, not by value: a **stored 0 is not missing**
  (`success=True, value=0`); only an absent key gives `success=False`. [v01
  direct]
- `int32` response fields: plain Python ints are fine; the field type is part
  of the contract so totals stay in range. If a variant's spec permits
  out-of-range aggregates, clamp or widen per the proto first. [v01 direct +
  extrapolation]
- `serve()` skeleton:
  ```python
  server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
  kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
  port = server.add_insecure_port("[::]:5328")     # dual-stack: also accepts IPv4
  assert port, "failed to bind (stale server?)"    # returns 0, does NOT raise!
  server.start()
  server.wait_for_termination()
  ```
  `add_insecure_port` returns 0 on EADDRINUSE instead of raising — always
  assert it. Bind `[::]:<port>` (Linux dual-stack, v6only off) or both
  families explicitly, because client channel targets are outside your
  control and `localhost` may resolve to `::1` first. [v01 direct + teacher]
- Guard everything under `if __name__ == "__main__":` so graders/smoke
  clients can `import server` without side effects. [reverse-engineered
  robustness; cheap and safe]

### 5. Handover gate (the critical part — the deliverable is a LIVE process)

Never end with a foreground `python3 server.py` (hangs the tool) or a bare
`... &` you haven't proven. Procedure (see `scripts/gate.py`):

1. **Kill EVERY `python3 … server.py` interpreter** by scanning
   `/proc/<pid>/cmdline` — `$!` records a *wrapper* pid in this wrapped
   shell, not the interpreter, so `kill $!` can silently miss the real
   process. [v01 direct: recorded pids 104/262 vs. real interpreters 106/264]
2. **Prove zero listeners**: TCP connect to BOTH `::1` and `127.0.0.1` on the
   port must be refused. A zombie `/proc/<pid>` dir proves nothing; the
   connect-refused oracle is the only liveness truth. [v01 direct]
3. Launch detached: `nohup python3 /app/server.py >/app/server.log 2>&1 &`,
   sleep ~1 s, read the log.
4. **Prove exactly ONE server interpreter** exists (re-scan /proc).
5. Run the smoke client; **all checks must pass** (see below).
6. Leave it running. Do not kill/restart afterward — the grader must meet one
   live process with an EMPTY store.

   **Repair vs. verify asymmetry**: `gate.py` is a REPAIR tool — it starts by
   SIGKILLing every server on the port, so it is allowed only while the port
   is not yet final. Once handover state exists (one server, smoke green),
   all verification becomes strictly non-mutating: `/proc` cmdline scan for
   exactly one `python3 <server>.py` interpreter, nothing that kills,
   relaunches, or rebinds. Re-running the gate "to confirm" reopens the
   dead-port window you just closed.

### 6. Smoke verification (v01 semantics table; template in `scripts/smoke.py`)

Required functional checks, each asserted through the generated stubs:
fetch-missing → 0; put returns written value; overwrite → newest value;
namespace isolation; total sums only its namespace; absent namespace → 0;
delete existing → `success=True` + removed value; delete missing →
`success=False, value=0`; stored zero is not missing; **state persists across
a freshly created channel**; then **self-clean**: delete every key written
and assert all touched namespace totals are 0 again.

- The fresh-channel checks are also your **single-server exclusivity oracle**:
  if two server processes share the port (observed on v01: both reported a
  successful bind of the same `[::]:5328` — exact socket-flag mechanism
  unproven, do not assert), successive connections can land on either
  process, so the second channel can read a different store → persistence
  checks fail. [v01 direct]
- Self-cleaning smoke + (only if needed) a final fresh relaunch guarantee the
  grader's preconditions (empty store) hold. Decide as follows: if the smoke
  client self-cleaned AND asserted all touched totals back to 0, the store is
  already empty — DO NOT relaunch (a relaunch reopens the dead-port window
  and violates the repair-vs-verify asymmetry). Only relaunch when a probe
  could not self-clean and left state behind. [direct: iteration-2 smoke
  ended at totals 0 → no relaunch; the iteration-1 fresh solver spent real
  reasoning on this ambiguity, and the Skill should settle it]
- Side note: `/proc/net/tcp6` ports are HEX (`5328` → `0x14D0`);
  `grep '5328'` there is noise, and `head` truncation can fake "one
  listener". Prefer the connect oracle. [teacher + v01 direct]
- Imports: the interpreter's script directory (not cwd) is on `sys.path` —
  keep helper clients next to the generated modules, or the import fails
  even with the right cwd. [v01 direct]

## Failure modes index

| Symptom | Cause | Fix |
|---|---|---|
| Tool call hangs | foreground blocking server | `nohup … &`, verify via log + connect |
| Grader connection-refused although you "started" a server | stale/other server died, or your bind failed silently | assert `add_insecure_port` result; gate |
| Persistence smoke checks fail after a relaunch | two live servers share the port; fresh channel hit the other store | full gate: SIGKILL all by /proc scan, prove refusal on both families, relaunch, prove exactly one pid |
| `kill $!` does nothing to the served store | `$!` is a wrapper pid, interpreter is a child | scan `/proc/*/cmdline` for the script |
| `RuntimeError: dictionary changed size during iteration` | concurrent Put during sum/iteration | single lock around mutations AND aggregate reads |
| Smoke leaves keys behind → grader sees non-empty store | probe wrote state | self-cleaning smoke; only if it cannot self-clean, fresh relaunch (never just "to confirm") |
| `cp` from a host workspace path fails inside the container | host paths are not visible; the skill is mounted read-only at `/skill` | `cp /skill/scripts/... /app/` or heredoc |
| Concurrency burst flakiness | unlocked state, or an executor with too little headroom under bursts (the default executor is sized off CPU count, not 1 — but don't rely on it) | one lock around all state + explicit `ThreadPoolExecutor(max_workers>=10)` |

## Evidence tags

- **[v01 direct]** — observed by running the v01 task: smoke table and
  cross-channel persistence/exclusivity oracle (18/18, iterations 1-3),
  gate + wrapper-pid split, hex ports, lock-under-burst, bind-assert;
  binding facts via bindings_probe (19/19 on grpcio-tools 1.73.0 /
  protobuf 6.33.6 / upb); burst determinism warranty under REAL size
  churn, including the 120/140 unseeded-churn catch (the success-count
  self-check fired where the determinism assertions could not);
  verify_handover checklist (one pid, both families accept, named
  namespaces empty).
- **[teacher; subsequently v01-direct verified]** — dual-stack `[::]` bind
  acceptance on both families (connect oracle), bind-returns-0 semantics
  (asserted and observed), persistence checks as the exclusivity oracle
  (18/18 smoke, incl. the two-server incident), self-clean/fresh-relaunch
  handling.
- **[teacher]** — guidance relied on but not directly observed:
  `localhost`→`::1`-first resolution reasoning; v6only socket semantics
  beyond the observed acceptance.
- **[extrapolation]** — reasoned from spec axes without local exercise:
  conditional-update and multi-key operation semantics testing
  methodology; the churn+scale race-detector levers at 10^4-10^5 keys
  (GIL-mechanics reasoning; never run at that scale); long-window
  readiness beyond the `wait_ready` helper.

  Maintenance rule: evidence tags are claims too. Every edit that
  upgrades a claim's status ([extrapolation]→[direct], or a [teacher]
  item verified on a run) must update this section IN THE SAME EDIT: a
  tag records the strongest epistemic status a claim has reached;
  provenance may live in a parenthetical, but status is the column's
  meaning.

## proto3 ↔ Python bindings reference (rpc_api_structure)

All claims below were DIRECTLY PROBED on this environment's toolchain:
grpcio-tools 1.73.0, protobuf 6.33.6 (upb backend), Python 3.13.1. Exception
classes and messages are BACKEND-SPECIFIC: re-run `scripts/bindings_probe.py`
against a variant's pinned toolchain before relying on them. [direct on
this toolchain; portable practice marked when applicable]

- **Enums**: proto3 REQUIRES the first enum value to be `0` (the default).
  Members are plain ints — `x_pb2.Color.GREEN == 1` — and the field getter
  returns an int, so compare with `resp.status == x_pb2.Status.OK`.
  `Color.Name(v)` / `Color.Value('RED')` map both directions. Proto3 enums
  are open: an undeclared int (e.g. 7) round-trips serialize/parse without
  error, so server code must tolerate values outside the declared set.
- **Repeated scalar fields**: the constructor accepts a keyword list
  (`Msg(xs=[1,2])`). Attribute assignment raises
  `AttributeError: Assignment not allowed to map, or repeated field "xs" in
  protocol message object.` (AttributeError, not TypeError — and the message
  mentions "map, or repeated"). Mutate with `.append()/.extend()`. For
  responses, build a fresh message with the constructor keyword.
- **Repeated composite fields**: `m.items.add()` returns a new submessage for
  chained field sets.
- **Nested messages**: `Outer.Inner` → `x_pb2.Outer.Inner`. On this toolchain
  the constructor ALSO accepts a plain dict for a message-typed keyword and
  converts it (`p.Outer(inner={'name':'n'})` → `inner.name == 'n'`); an
  unknown dict key raises `ValueError: Protocol message ... has no "x"
  field.` PORTABLE PRACTICE: always construct with message INSTANCES —
  dict-kwarg acceptance is a backend convenience, not a contract; code that
  depends on it breaks on other protobuf backends. [iteration-1's "dict
  rejected" claim was FALSE on this backend — corrected by direct probe]
- **Maps** (`map<string,int32>`): behave as a MutableMapping (assign to keys,
  `.items()`); reassigning the container raises the same AttributeError
  family as repeated fields.
- **Presence**: proto3 scalar fields have NO `HasField` — calling it raises
  `ValueError: Field ... does not have presence.` Presence checks work for
  message fields (`m.HasField('inner')` → False/True) and oneofs
  (`m.WhichOneof('choice')` → member name or None). If a variant's semantics
  hinge on "was this field set", the spec must express it via sentinels or
  flags — mirror exactly what the spec says, don't invent presence.
- **Multi-field responses**: set every spec-required field explicitly —
  proto3 defaults are silent and an omitted bool defaults to `False` and
  "looks right". General rule (your Delete checks already embody it): assert
  presence through a presence-observable output (the flag), not through a
  defaulted value.
- **Codegen guard**: modern grpcio-tools embeds a generated-code runtime
  version check in `_pb2.py`; always regenerate with the task-pinned
  grpcio-tools in the SAME interpreter that runs the server — never
  hand-copy generated files from another environment.
- **Probe harness pattern**: negative expectations must never abort the
  suite. Use a helper that captures ANY exception, classifies it, records the
  actual class+message as evidence, and continues:
  `try: fn() except Exception as e: ok = type(e) in classes; ...` — and
  capture shell exit codes before echoing (`rc=$?; echo ...; exit $rc`),
  otherwise `echo`'s own status (0) masks a failing probe.

## Future verification procedures (for spec-declared variation)

- **rpc_api_structure**: run `scripts/bindings_probe.py` against the
  variant's generated bindings (it compiles its own probe proto and checks
  every claim of the binding reference: enums, repeated, nested, map,
  presence, oneof). After codegen, also confirm stub/servicer symbol names;
  round-trip each task message type through the stubs (construct → serialize
  → parse) before wiring the server.
- **stateful_service_semantics**: build the semantics table from the spec
  (identify delete/reset/conditional/aggregate/multi-key behavior), implement
  with one lock, and smoke-test every row PLUS cross-channel persistence PLUS
  a concurrency burst (`scripts/burst.py`) against the aggregate read. Burst
  mechanism, stated precisely: `RuntimeError: dictionary changed size during
  iteration` fires only on dict SIZE changes (insert/delete), never on value
  overwrites; `sum(ns.values())` holds the GIL (~5ms thread-switch interval),
  so at v01 scale (~100 keys, microsecond sums) even an UNLOCKED server
  almost always passes — at that scale the burst's real warranty is
  determinism (exact final total via client-side per-worker replay + clean
  zero), not race detection. To make the burst a genuine race detector,
  apply the two levers: (a) size churn for the WHOLE run (delete the
  previous churn's fresh key, insert a new one — chain must be seeded so the
  first victim provably exists, and count `success=True` deletes against the
  expected cycles so a silent no-op churn fails loudly; direct evidence: the
  unseeded chain returned 120/140 on first run while the exact-total
  assertions still passed — determinism alone cannot see a fake churn), and
  (b) scale: 10^4-10^5 keys per namespace make each sum span multiple GIL
  windows, and an unlocked server then fails reliably. Only under churn+
  scale may a failure be interpreted as proof the lock is missing. Keep
  per-worker key prefixes so the replay total stays exact (shared keys make
  overwrite order unmirrorable).
- **runtime_interaction_requirements**: wait-for-ready client helper
  (`channel_ready_future` with deadline, already in `scripts/smoke.py`);
  `scripts/burst.py` (self-cleaning, interleaves aggregate/point reads with
  writes under size churn); repeated channel creation; before handover run
  `scripts/verify_handover.py [namespaces...]` — the final NON-MUTATING
  checklist: exactly one server interpreter (/proc scan), connect oracle on
  both address families, and API emptiness of every named namespace
  (read-only totals).

## Assets

- `scripts/gate.py` — kill-all → port-free proof → launch → exactly-one-pid
  handover gate (parameterize port).
- `scripts/smoke.py` — self-cleaning full-semantics client (parameterize
  port, service stubs, semantics rows for the variant).
- `scripts/bindings_probe.py` — self-contained proto3↔Python binding probe:
  compiles its own probe proto (enum/repeated/nested/map/oneof) and verifies
  every binding-reference claim against the CURRENT toolchain; re-run on
  every variant. [probed directly on grpcio-tools 1.73.0 / protobuf 6.33.6]
- `scripts/burst.py` — self-cleaning concurrency burst: size churn through
  the whole run (seeded victim chain + success-count guard against silent
  no-op churn), exact final total via client-side replay, clean-zero
  assertion; honestly tagged: determinism check at v01 scale, race detector
  only with the churn+scale levers (see stateful_service_semantics bullet).
  [run on v01 iteration 3: 140/140 churn deletes, totals exact, post-clean 0]
- `scripts/verify_handover.py` — final NON-MUTATING checklist after all
  self-cleaning probes: exactly one server pid, connect oracle both
  families, optional per-namespace API emptiness (argv namespaces).
  [run on v01 iteration 3: HANDOVER OK]
- `scripts/server_template.py` — locked, dual-stack, asserted-bind server
  skeleton.
- `scripts/proto_template.proto` — proto skeleton with service/message
  placeholders.