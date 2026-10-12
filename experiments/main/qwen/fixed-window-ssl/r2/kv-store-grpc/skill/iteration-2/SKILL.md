---
name: kv-store-grpc
description: >
  Build and run a stateful Python gRPC service from a protobuf specification.
  Covers proto authoring, code generation, thread-safe server implementation
  with in-memory state, and reliable lifecycle management. Generalizes across
  varying RPC structures, stateful semantics, and runtime requirements.
---

# Build a Stateful Python gRPC Service

## Procedure Overview

1. Install pinned grpcio + grpcio-tools
2. Write the `.proto` file from the service specification
3. Generate Python bindings with correct import paths
4. Implement the servicer class with thread-safe state
5. Start the server and verify it is listening

---

## Step 1: Install Dependencies

```bash
pip install grpcio==<version> grpcio-tools==<version>
```

Use the exact versions specified in the task. Both must match.

---

## Step 2: Write the Proto File

### Decision: Map the service specification to proto syntax

Read the task specification and extract:
- **Service name** → `service <ServiceName> { ... }`
- **RPC methods** → `rpc <MethodName>(<RequestMsg>) returns (<ResponseMsg>);`
- **Message fields** → extract field name, type, and field number from the spec

**Field type mapping** (spec terminology → proto type):
| Spec says | Proto type |
|-----------|-----------|
| "string field N" | `string name = N;` |
| "int32 field N" | `int32 name = N;` |
| "bool field N" | `bool name = N;` |
| "repeated X" | `repeated X name = N;` |
| "enum" | Define `enum Name { ... }` then use as field type |
| nested message | Define `message Inner { ... }` then use as field type |

**File naming**: The proto filename determines the generated Python module names. Hyphens in the filename become underscores in Python imports. Example: `my-service.proto` → `my_service_pb2.py` and `my_service_pb2_grpc.py`.

**Template**:
```protobuf
syntax = "proto3";
package <package_name>;

service <ServiceName> {
  rpc <Method1>(<Req1>) returns (<Resp1>);
  rpc <Method2>(<Req2>) returns (<Resp2>);
  // ... more RPCs as specified
}

message <Req1> {
  <type> <field_name> = <field_number>;
  // fields numbered sequentially from 1
}

message <Resp1> {
  <type> <field_name> = <field_number>;
}
// ... repeat for all request/response messages
```

---

## Step 3: Generate Python Bindings

```bash
python -m grpc_tools.protoc -I<proto_dir> --python_out=<out_dir> --grpc_python_out=<out_dir> <proto_dir>/<filename>.proto
```

**Critical rule**: `-I` must be the directory containing the proto file. This sets the import root so the generated `*_pb2_grpc.py` can correctly `import <module>_pb2`.

**Pitfall**: If `-I` is wrong or missing, the generated grpc file will have a broken import and fail at runtime with `ModuleNotFoundError`.

### Decision: Verify generated names before writing server code

After generation, inspect the `*_pb2_grpc.py` file to confirm:
- **Servicer base class name**: `<ServiceName>Servicer` (e.g., `KVStore` → `KVStoreServicer`)
- **Registration function**: `add_<ServiceName>Servicer_to_server`
- **Stub class**: `<ServiceName>Stub`

```bash
grep -n "class\|def add_" <module>_pb2_grpc.py
```

This prevents guessing wrong names when the service name varies.

---

## Step 4: Implement the Servicer

### Decision: Choose state data structure

Analyze the service semantics from the spec:

| Semantic pattern | State structure | Example |
|-----------------|----------------|---------|
| Flat key-value store | `dict` | `{key: value}` |
| Namespaced/partitioned store | `defaultdict(dict)` | `{ns: {key: value}}` |
| Multiple entity types | Multiple dicts or nested structure | `{users: {}, items: {}}` |
| Ordered/sequential data | `list` or `deque` | Event log |
| Counter/accumulator | `int` or `defaultdict(int)` | Per-key counters |

**v01 example**: Namespaced integer store → `self.store = defaultdict(dict)` where `store[namespace][key] = int_value`.

### Decision: Map each RPC to state operations

For each RPC method, determine:
1. **What state does it read?** → use `.get()` with appropriate defaults for missing keys
2. **What state does it write?** → direct assignment for overwrite, `.pop()` for delete
3. **What does it return?** → construct the response message with correct fields
4. **What are the edge cases?** → missing keys, empty namespaces, deleting non-existent entries

**Common semantic patterns**:
- **Create/Overwrite**: `store[ns][key] = value; return value`
- **Read with default**: `return store.get(ns, {}).get(key, default_value)`
- **Delete with feedback**: Check existence → pop and return `(success=True, value)` or `(success=False, default)`
- **Aggregate**: `sum(store.get(ns, {}).values())` — returns 0 for missing/empty namespace

### Decision: Class naming — task-specified vs generated

The task specification will name the implementation class (e.g., "Implement the service as class `Server`"). The generated protobuf code provides a **base class** named `<ServiceName>Servicer` (e.g., `KVStore` → `KVStoreServicer`). These are two different names:

```python
# Task says: "class Server"
# Generated base class: KVStoreServicer (from proto service name KVStore)
class Server(kv_store_pb2_grpc.KVStoreServicer):
    ...
```

