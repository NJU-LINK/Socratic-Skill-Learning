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

Build a real, running Python gRPC namespaced key-value store.
Pipeline: **Install → Proto → Generate → Serve → Launch**.
Every family member shares this pipeline; only the concrete parameters vary.

**For the v01 anchor member**, the Quick-Reference at the bottom provides exact
proto content and server code. **For any other spec**, you MUST construct proto
and server from Phases 2 and 4 using the spec's parameters — never copy v01
examples for a different spec.

---

## Phase 0: Extract Parameters

Read `task.yaml` and extract ALL of the following before writing any code:

| Parameter | Source in spec | v01 default |
|---|---|---|
| `GRPC_VERSION` | "grpcio==X.Y.Z" | `1.73.0` |
| `PROTO_FILENAME` | "/app/<name>.proto" | `kv-store.proto` |
| `SERVICE_NAME` | "service <Name>" | `KVStore` |
| `PROTO_PACKAGE` | "package <pkg>" | `kvstore` |
| `PORT` | "port NNNN" | `5328` |
| `SERVER_CLASS` | "class <Name>" | `Server` |
| `RPC_LIST` | Each `rpc` entry with request/response types | Put, Fetch, Delete, ListNamespaceTotal |
| `MESSAGE_FIELDS` | Each field's name, type, number per message | See task.yaml |
| `STATE_SEMANTICS` | Prose: defaults, return values, edge cases | ns int store, overwrite, 0-default, delete-returns-value, sum |

**Critical rule:** Every field name, field number, field type, RPC name, message
name, service name, port, and class name must match the spec **exactly**.

---

## Phase 1: Install

```bash
pip install grpcio=={GRPC_VERSION} grpcio-tools=={GRPC_VERSION}
```

Verify: `python3 -c "import grpc; print(grpc.__version__)"` prints the exact version.

---

## Phase 2: Construct and Write the Proto File

Write `/app/{PROTO_FILENAME}` using `cat > file << 'PROTOEOF'` heredoc.

### Step-by-step construction procedure

Execute these steps **in order** for every spec:

**Step 1 — Write the header:**
```proto
syntax = "proto3";

package {PROTO_PACKAGE};
```

**Step 2 — Write the service block:** For each RPC in `RPC_LIST`, add one line:
```proto
service {SERVICE_NAME} {
  rpc Put(PutRequest) returns (PutResponse);
  rpc Fetch(FetchRequest) returns (FetchResponse);
  ...
}
```
- RPC method names are case-sensitive from the spec.
- Each RPC has unique `{MethodName}Request` / `{MethodName}Response` message types.

**Step 3 — Write each request message:** For each RPC's request, read the spec
and produce one `message` block. For each field:
1. Read: `field_name` (exact name from spec), `type` (map below), `field_number` ("field N" → `= N`)
2. Write: `  {proto_type} {field_name} = {field_number};`

```proto
message PutRequest {
  string namespace = 1;
  string key = 2;
  int32 value = 3;
}
```

**Step 4 — Write each response message:** Same procedure as Step 3.

**Step 5 — Verify** before moving on:
- [ ] Every RPC has a `rpc` line AND both request + response message definitions
- [ ] Every field name matches spec exactly (case-sensitive)
- [ ] Every field number matches spec ("field N" → `= N`)
- [ ] Field numbers are unique within each message and ≥ 1
- [ ] Every field line ends with `;`
- [ ] Braces are balanced

### Type mapping table

| Spec type (case-insensitive) | Proto type | Notes |
|---|---|---|
| string | `string` | |
| int32, int, integer | `int32` | |
| int64, long | `int64` | |
| bool, boolean | `bool` | |
| float | `float` | |
| double | `double` | |
| bytes | `bytes` | |
| uint32 | `uint32` | |
| uint64 | `uint64` | |
| repeated T | `repeated T` | Python list accessor |
| EnumName | `EnumName` | First value must be 0 |
| NestedMsg | `NestedMsg` | Define inner message first |

### Handling variant types

**Repeated fields:** `repeated string tags = 1;` → Python `request.tags` is a list.

