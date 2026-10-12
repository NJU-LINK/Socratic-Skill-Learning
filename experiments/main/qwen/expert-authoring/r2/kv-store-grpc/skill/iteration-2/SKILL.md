---
name: kv-store-grpc
description: >
  Build a Python gRPC key-value store service from a task specification.
  Covers proto file authoring, code generation, stateful server implementation,
  and background server lifecycle management. Handles variation in RPC surface
  area, state semantics (CRUD, namespaces, aggregates), and runtime serving
  requirements.
---

# KV-Store gRPC Service Builder

## Overview

This skill builds a real, running Python gRPC namespaced key-value store.
The workflow has five deterministic phases: **Install → Proto → Generate → Serve → Launch**.
Every family member shares this pipeline; only the concrete parameters vary.

---

## Phase 0: Extract Parameters from Task Spec

Read `task.yaml` (or the inline instruction) and extract these parameters.
If any parameter is not explicitly stated, use the family defaults shown.

| Parameter | Where to find it | Family default (v01) |
|---|---|---|
| `GRPC_VERSION` | "Install … grpcio==X.Y.Z" | `1.73.0` |
| `PROTO_FILENAME` | "Create /app/<name>.proto" | `kv-store.proto` |
| `SERVICE_NAME` | "service <Name>" | `KVStore` |
| `PROTO_PACKAGE` | "package <pkg>" | `kvstore` |
| `PORT` | "listen on port NNNN" | `5328` |
| `SERVER_CLASS` | "class <Name>" | `Server` |
| `RPC_LIST` | Each `rpc Name(Req) returns (Resp)` entry | Put, Fetch, Delete, ListNamespaceTotal |
| `MESSAGE_DEFS` | Each `message Name { ... }` entry with fields | See v01 grounding |
| `STATE_SEMANTICS` | Prose description of RPC behaviors | Namespaced int store, overwrite-on-put, 0-default fetch, delete-returns-value, sum aggregate |

**Critical rule:** Every field name, field number, field type, RPC name, message
name, service name, port, and class name must match the spec **exactly**.
Case-sensitive. Do not paraphrase.

---

## Phase 1: Install Dependencies

```bash
pip install grpcio=={GRPC_VERSION} grpcio-tools=={GRPC_VERSION}
```

- Pin both packages to the same version.
- Verify: `python3 -c "import grpc; print(grpc.__version__)"` must print the exact version.

---

## Phase 2: Author the Proto File

Write `/app/{PROTO_FILENAME}`. This is the most error-prone step — get it right.

### 2.1 Proto structure

```proto
syntax = "proto3";

package {PROTO_PACKAGE};

service {SERVICE_NAME} {
  // One rpc line per RPC in the spec
}

// Message definitions follow the service block
```

### 2.2 Translating the spec into RPC definitions

For each RPC listed in the spec, add exactly one line inside the `service` block:

```proto
  rpc {MethodName}({RequestMsg}) returns ({ResponseMsg});
```

**Rules:**
- Method name is case-sensitive from the spec.
- Each RPC gets its own unique request message type and response message type.
- The naming convention from the spec is `{MethodName}Request` / `{MethodName}Response` — verify this in the spec text.

### 2.3 Translating the spec into message definitions

For each message referenced by the RPCs, add a `message` block after the `service` block.

**Algorithm — for each field described in the spec:**

1. **Read the field specification:** The spec will say something like:
   - `request: namespace string field 1, key string field 2, value int32 field 3`
   - `response: success bool field 1, value int32 field 2`

2. **Map the spec type to the protobuf type:**

   | Spec says (case-insensitive) | Proto type | Python accessor |
   |---|---|---|
   | string | `string` | `request.field_name` → `str` |
   | int32, int, integer | `int32` | `request.field_name` → `int` |
   | int64, long | `int64` | `request.field_name` → `int` |
   | bool, boolean | `bool` | `request.field_name` → `bool` |
   | float | `float` | `request.field_name` → `float` |
   | double | `double` | `request.field_name` → `float` |
   | bytes | `bytes` | `request.field_name` → `bytes` |
   | uint32 | `uint32` | `request.field_name` → `int` |
   | uint64 | `uint64` | `request.field_name` → `int` |
   | repeated T | `repeated T` | `request.field_name` → `list` |
   | EnumName (enum) | `EnumName` | `request.field_name` → `int` (enum value) |
   | NestedMsg (message) | `NestedMsg` | `request.field_name` → message object |

