---
name: kv-store-grpc
description: >
  Build and deploy a Python gRPC stateful in-memory service from a task specification.
  Covers proto file creation, Python binding generation, server implementation with
  correct state semantics, and reliable server lifecycle management. Handles arbitrary
  RPC interface structures (unary RPCs with scalar, nested, repeated, enum fields),
  varied stateful service semantics (namespaces, aggregates, conditional updates,
  deletes, resets), and diverse runtime requirements (concurrent requests, long-lived
  sessions, readiness checks).
---

# KV-Store-gRPC Skill

## Overview

This skill builds a real Python gRPC server with in-memory state from a task specification.
Every task in this family requires the same pipeline:

1. Install `grpcio` and `grpcio-tools` at specified versions
2. Create a `.proto` file matching the exact service/message/RPC specification
3. Generate Python protobuf and gRPC bindings from the proto file
4. Implement the servicer class with correct in-memory state semantics
5. Start the server on the specified port and keep it running for tests

## Step-by-Step Procedure

### Step 1: Parse the Task Specification

Extract these elements from the task description (typically in `instruction` field):

| Element | What to look for | Example |
|---------|-----------------|---------|
| Proto file path | Where to create the .proto | `/app/kv-store.proto` |
| Service name | gRPC service identifier | `KVStore` |
| RPC methods | Name, request type, response type | `Put(PutRequest) -> PutResponse` |
| Message fields | Name, type, field number | `namespace` string field 1 |
| Generated file names | Expected output file paths | `/app/kv_store_pb2.py` |
| Server class name | Python class for the servicer | `Server` |
| Listen port | Port number | `5328` |
| State semantics | Data model, defaults, operations | Namespaced dict, default 0 |
| grpcio version | Package version to install | `1.73.0` |

### Step 2: Install Dependencies

```bash
pip install grpcio==<version> grpcio-tools==<version>
```

Always use the exact versions specified in the task. This ensures compatibility between the protoc code generator and the runtime.

### Step 3: Create the Proto File

Write a `.proto` file with this structure:

```protobuf
syntax = "proto3";

package <package_name>;

service <ServiceName> {
  rpc <Method1>(<Request1>) returns (<Response1>);
  rpc <Method2>(<Request2>) returns (<Response2>);
  // ... more RPCs ...
}

message <Request1> {
  <type> <field_name> = <field_number>;
  // ... more fields ...
}

message <Response1> {
  <type> <field_name> = <field_number>;
}
// ... more messages ...
```

**Proto type mapping reference:**

| Task description type | Proto type | Python type |
|----------------------|-----------|-------------|
| string | `string` | `str` |
| integer / int32 | `int32` | `int` |
| integer / int64 | `int64` | `int` |
| boolean / bool | `bool` | `bool` |
| float / double | `double` | `float` |
| list of X | `repeated X` | `RepeatedComposite` (list-like) |
| enum | `enum Name { ... }` | `int` constants |
| nested message | `message Inner { ... }` then use as field type | Sub-message object |
| map<K,V> | `map<K, V>` | Dict-like |

**Critical rules:**
- Field numbers must be unique within each message, starting from 1
- Match field names exactly as specified (case-sensitive)
- Match message and service names exactly as specified
- Always use `syntax = "proto3";`
- Proto filenames can contain hyphens; generated Python files convert hyphens to underscores
- The `package` directive in the proto file affects gRPC service routing metadata but does **not** change generated Python module names. Python module names are derived solely from the `.proto` filename (with hyphens→underscores). So `package kvstore;` and `package my_store;` both produce `kv_store_pb2.py` from `kv-store.proto`.

### Step 4: Generate Python Bindings

```bash
cd <proto_directory>
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <filename>.proto
```

This produces two files:
- `<filename_without_hyphens>_pb2.py` — protobuf message classes
- `<filename_without_hyphens>_pb2_grpc.py` — gRPC stub and servicer base classes

**Important naming detail:** If the proto file is `kv-store.proto`, the generated files are `kv_store_pb2.py` and `kv_store_pb2_grpc.py`. The `_pb2_grpc.py` file imports `kv_store_pb2` (with underscores). This automatic hyphen-to-underscore conversion is handled by protoc.

### Step 5: Implement the Server

Create the server file (typically `/app/server.py`) with this structure:

```python
import grpc
from concurrent import futures
import threading
import <module>_pb2
import <module>_pb2_grpc


class <ServerClassName>(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        self._lock = threading.Lock()
        # Initialize state based on task semantics
        # Examples:
        #   Simple KV: self._store = {}
        #   Namespaced: self._store = {}  # {namespace: {key: value}}
        #   Multi-collection: self._data = {}; self._index = {}

    def <RpcMethod>(self, request, context):
        with self._lock:
            # Access request fields as attributes: request.field_name
            # Implement the business logic
            # Return the response message:
            return <module>_pb2.<ResponseMessage>(field1=val1, field2=val2)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(<ServerClassName>(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

**Key implementation details:**
- The servicer class must extend `<module>_pb2_grpc.<ServiceName>Servicer`
- Each RPC method name must exactly match the proto RPC name
- Request fields are accessed as Python attributes (e.g., `request.namespace`)
- Response is constructed by calling the response message class with keyword arguments
- Always use `threading.Lock()` around state access for thread safety under concurrent requests
- Use `max_workers=10` (or higher) in `ThreadPoolExecutor` to handle concurrent requests

**Multiple services in one proto file:** If the proto defines multiple services, you must:
1. Create a separate servicer class for each service (each extending its respective `<ServiceName>Servicer` base)
2. Register each servicer with the server using its own `add_<ServiceName>Servicer_to_server()` call
3. Each service can share state or have independent state, depending on the task requirements

Example for two services:
```python
class ServiceAServicer(module_pb2_grpc.ServiceAServicer):
    # implement RPCs for ServiceA
    pass