**Rule**: Always inherit from the generated `<ServiceName>Servicer`. The implementation class name comes from the task spec. If the task doesn't specify a name, use `Server` or `<ServiceName>Impl`.

### Decision: Thread safety

**Mandatory**: Python gRPC uses `ThreadPoolExecutor` — handlers run concurrently. Every RPC handler that reads or writes shared state must acquire a lock.

```python
import threading

class Server(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        self.lock = threading.Lock()
        self.store = ...  # chosen data structure

    def <RpcMethod>(self, request, context):
        with self.lock:
            # all state access here
            return <module>_pb2.<ResponseMsg>(...)
```

**Rule**: One lock for the entire state is simplest and correct. Only split into multiple locks if profiling shows contention (rare for in-memory stores).

---

## Step 5: Start the Server

```python
from concurrent import futures
import grpc

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

### Decision: Server lifecycle

- **`wait_for_termination()` is mandatory** — without it, the script exits immediately after `start()`.
- **`[::]:<port>`** binds to all interfaces (IPv4 + IPv6).
- **`max_workers`**: 10 is a safe default. Increase for high-concurrency requirements.
- **Working directory**: Always `cd <dir> && python server.py &`. When you run `python server.py`, Python automatically adds the script's directory to `sys.path[0]`, so the generated `import <module>_pb2` resolves correctly. **No manual `sys.path` manipulation is needed.**

### Decision: Readiness verification

**Proven approach**: Use `sleep 2` or `sleep 3` after starting the server. This is simple and sufficient for this task family.

```bash
cd <work_dir> && python server.py &
sleep 2
```

**If polling is required** (e.g., strict readiness checks), you **must** use timeouts. gRPC channel creation is lazy and RPCs without timeouts will hang indefinitely when nothing is listening:

```python
# Correct: use channel_ready_future with timeout
ch = grpc.insecure_channel('localhost:<port>')
grpc.channel_ready_future(ch).result(timeout=2)

# Or: use per-call timeout
stub.<Method>(request, timeout=2)
```

**Pitfall**: Never poll gRPC without timeouts. A bare `stub.Method(request)` will wait for the default deadline (~minutes) when the server isn't ready, making your polling loop useless.

If the server fails to start, check:
- Working directory: are you running from the directory containing the generated `*_pb2.py` files?
- Port conflicts (another process on the same port)
- Import errors (proto compilation failures or wrong `-I` path)

---

## Verification Checklist

After implementation, systematically verify:

1. ✅ Proto compiles without errors
2. ✅ Generated Python imports resolve correctly
3. ✅ Server starts and stays running (doesn't exit)
4. ✅ Each RPC method responds correctly to basic calls
5. ✅ State persists across separate client channels
6. ✅ Missing keys return specified defaults
7. ✅ Namespaces/partitions are properly isolated
8. ✅ Delete semantics correct (existing vs missing)
9. ✅ Aggregates reflect current state after mutations
10. ✅ Concurrent requests don't corrupt state

---

## Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Wrong `-I` path in protoc | `ModuleNotFoundError: No module named '*_pb2'` | Set `-I` to directory containing the proto file |
| Missing `wait_for_termination()` | Server exits immediately | Add `server.wait_for_termination()` after `start()` |
| No thread lock | Intermittent wrong values under concurrent load | Wrap all state access in `with self.lock:` |
| Confusing implementation class with servicer base class | `TypeError` or wrong inheritance | Task-specified class (e.g., `Server`) inherits from generated `<ServiceName>Servicer` |
| Wrong servicer class name | `AttributeError` or `TypeError` | Check generated file: it's `<ServiceName>Servicer` |
| Wrong registration function | Server starts but RPCs return UNIMPLEMENTED | Use generated `add_<ServiceName>Servicer_to_server` |
| Proto filename hyphens | Import fails | Remember: hyphens → underscores in Python module names |
| Forgetting field numbers | Proto compilation error | Every field must have `= N;` with sequential numbers |
| Not handling missing keys | KeyError crashes | Use `.get(key, default)` or check existence first |
| Running server from wrong directory | `ModuleNotFoundError` for generated pb2 modules | Always `cd <dir> && python server.py` — Python adds script dir to sys.path automatically |
| Polling gRPC readiness without timeouts | Health check hangs indefinitely | Use `grpc.channel_ready_future(ch).result(timeout=N)` or per-call `timeout=N` |

---

## Adapting to Variation

### When RPC structure varies
- More RPCs: add more `rpc` lines and message definitions — same pattern
- Nested messages: define inner messages, use as field types
- Repeated fields: `repeated <type> name = N;` → accessed as Python lists
- Enums: define `enum`, use as field type, access as integer in Python

### When state semantics vary
- Conditional updates (CAS): check condition under lock, only mutate if condition holds
- Multi-key operations: operate on multiple keys within a single lock acquisition
- Reset/clear: `self.store.clear()` or `self.store[ns].clear()` under lock
- Different defaults: change the fallback value in `.get()` calls

### When runtime requirements vary
- Longer test windows: ensure `wait_for_termination()` keeps server alive
- Burst concurrency: increase `max_workers`, ensure lock granularity is sufficient
- Readiness checks: add a health-check RPC or poll the port before proceeding
- Multiple channels: state lives in the server process, shared across all channels automatically