3. **Assign field numbers:** The spec says "field N" → use `= N`. Field numbers must be:
   - Positive integers ≥ 1
   - Unique within each message
   - Match the spec exactly

4. **Write each field as:** `  {proto_type} {field_name} = {field_number};`

### 2.4 Handling repeated fields and enums (for variant specs)

**Repeated fields** — When the spec says "repeated string tags" or "repeated Item items":
```proto
message SomeRequest {
  repeated string tags = 1;
  repeated Item items = 2;  // nested message type
}
```
In Python, repeated fields are accessed as lists: `request.tags` → `list[str]`.

**Enums** — When the spec defines an enum type:
```proto
enum Status {
  UNKNOWN = 0;
  ACTIVE = 1;
  INACTIVE = 2;
}
message SomeResponse {
  Status status = 1;
}
```
The first enum value MUST be 0 in proto3. In Python, enum values are integers.

**Nested messages** — Define the inner message first, then reference it:
```proto
message Inner {
  string name = 1;
  int32 value = 2;
}
message Outer {
  Inner item = 1;
  repeated Inner items = 2;
}
```

### 2.5 Proto file verification checklist

After writing the proto file, verify:
- [ ] Every RPC in the spec has a corresponding `rpc` line
- [ ] Every request and response message is defined
- [ ] All field names match the spec (case-sensitive)
- [ ] All field numbers match the spec ("field N" → `= N`)
- [ ] All field types are correctly mapped
- [ ] Field numbers within each message are unique and ≥ 1
- [ ] Semicolons end every field line
- [ ] Braces are balanced

### 2.6 Filename-to-module mapping

Proto filenames with hyphens generate Python modules with underscores:
- `kv-store.proto` → `kv_store_pb2.py` and `kv_store_pb2_grpc.py`
- `my_service.proto` → `my_service_pb2.py` and `my_service_pb2_grpc.py`

The import statement in server.py must use the **underscore** form.

---

## Phase 3: Generate Python Bindings

```bash
cd /app && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. {PROTO_FILENAME}
```

**Verify** both files exist:

```bash
ls -la /app/{module_name}_pb2.py /app/{module_name}_pb2_grpc.py
```

**If generation fails**, check:
1. Proto syntax is valid (all semicolons, braces, field numbers).
2. The `-I.` flag points to the directory containing the .proto file.
3. Package name doesn't conflict with Python keywords.
4. Enum values start at 0 (required by proto3).
5. No duplicate field numbers within a message.

---

## Phase 4: Implement the Server

Write `/app/server.py`.

### 4.1 File writing method

**Use bash heredoc** to write multi-line files. This avoids all quoting issues:

```bash
cat > /app/server.py << 'SERVEREOF'
... actual Python code here ...
SERVEREOF
```

The single quotes around `'SERVEREOF'` prevent any variable expansion or escape
interpretation inside the heredoc. This is the safest method for writing code
that may contain quotes, backslashes, or special characters.

**Alternative** (if heredoc fails in some shell): write via Python using a
raw string or by reading from a temporary file.

### 4.2 Server skeleton

```python
import grpc
from concurrent import futures
import threading
import {module}_pb2
import {module}_pb2_grpc


class {SERVER_CLASS}({module}_pb2_grpc.{SERVICE_NAME}Servicer):
    def __init__(self):
        self._lock = threading.Lock()
        # Initialize in-memory state here
        self.store = {}  # {namespace: {key: value}}

    # One method per RPC, matching RPC name exactly
    def {RpcName}(self, request, context):
        ...


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    {module}_pb2_grpc.add_{SERVICE_NAME}Servicer_to_server({SERVER_CLASS}(), server)
    server.add_insecure_port("[::]:{PORT}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
```

### 4.3 State management — instance variables only

All state lives in `self` (instance variables set in `__init__`). Never use
module-level globals or method-local variables for persistent state.

