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
The workflow has four deterministic phases: **Install → Proto → Generate → Serve**.
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
| `RPC_METHODS` | "rpc Name(Req) returns (Resp)" | Put, Fetch, Delete, ListNamespaceTotal |
| `MESSAGE_DEFS` | "message Name { … }" | See v01 grounding |
| `PORT` | "listen on port NNNN" | `5328` |
| `SERVER_CLASS` | "class <Name>" | `Server` |
| `STATE_SEMANTICS` | Prose description | Namespaced int store, overwrite-on-put, 0-default fetch, delete-returns-value, sum aggregate |

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

Write `/app/{PROTO_FILENAME}` with these rules:

### 2.1 Structure

```proto
syntax = "proto3";
package {PROTO_PACKAGE};
service {SERVICE_NAME} { /* RPCs */ }
/* Message definitions */
```

### 2.2 RPC definitions

For each RPC from the spec:

```proto
rpc {MethodName}({RequestMessageName}) returns ({ResponseMessageName});
```

- Only **unary** RPCs in this family (no streaming).
- Each RPC has its own request and response message type.

### 2.3 Message definitions

For each message:

```proto
message {MessageName} {
  {protobuf_type} {field_name} = {field_number};
  ...
}
```

**Protobuf type mapping** (use exactly these names in the .proto file):

| Spec says | Proto type |
|---|---|
| string | `string` |
| int32 / int / integer | `int32` |
| int64 / long | `int64` |
| bool / boolean | `bool` |
| float | `float` |
| double | `double` |
| bytes | `bytes` |
| repeated X | `repeated X` |

**Field numbers** must be positive integers, unique within each message, and
match the spec. When the spec says "field N", use `= N`.

### 2.4 Filename-to-module mapping

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

If generation fails, check:
1. Proto syntax is valid (all semicolons, braces, field numbers).
2. The `-I.` flag points to the directory containing the .proto file.
3. Package name doesn't conflict with Python keywords.

---

## Phase 4: Implement the Server

Write `/app/server.py`. The structure is always:

```python
import grpc
from concurrent import futures
import {module}_pb2
import {module}_pb2_grpc


class {SERVER_CLASS}({module}_pb2_grpc.{SERVICE_NAME}Servicer):
    def __init__(self):
        # Initialize in-memory state here
        ...

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

### 4.1 State management patterns

The server's `__init__` sets up in-memory state that **persists across all RPC
calls and client channels**. Use instance variables, never globals or locals
inside RPC methods.

**Namespaced dictionary store** (most common pattern in this family):

```python
self.store = {}  # {namespace: {key: value}}
```

### 4.2 Implementing state semantics

Map each RPC to its state operation. Use this decision table:

| Operation | Pattern | Default / edge case |
|---|---|---|
| **Create/Overwrite** (Put) | `self.store.setdefault(ns, {})[key] = value; return value` | Always succeeds |
| **Read** (Fetch/Get) | `return self.store.get(ns, {}).get(key, DEFAULT)` | Return `0` (or spec default) for missing key |
| **Delete** | Check existence first; if present: `pop(key)`, return `(True, value)`; else return `(False, 0)` | Missing key → success=False, value=0 |
| **Aggregate** (Sum/Count/List) | Compute over `self.store.get(ns, {})` | Return `0` or empty for absent namespace |
| **Conditional update** | Read-then-write with comparison | Only update if condition holds |

**Namespace isolation rule:** Every state operation must scope to `request.namespace`.
Never let one namespace's data leak into another's.

### 4.3 Server lifecycle

- Use `ThreadPoolExecutor(max_workers=10)` — sufficient for light-to-moderate concurrency.
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

### 5.2 Verify the server is alive

`pgrep` and `ps` may not be available in minimal containers. Use a Python
channel-connect check instead:

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

### 5.3 Smoke test with a real gRPC client

Write a short inline Python script that:
1. Opens an insecure channel to `localhost:{PORT}`.
2. Calls each RPC at least once with known inputs.
3. Asserts expected outputs match the spec's state semantics.
4. Closes the channel.

**Self-verification checklist:**

- [ ] Put returns the written value
- [ ] Fetch returns the stored value for existing keys
- [ ] Fetch returns default (0) for missing keys
- [ ] Delete returns (True, removed_value) for existing keys
- [ ] Delete returns (False, 0) for missing keys
- [ ] Aggregate (sum/count) returns correct computation
- [ ] Aggregate returns 0/empty for absent namespace
- [ ] Namespace isolation: data in ns1 is invisible from ns2
- [ ] State persists across separate RPC calls
- [ ] State persists across separate client channels (close and reopen channel)

---

## Common Pitfalls and Mitigations

| Pitfall | Symptom | Fix |
|---|---|---|
| Hyphen in proto filename but underscore in import | `ModuleNotFoundError` | `kv-store.proto` → import `kv_store_pb2` |
| Wrong field number in proto | Deserialization errors / wrong field values | Double-check every `= N` against spec |
| Using global state instead of instance state | State leaks between test runs or doesn't persist | All state in `self.store` inside `__init__` |
| Forgetting `setdefault` for namespace | `KeyError` on first Put to a new namespace | Always `self.store.setdefault(ns, {})[key] = val` |
| Server started in foreground | Blocks forever, test times out | Use `&` to background, then `sleep` |
| Server not started before tests run | `UNAVAILABLE` gRPC status | Add `sleep 2` after launch; verify with channel_ready_future |
| Wrong port binding | Connection refused | Use `[::]:{PORT}`, not `localhost:{PORT}` |
| Not installing exact grpcio version | Generated code incompatibility | Pin both grpcio and grpcio-tools to spec version |
| `pgrep`/`ps` not in container | `command not found` | Use Python `grpc.channel_ready_future` to verify |

---

## Adapting to Spec Variations

### When the spec adds more RPCs
Add a new method to the Servicer class for each RPC. Follow the same
state-operation patterns above. Each new RPC still needs its own request
and response message in the proto.

### When the spec changes field types
Use the type mapping table in §2.3. For `repeated` fields, the Python
generated code exposes them as lists. For nested messages, define the inner
message first and reference it as a type.

### When the spec changes state semantics
Adapt the decision table in §4.2. The key invariants are:
- State lives in `self` (instance variables).
- Every operation scopes to the correct namespace/key.
- Default return values match the spec for missing data.

### When the spec changes the port or class name
These are direct substitutions in the template. Grep for `{PORT}` and
`{SERVER_CLASS}` in the template and replace.

---

## Execution Script (Reference)

The following consolidated script can be adapted for any family member.
Replace all `{placeholders}` with extracted parameters.

```bash
#!/bin/bash
set -e

# Phase 1: Install
pip install grpcio=={GRPC_VERSION} grpcio-tools=={GRPC_VERSION}

# Phase 2: Proto (write via Python to avoid heredoc quoting issues)
python3 -c "
proto = '''{PROTO_CONTENT}'''
with open('/app/{PROTO_FILENAME}', 'w') as f:
    f.write(proto)
"

# Phase 3: Generate
cd /app
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. {PROTO_FILENAME}

# Phase 4: Server (write via Python)
python3 -c "
server_code = '''{SERVER_CODE}'''
with open('/app/server.py', 'w') as f:
    f.write(server_code)
"

# Phase 5: Launch
cd /app && python3 server.py &
sleep 2

# Verify (pgrep may not exist in minimal containers)
python3 -c "
import grpc
ch = grpc.insecure_channel('localhost:{PORT}')
grpc.channel_ready_future(ch).result(timeout=5)
print('Server running on port {PORT}')
ch.close()
"
```