**Enums:** First value MUST be `= 0` (proto3 requirement).
```proto
enum Status { UNKNOWN = 0; ACTIVE = 1; INACTIVE = 2; }
```

**Nested messages:** Define the inner message BEFORE any message that references it.

### Filename-to-module mapping

Hyphens in proto filenames become underscores in generated Python modules:
`kv-store.proto` → `kv_store_pb2.py` / `kv_store_pb2_grpc.py`.
Server imports MUST use the underscore form.

---

## Phase 3: Generate Python Bindings

```bash
cd /app && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. {PROTO_FILENAME}
```

Verify: `ls -la /app/{module}_pb2.py /app/{module}_pb2_grpc.py`

**If generation fails**, check: valid proto syntax, `-I.` points to proto dir,
no Python keyword conflicts, enum starts at 0, no duplicate field numbers.

---

## Phase 4: Construct and Write the Server

Write `/app/server.py` using `cat > file << 'SERVEREOF'` heredoc.

### Step-by-step construction procedure

**Step 1 — Write imports:**
```python
import grpc
from concurrent import futures
import threading
import {module}_pb2
import {module}_pb2_grpc
```
`{module}` is the underscore form of the proto filename (e.g., `kv_store`).

**Step 2 — Write the Servicer class skeleton:**
```python
class {SERVER_CLASS}({module}_pb2_grpc.{SERVICE_NAME}Servicer):
    def __init__(self):
        self._lock = threading.Lock()
        self.store = {}  # {namespace: {key: value}}
```
All persistent state goes in `self` — never globals.

**Step 3 — Implement one method per RPC:** For each RPC, follow this template:
```python
    def {MethodName}(self, request, context):
        # 1. Extract request fields
        ns = request.namespace
        key = request.key

        # 2. Perform state operation (with lock for mutations)
        with self._lock:
            # ... mutation logic ...
            result = ...

        # 3. Return response
        return {module}_pb2.{ResponseMsg}(field1=result)
```

**Use the state operation decision table below** to implement each method's logic.

**Step 4 — Write the serve() function:**
```python
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    {module}_pb2_grpc.add_{SERVICE_NAME}Servicer_to_server({SERVER_CLASS}(), server)
    server.add_insecure_port("[::]:{PORT}")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
```

### State operation decision table

| Category | Implementation pattern | Edge case |
|---|---|---|
| **Create/Overwrite** (Put, Set) | `with self._lock: self.store.setdefault(ns, {})[key] = value` then `return Resp(value=value)` | Always succeeds |
| **Read** (Get, Fetch) | `value = self.store.get(ns, {}).get(key, 0)` then `return Resp(value=value)` | Return `0` or spec default for missing |
| **Delete** (Remove) | `with self._lock:` check `ns in self.store and key in self.store[ns]`; if present: `value = self.store[ns].pop(key)`, `return Resp(success=True, value=value)`; **else still inside lock**: `return Resp(success=False, value=0)` | Missing → `(False, 0)` |
| **Sum aggregate** (Total, Sum) | `total = sum(self.store.get(ns, {}).values())` then `return Resp(total=total)` | `0` for absent/empty ns |
| **Count aggregate** (Count, Size) | `count = len(self.store.get(ns, {}))` then `return Resp(count=count)` | `0` for absent/empty ns |
| **List keys** (ListKeys) | `keys = list(self.store.get(ns, {}).keys())` → populate repeated field | Empty for absent ns |
| **List entries** (ListAll) | Iterate `.items()`, append to repeated message field | Empty for absent ns |
| **Conditional update** (CAS) | `with self._lock:` read current, compare, write only if match | `success=False` if condition fails |
| **Increment** (Incr) | `with self._lock: self.store.setdefault(ns, {})[key] = self.store.get(ns, {}).get(key, 0) + delta` | Treat missing as 0 |
| **Reset/Clear** | `with self._lock: self.store[ns] = {}` or `self.store.pop(ns, {})` | `True` even if ns absent |
| **Multi-key read** (MultiGet) | `[self.store.get(ns, {}).get(k, 0) for k in request.keys]` | Default per missing key |
| **Multi-key write** (MultiPut) | `with self._lock:` loop `self.store.setdefault(ns, {})[k] = v` | Always succeeds |