**Namespaced dictionary store** (primary pattern):

```python
self.store = {}  # {namespace_str: {key_str: value}}
```

**Thread safety:** gRPC servers use a thread pool, so concurrent requests are
possible. Use `threading.Lock()` to protect state mutations:

```python
def Put(self, request, context):
    with self._lock:
        ns = request.namespace
        self.store.setdefault(ns, {})[request.key] = request.value
    return {module}_pb2.PutResponse(value=request.value)
```

For read-only operations, locking is optional but recommended for consistency.

### 4.4 State operation patterns

Map each RPC to its state operation using this decision table:

| Operation category | Pattern | Return value | Edge case return |
|---|---|---|---|
| **Create/Overwrite** (Put, Set) | `store.setdefault(ns, {})[key] = value` | The written value | Always succeeds |
| **Read** (Get, Fetch) | `store.get(ns, {}).get(key, DEFAULT)` | The stored value | `0` or spec-defined default for missing |
| **Delete** (Remove) | Check existence; if present: `pop(key)`, return `(True, value)` | success=True + removed value | `(False, 0)` for missing key |
| **Sum aggregate** (Total, Sum) | `sum(store.get(ns, {}).values())` | The integer sum | `0` for absent/empty namespace |
| **Count aggregate** (Count, Size) | `len(store.get(ns, {}))` | The integer count | `0` for absent/empty namespace |
| **List keys** (ListKeys, Keys) | `list(store.get(ns, {}).keys())` | repeated string field | Empty list for absent namespace |
| **List entries** (ListAll, Entries) | Iterate `store.get(ns, {}).items()` | repeated message field | Empty list for absent namespace |
| **Conditional update** (CAS, SetIf) | Read current value, compare, write only if match | success bool + new/old value | success=False if condition not met |
| **Increment** (Incr, Add) | `store.setdefault(ns, {})[key] = store.get(ns, {}).get(key, 0) + delta` | The new value | Treat missing as 0 |
| **Reset/Clear** (Clear, ResetAll) | `store[ns] = {}` or `del store[ns]` | success bool | success=True even if ns was absent |
| **Multi-key read** (MultiGet) | `[store.get(ns, {}).get(k, DEFAULT) for k in keys]` | repeated message | Default for each missing key |
| **Multi-key write** (MultiPut) | Loop `store.setdefault(ns, {})[k] = v` for each pair | success bool | Always succeeds |

### 4.5 Namespace isolation rule

Every state operation must scope to `request.namespace`. Never let one
namespace's data leak into another's. The standard pattern is:

```python
ns_data = self.store.get(request.namespace, {})
# operate on ns_data
```

Or for writes:
```python
self.store.setdefault(request.namespace, {})[key] = value
```

### 4.6 Implementing the Servicer methods

For each RPC method, follow this template:

```python
def {MethodName}(self, request, context):
    # 1. Extract fields from request
    ns = request.namespace  # or whatever the namespace field is called
    key = request.key       # or whatever the key field is called

    # 2. Perform state operation (with lock for writes)
    with self._lock:
        # ... state mutation ...

    # 3. Construct and return the response message
    return {module}_pb2.{ResponseMsg}(field1=val1, field2=val2)
```

**Important:** The response constructor takes keyword arguments matching the
field names from the proto definition. Use the exact field names.

### 4.7 Server lifecycle

- Use `ThreadPoolExecutor(max_workers=10)` — sufficient for light-to-moderate concurrency. Increase to 20+ if the spec mentions high concurrency.
- Bind to `[::]:{PORT}` (IPv4+IPv6 wildcard) so localhost connections always work.
- Call `server.start()` then `server.wait_for_termination()` in the main thread.
- The server must be **started in the background** and **left running** after the
  skill completes. The test harness connects to it as an external client.

---

## Phase 5: Launch and Verify

### 5.1 Start the server as a background process

```bash
cd /app && python3 server.py &
sleep 2
```

If the spec mentions the server must be ready before tests, add a readiness
check:

```bash
python3 -c "
import grpc, time
for i in range(10):
    try:
        ch = grpc.insecure_channel('localhost:{PORT}')
        grpc.channel_ready_future(ch).result(timeout=2)
        print('Server is ready')
        ch.close()
        break
    except:
        time.sleep(1)
else:
    print('SERVER NOT READY')
"
```

### 5.2 Verify file artifacts exist

```bash
ls -la /app/{PROTO_FILENAME} /app/{module}_pb2.py /app/{module}_pb2_grpc.py /app/server.py
```

### 5.3 Smoke test with a real gRPC client

Write a short inline Python script that:
1. Opens an insecure channel to `localhost:{PORT}`.
2. Calls each RPC at least once with known inputs.
3. Asserts expected outputs match the spec's state semantics.
4. Tests edge cases (missing keys, empty namespaces, namespace isolation).
5. Tests cross-channel persistence (close channel, reopen, verify state persists).
6. Closes the channel.

**Self-verification checklist:**

- [ ] Put/Set returns the written value
- [ ] Put/Set overwrites existing value correctly
- [ ] Get/Fetch returns the stored value for existing keys
- [ ] Get/Fetch returns default (0) for missing keys
- [ ] Get/Fetch returns default (0) for missing namespaces
- [ ] Delete returns (True, removed_value) for existing keys
- [ ] Delete returns (False, 0) for missing keys
- [ ] Aggregate operations return correct computation
- [ ] Aggregate operations return 0/empty for absent namespace
- [ ] Namespace isolation: data in ns1 is invisible from ns2
- [ ] State persists across separate RPC calls
- [ ] State persists across separate client channels (close and reopen)
- [ ] (If spec requires) Conditional updates only apply when condition holds
- [ ] (If spec requires) Multi-key operations work correctly
- [ ] (If spec requires) Increment/CAS operations behave atomically

---

## Common Pitfalls and Mitigations

| Pitfall | Symptom | Fix |
|---|---|---|
| Hyphen in proto filename but underscore in import | `ModuleNotFoundError` | `kv-store.proto` → import `kv_store_pb2` |
| Wrong field number in proto | Deserialization errors / wrong field values | Double-check every `= N` against spec |
| Wrong field name in proto | `AttributeError` at runtime | Field names are case-sensitive from spec |
| Missing semicolon in proto | Protoc parse error | Every field line ends with `;` |
| Enum not starting at 0 | Protoc error (proto3 requirement) | First enum value must be `= 0` |
| Using global state instead of instance state | State leaks or doesn't persist | All state in `self.store` inside `__init__` |
| Forgetting `setdefault` for namespace | `KeyError` on first Put to a new namespace | Always `self.store.setdefault(ns, {})[key] = val` |
| No thread locking | Race conditions under concurrent requests | Use `with self._lock:` for all mutations |
| Server started in foreground | Blocks forever, test times out | Use `&` to background, then `sleep` |
| Server not started before tests run | `UNAVAILABLE` gRPC status | Add `sleep 2` after launch; verify with channel_ready_future |
| Wrong port binding | Connection refused | Use `[::]:{PORT}`, not `localhost:{PORT}` |
| Not installing exact grpcio version | Generated code incompatibility | Pin both grpcio and grpcio-tools to spec version |
| `pgrep`/`ps` not in container | `command not found` | Use Python `grpc.channel_ready_future` to verify |
| `python3 -c` quoting issues | SyntaxError when writing files | Use bash heredoc: `cat > file << 'EOF'` |
| Nested quotes in heredoc | Still fails | Use `'EOF'` (quoted) to disable expansion |

---

## Adapting to Spec Variations

### When the spec has more RPCs or a larger service
For each additional RPC:
1. Add an `rpc` line in the `service` block.
2. Define its request and response messages.
3. Add a method to the Servicer class matching the RPC name.
4. Implement using the state operation patterns from §4.4.

### When the spec has complex message types
- **Multiple fields per message:** Just add more field lines. Keep field numbers unique and matching the spec.
- **Repeated fields:** Use `repeated` keyword. In Python, these become lists.
- **Nested messages:** Define inner messages before outer messages. Reference by type name.
- **Enums:** Define the enum before any message that uses it. First value must be 0.