class ServiceBServicer(module_pb2_grpc.ServiceBServicer):
    # implement RPCs for ServiceB
    pass

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    module_pb2_grpc.add_ServiceAServicer_to_server(ServiceAServicer(), server)
    module_pb2_grpc.add_ServiceBServicer_to_server(ServiceBServicer(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()
```

### Step 6: Start the Server and Verify

**CRITICAL: The server must be running when this step completes.** The evaluation test harness (pytest) connects to the server *after* the agent exits. If the server process dies when the agent's shell session ends, every test fails with `UNAVAILABLE: failed to connect to all addresses`. This is the single most common failure mode for gRPC skills.

#### 6a. Kill any stale servers on the target port

Before starting the server, ensure no other process is using the target port. This is critical if:
- You're restarting the server after fixing a bug
- A previous agent attempt left a server running
- You're testing on a shared system

```bash
# Find and kill any process listening on the target port
PORT=<port>
PID=$(lsof -ti:$PORT 2>/dev/null || fuser $PORT/tcp 2>/dev/null | tr -d ' ')
if [ -n "$PID" ]; then
  kill -9 $PID 2>/dev/null || true
  sleep 1
fi
```

If `lsof` or `fuser` are not available, you can use `pkill` to kill by process name:
```bash
pkill -9 -f "python.*server.py" 2>/dev/null || true
sleep 1
```

**Important**: Only kill stale servers *before* starting the new one. Once the correct server is running and verified, **never kill it** (see 6e below).

#### 6b. Launch with shell-exit survival

Use `nohup` + `disown` to ensure the process survives shell exit:

```bash
cd /app
nohup python server.py > /tmp/server.log 2>&1 &
disown
```

- `nohup` makes the process ignore SIGHUP (sent when the shell exits).
- `disown` removes the job from the shell's job table, preventing the shell from sending it any signal on exit.
- Together they guarantee the server stays alive after the agent's session ends.

**Note on Python command**: Use `python` if available, otherwise `python3`. Both should work in most environments, but `python3` is more explicit and portable.

#### 6c. Wait for readiness AND verify with an RPC-based retry loop

Do not rely on a fixed `sleep` or a channel-creation check — `grpc.insecure_channel()` is **lazy** in Python and does not establish a TCP connection until you make an RPC call. A channel-creation check will always succeed as long as the `grpc` module is importable, regardless of whether the server is actually listening.

The only reliable test of gRPC server readiness is a **real RPC call with a timeout**. Merge readiness waiting and verification into a single loop:

```bash
cd /app
PORT=<port>
MAX_RETRIES=15
RETRY_DELAY=1

for i in $(seq 1 $MAX_RETRIES); do
  if python3 -c "
import grpc, <module>_pb2, <module>_pb2_grpc
ch = grpc.insecure_channel('localhost:$PORT')
stub = <module>_pb2_grpc.<ServiceName>Stub(ch)
stub.<SimpleRpc>(<module>_pb2.<SimpleRequest>(...), timeout=5)
ch.close()
print('ready')
" 2>/dev/null; then
    echo "Server verified ready (attempt $i)"
    break
  fi
  if [ $i -eq $MAX_RETRIES ]; then
    echo "Server failed to start after $MAX_RETRIES attempts"
    cat /tmp/server.log
    exit 1
  fi
  sleep $RETRY_DELAY
done
```

This loop does three things at once:
1. **Waits** for the server to bind the port and start accepting connections
2. **Verifies** the server can actually serve RPCs (catches import errors, crashes, logic bugs)
3. **Retries** with backoff, adapting to slow-starting servers

If the server has a bug that causes RPCs to crash, you'll catch it here rather than discovering it only after the agent exits.

**Choosing the verification RPC**: Pick the simplest RPC in the service — one that requires minimal or no state setup. For example, a `Fetch` or `Get` RPC with a key that doesn't exist (expecting a default value response) is ideal because it doesn't depend on any prior state. If all RPCs require state, use a `Put` to set a known value and verify the response.

#### 6d. Optional: deeper functional verification

After the server is confirmed ready by step 6c, you may optionally run additional RPC calls to verify more complex behavior (e.g., state persistence across calls, namespace isolation, default values). This is not required for the server to be "ready" — step 6c already confirmed that — but it can catch logic bugs early:

```python
import grpc
import <module>_pb2
import <module>_pb2_grpc

channel = grpc.insecure_channel('localhost:<port>')
stub = <module>_pb2_grpc.<ServiceName>Stub(channel)

# Test state persistence: put a value, then fetch it
stub.<PutRpc>(<module>_pb2.<PutRequest>(...))
resp = stub.<FetchRpc>(<module>_pb2.<FetchRequest>(...))
assert resp.<value_field> == <expected>, f"Expected {<expected>}, got {resp.<value_field>}"

# Test default for missing key
resp = stub.<FetchRpc>(<module>_pb2.<FetchRequest>(...))
assert resp.<value_field> == <default>, f"Expected default {<default>}, got {resp.<value_field>}"

channel.close()
print('All functional checks passed')
```

If any check fails, check `/tmp/server.log` for errors, fix the issue, and restart from step 6a.

#### 6e. NEVER kill the server after verification

**Do not** run `kill %1`, `pkill -f server.py`, or any command that stops the server process after you have verified it is working. The server must remain running when the agent's trajectory ends. The evaluation tests run *after* the agent finishes.

If you need to restart during development (before final verification):
- Go back to step 6a and repeat the full startup sequence
- Only stop when you have a verified, running server that you will not touch again

The final state of the trajectory must be: server process running, port listening, accepting connections.

## State Semantics Patterns

### Pattern: Simple Key-Value Store
```python
self._store = {}  # {key: value}
# Put: self._store[key] = value
# Get: self._store.get(key, default)
# Delete: self._store.pop(key, None)
```

### Pattern: Namespaced Key-Value Store
```python
self._store = {}  # {namespace: {key: value}}
# Put: self._store.setdefault(ns, {})[key] = value
# Get: self._store.get(ns, {}).get(key, default)
# Delete: pop from inner dict
# Namespace total: sum(self._store.get(ns, {}).values())
```

### Pattern: Multi-Collection / Indexed Store
```python
self._data = {}     # primary storage
self._index = {}    # secondary index
# Maintain both structures in sync under the lock
```

### Pattern: Aggregate / Running Total
```python
self._store = {}
self._totals = {}   # {namespace: running_sum}
# On Put: update both _store and _totals
# On Delete: update both _store and _totals
# ListTotal: return self._totals.get(ns, 0)
```

### Default Value Handling

Common defaults specified in tasks:
- Missing integer key → `0`
- Missing string key → `""`
- Missing boolean → `false`
- Empty namespace total → `0`
- Delete nonexistent → `success=false, value=<default>`

Always implement defaults in the **server logic**, not in proto (proto3 already zero-initializes unset fields, but the task may specify different behavior).

## Handling Variation Axes

### Axis 1: RPC API Structure Complexity

The skill adapts to any proto complexity:

- **More RPCs**: Each becomes a method on the servicer class. The pattern is identical.
- **Complex request/response messages**: Multiple fields, nested messages, repeated fields — all handled by defining the messages correctly in proto and accessing them as attributes in Python.
- **Enums**: Define in proto, use integer values in Python. Access via `<module>_pb2.<EnumName>.<VALUE>`.
- **Oneof fields**: Use `request.HasField('field_name')` to check which variant is set.
- **Map fields**: Access like Python dicts.

### Axis 2: Stateful Service Semantics

The skill adapts to any state model:

- **Different data structures**: Choose the right Python data structure (dict, list, set, nested dicts) based on what the semantics require.
- **Different operations**: Implement each operation (create, read, update, delete, aggregate, conditional) correctly.
- **Namespace isolation**: Use nested dicts or composite keys to isolate state.
- **Conditional updates**: Check conditions before modifying state, all under the lock.
- **Reset/clear**: Re-initialize data structures.

### Axis 3: Runtime Interaction Requirements

The skill ensures reliability under various conditions:

- **Long-lived sessions**: `server.wait_for_termination()` keeps the server running indefinitely.
- **Concurrent requests**: `ThreadPoolExecutor(max_workers=10)` handles parallelism; `threading.Lock()` ensures state consistency.
- **Startup readiness**: Use an RPC-based retry loop (see Step 6c) to wait for the server to become ready, rather than a fixed `sleep`. This adapts to varying startup times and catches immediate failures.
- **Repeated channel creation**: gRPC naturally handles new connections; no special code needed.
- **Burst traffic**: The thread pool absorbs bursts; the lock serializes state access safely.
- **Server crash recovery**: Use `nohup` and log to file for debugging. If needed, implement a wrapper that restarts on failure.

## Common Pitfalls and Fixes

1. **Import errors in generated code**: Proto filenames with hyphens produce Python files with underscores. `kv-store.proto` → `kv_store_pb2.py`. The `_pb2_grpc.py` imports `kv_store_pb2` (underscores). Always use the underscore version in Python imports.

2. **Field number conflicts**: Each field in a message must have a unique number. Numbers are per-message, not global.

3. **Wrong servicer base class**: The generated base class is `<module>_pb2_grpc.<ServiceName>Servicer`. Make sure to extend this exact class.

4. **Server not binding to port**: Use `[::]:port` for dual-stack binding. Check that no other process uses the port.

5. **State not persisting across calls**: The servicer instance is created once in `serve()` and reused for all requests. Don't create a new servicer per request.

6. **Race conditions**: Without `threading.Lock()`, concurrent requests can corrupt dict state. Always lock around read-modify-write sequences.

7. **Proto3 default values**: Proto3 zero-initializes all fields. If the task says "Fetch returns 0 for missing key", this is the proto3 default — but you still need explicit logic to return 0 when the key is not in your store.

8. **Blocking the server thread**: Don't do long operations in RPC handlers. The ThreadPoolExecutor handles concurrency, but blocking all workers will stall the server.

9. **Server killed or dies on shell exit (MOST CRITICAL)**: If you use `python server.py &` without `nohup`, the server receives SIGHUP when the agent's shell exits and dies. The evaluation harness then fails to connect. Always use `nohup python server.py > /tmp/server.log 2>&1 &` followed by `disown`. Never kill the server after starting it — the evaluation tests run *after* the agent finishes.

10. **Port already in use**: If a stale server from a previous attempt is still running on the target port, the new server will fail to bind with error `OSError: [Errno 98] Address already in use`. Always check for and kill stale servers before starting (see Step 6a). Use `lsof -ti:<port>`, `fuser <port>/tcp`, or `pkill -f server.py` to find and kill stale processes.

11. **Lazy channel creation is not a readiness check**: `grpc.insecure_channel()` in Python is lazy — it creates a channel object without establishing a TCP connection. The connection only happens when you make an RPC call. A check that only creates and closes a channel will always succeed as long as the `grpc` module imports, regardless of whether the server is listening. Always use a real RPC call with a timeout to verify server readiness (see Step 6c).

## Verification Checklist

Before declaring the task complete:
- [ ] `grpcio` and `grpcio-tools` installed at specified versions
- [ ] Proto file created with correct syntax, messages, service, and RPCs
- [ ] Field names, types, and numbers match specification exactly
- [ ] Generated Python files exist and are importable
- [ ] Server class extends the correct generated servicer base
- [ ] All RPC methods implemented with correct names and semantics
- [ ] State persistence works across multiple calls
- [ ] Default values returned correctly for missing/absent data
- [ ] Thread-safe state access (lock around state mutations)
- [ ] **Stale servers killed before starting** (no port conflicts)
- [ ] **Server launched with `nohup` + `disown`** (survives shell exit)
- [ ] **Server readiness verified with RPC-based retry loop** (real RPC call with timeout, not just channel creation or fixed sleep)
- [ ] **Server process NOT killed** — it must be running when the agent exits