### Critical rules

1. **Namespace isolation:** Every operation scopes to `request.namespace`. Use
   `self.store.get(ns, {})` for reads, `self.store.setdefault(ns, {})` for writes.
2. **Thread safety:** ALL state mutations use `with self._lock:`. Read-only ops
   may omit the lock but it is recommended for consistency.
3. **Delete lock pattern:** The ENTIRE Delete method body (both branches) must
   be inside `with self._lock:`. Never return outside the lock for mutations.
4. **Response constructors** use keyword args matching proto field names:
   `{module}_pb2.DeleteResponse(success=True, value=removed_value)`

---

## Phase 5: Launch and Verify

### Start the server as a background process

```bash
cd /app && python3 server.py &
sleep 2
```

### Verify server is alive

```bash
python3 -c "
import grpc
ch = grpc.insecure_channel('localhost:{PORT}')
grpc.channel_ready_future(ch).result(timeout=5)
print('Server running on port {PORT}')
ch.close()
"
```

`pgrep`/`ps` may not exist in minimal containers — always use the Python check.

### Verify file artifacts

```bash
ls -la /app/{PROTO_FILENAME} /app/{module}_pb2.py /app/{module}_pb2_grpc.py /app/server.py
```

### Smoke test (recommended)

Write an inline test script covering:
- Each RPC called at least once
- Edge cases: missing keys, empty namespaces, namespace isolation
- Cross-channel persistence: close channel, reopen, verify state persists
- Assert expected return values match the spec's state semantics

---

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| Hyphen in proto filename but underscore in import | `kv-store.proto` → `import kv_store_pb2` |
| Wrong field number in proto | Double-check `= N` against spec for every field |
| Wrong field name (case mismatch) | Copy field names verbatim from spec |
| Missing semicolon in proto | Every field line ends with `;` |
| Enum not starting at 0 | First enum value must be `= 0` (proto3 rule) |
| Global state instead of instance state | All state in `self.store` inside `__init__` |
| Missing `setdefault` for namespace | Always `self.store.setdefault(ns, {})[key] = val` |
| Delete returning outside the lock | Entire Delete body inside `with self._lock:` |
| Server started in foreground | Use `&` then `sleep 2` |
| Server not ready before tests | `sleep 2` + `channel_ready_future` check |
| Wrong port binding | Use `[::]:{PORT}`, not `localhost:{PORT}` |
| Wrong grpcio version | Pin both grpcio and grpcio-tools to spec version |
| `python3 -c` quoting issues | Use heredoc: `cat > file << 'EOF'` |

---

## Adapting to Spec Variations

**More RPCs:** Add `rpc` line + request/response messages + Servicer method per RPC.

**Complex messages:** More fields → more field lines. Repeated → `repeated` keyword.
Nested → define inner message first. Enums → first value = 0.

**Different state semantics:** Use the decision table. Invariants: state in `self`,
operations scope to namespace/key, defaults match spec.

**Different port/class/package:** Direct substitution in templates.

**High concurrency:** Increase `max_workers` (e.g., 50). Ensure all mutations locked.

---

## Quick-Reference: End-to-End Template

```bash
# Phase 1
pip install grpcio=={GRPC_VERSION} grpcio-tools=={GRPC_VERSION}

# Phase 2 (heredoc)
cat > /app/{PROTO_FILENAME} << 'PROTOEOF'
{CONSTRUCTED_PER_PHASE_2}
PROTOEOF

# Phase 3
cd /app && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. {PROTO_FILENAME}

# Phase 4 (heredoc)
cat > /app/server.py << 'SERVEREOF'
{CONSTRUCTED_PER_PHASE_4}
SERVEREOF

# Phase 5
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

### v01 Anchor — Proto Content

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

### v01 Anchor — Server Code

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
            else:
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

**For non-v01 specs:** replace RPC definitions, message types, method implementations,
port, and class name per Phases 2 and 4. Keep the overall structure (imports, lock,
serve function, lifecycle) identical.