### When the spec changes state semantics
Use the operation pattern table in §4.4. Key invariants:
- State lives in `self` (instance variables).
- Every operation scopes to the correct namespace/key.
- Default return values match the spec for missing data.
- Write operations use `self._lock` for thread safety.

### When the spec changes port, class name, or package name
These are direct substitutions in the templates. The patterns remain identical.

### When the spec requires high-concurrency serving
- Increase `max_workers` in `ThreadPoolExecutor` (e.g., 50 or 100).
- Ensure all state mutations are locked.
- Consider read-write locks (`threading.RWLock`) if reads vastly outnumber writes.

---

## Quick-Reference: End-to-End Execution Template

This template shows the shell structure. Replace all `{PLACEHOLDERS}` with
values extracted in Phase 0. The proto and server content shown here are for
the v01 anchor member; for other family members, construct them per Phases 2–4.

```bash
#!/bin/bash
set -e

# Phase 1: Install
pip install grpcio=={GRPC_VERSION} grpcio-tools=={GRPC_VERSION}

# Phase 2: Write proto (heredoc avoids all quoting issues)
cat > /app/{PROTO_FILENAME} << 'PROTOEOF'
{PROTO_CONTENT_CONSTRUCTED_PER_PHASE_2}
PROTOEOF

# Phase 3: Generate
cd /app
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. {PROTO_FILENAME}

# Phase 4: Write server (heredoc avoids all quoting issues)
cat > /app/server.py << 'SERVEREOF'
{SERVER_CODE_CONSTRUCTED_PER_PHASE_4}
SERVEREOF

# Phase 5: Launch and verify
cd /app && python3 server.py &
sleep 2

python3 -c "
import grpc
ch = grpc.insecure_channel('localhost:{PORT}')
grpc.channel_ready_future(ch).result(timeout=5)
print('Server running on port {PORT}')
ch.close()
"
```

### v01 Concrete Example (proto content)

For the v01 anchor member, the proto heredoc content is:

```proto
syntax = "proto3";

package kvstore;

service KVStore {
  rpc Put(PutRequest) returns (PutResponse);
  rpc Fetch(FetchRequest) returns (FetchResponse);
  rpc Delete(DeleteRequest) returns (DeleteResponse);
  rpc ListNamespaceTotal(ListNamespaceTotalRequest) returns (ListNamespaceTotalResponse);
}

message PutRequest {
  string namespace = 1;
  string key = 2;
  int32 value = 3;
}

message PutResponse {
  int32 value = 1;
}

message FetchRequest {
  string namespace = 1;
  string key = 2;
}

message FetchResponse {
  int32 value = 1;
}

message DeleteRequest {
  string namespace = 1;
  string key = 2;
}

message DeleteResponse {
  bool success = 1;
  int32 value = 2;
}

message ListNamespaceTotalRequest {
  string namespace = 1;
}

message ListNamespaceTotalResponse {
  int32 total = 1;
}
```

### v01 Concrete Example (server code)

For the v01 anchor member, the server heredoc content is:

```python
import grpc
from concurrent import futures
import threading
import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self):
        self._lock = threading.Lock()
        self.store = {}

    def Put(self, request, context):
        with self._lock:
            self.store.setdefault(request.namespace, {})[request.key] = request.value
        return kv_store_pb2.PutResponse(value=request.value)

    def Fetch(self, request, context):
        value = self.store.get(request.namespace, {}).get(request.key, 0)
        return kv_store_pb2.FetchResponse(value=value)

    def Delete(self, request, context):
        with self._lock:
            ns_data = self.store.get(request.namespace, {})
            if request.key in ns_data:
                value = ns_data.pop(request.key)
                return kv_store_pb2.DeleteResponse(success=True, value=value)
        return kv_store_pb2.DeleteResponse(success=False, value=0)

    def ListNamespaceTotal(self, request, context):
        total = sum(self.store.get(request.namespace, {}).values())
        return kv_store_pb2.ListNamespaceTotalResponse(total=total)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
```

For other family members, replace the RPC definitions, message types, method
implementations, port, and class name according to the spec, while keeping
the overall structure (imports, lock, serve function, lifecycle) identical.
