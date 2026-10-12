---
name: kv-store-grpc
description: >
  Build a stateful Python gRPC service from a task specification. Covers the
  full pipeline: installing grpcio/grpcio-tools, writing a .proto file with the
  required service/RPC/message definitions, generating Python bindings with
  protoc, implementing the servicer class with correct in-memory state
  semantics, and launching the server so it is reliably accepting connections
  when tests run. Generalizes across variation in RPC API structure (number of
  methods, field types, nested/repeated/enum/map fields), stateful service
  semantics (namespaces, conditional updates, aggregates, multi-key operations,
  deletes, resets), and runtime requirements (concurrency, startup readiness,
  long-lived sessions, repeated channel creation).
---

# Skill: Build a Stateful Python gRPC Service

## Overview

This skill covers the end-to-end construction of a Python gRPC server with
in-memory state, starting from a task instruction that specifies the proto
schema, service semantics, and runtime requirements. The workflow has five
phases: **install**, **proto**, **generate**, **implement**, and **launch**.

## Phase 1: Install Dependencies

Install `grpcio` and `grpcio-tools` system-wide with pip. The task instruction
will specify exact versions; if not, use a recent stable pair.

```bash
pip3 install grpcio==<version> grpcio-tools==<version>
```

**Key invariant**: The installed `grpcio-tools` version must match the version
used to generate code, and the generated `_grpc.py` file checks this at import
time. Always install before generating.

## Phase 2: Create the Proto File

Parse the task instruction to extract:
- **Proto file path** (e.g., `/app/kv-store.proto`)
- **Package name** (e.g., `kvstore`)
- **Service name** (e.g., `KVStore`)
- **RPC methods**: each with name, request message type, response message type
- **Message definitions**: each with field name, type, and field number

### Proto File Structure

```protobuf
syntax = "proto3";

package <package_name>;

service <ServiceName> {
  rpc <MethodName>(<RequestType>) returns (<ResponseType>);
  // ... more RPCs
}

message <RequestType> {
  <field_type> <field_name> = <field_number>;
  // ... more fields
}

message <ResponseType> {
  <field_type> <field_name> = <field_number>;
  // ... more fields
}
```

### Protobuf Field Type Reference

| Proto type | Python type (accessed as) |
|---|---|
| `string` | `str` |
| `int32`, `int64` | `int` |
| `uint32`, `uint64` | `int` |
| `float`, `double` | `float` |
| `bool` | `bool` |
| `bytes` | `bytes` |
| `enum` | `int` (use enum name for setting) |
| `repeated T` | `list` (use `.append()` or assign list) |
| `map<K,V>` | `dict`-like (use `msg.map_field[key] = val`) |
| nested message | sub-message instance |

### Naming Convention: Hyphens vs Underscores

When the proto filename contains hyphens (e.g., `kv-store.proto`), the
generated Python modules use underscores (`kv_store_pb2.py`,
`kv_store_pb2_grpc.py`). This is automatic protoc behavior. The import
statement in `server.py` must use the underscore form:

```python
import kv_store_pb2
import kv_store_pb2_grpc
```

### Enums

```protobuf
enum Status {
  UNKNOWN = 0;
  ACTIVE = 1;
  INACTIVE = 2;
}
```

In Python, enum values are accessed as integers. The first value must be 0
(proto3 requirement).

### Repeated Fields

```protobuf
message BatchRequest {
  repeated string keys = 1;
}
```

In Python, `request.keys` is a repeated scalar container. Iterate directly or
use `list(request.keys)`. To set: `request.keys.extend([...])` or
`request.keys.append(val)`.

### Map Fields

```protobuf
message ConfigUpdate {
  map<string, int32> updates = 1;
}
```

In Python, `request.updates` behaves like a dict.

## Phase 3: Generate Python Bindings

**Before generating**, clean up any stale Python cache to avoid import confusion:

```bash
rm -rf <proto_dir>/__pycache__
```

**Note**: Do NOT attempt to kill old server processes here. If there's a port conflict, Phase 5's Layer 1 port guard will handle it safely. Killing processes by scanning `/proc` can accidentally kill the solver's own process or parent shell, causing exit code 137 (SIGKILL).

Run protoc from the directory containing the .proto file:

```bash
cd <proto_dir>
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_file>.proto
```

This generates:
- `<module>_pb2.py` — message classes
- `<module>_pb2_grpc.py` — stub and servicer classes

**Critical**: The `<module>` name is derived from the proto filename with
hyphens replaced by underscores and the `.proto` extension replaced by `_pb2`.

**Stale cache warning**: If you previously generated bindings for a different
proto, the `__pycache__/` directory may contain `.pyc` files for old module
names. Always delete `__pycache__/` before regenerating to avoid import
confusion.

### Generated Code Structure

The `_pb2_grpc.py` file contains:
- `<ServiceName>Stub` — client-side stub (for testing)
- `<ServiceName>Servicer` — base class to extend for server implementation
- `add_<ServiceName>Servicer_to_server(servicer, server)` — registration function

## Phase 4: Implement the Servicer

Create `server.py` with a class that extends the generated servicer base class.

### Template

```python
import grpc
from concurrent import futures
import <module>_pb2
import <module>_pb2_grpc


class Server(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize in-memory state here
        # Common patterns:
        # - Flat dict: self._data = {}
        # - Namespaced: self._store = {}  # {namespace: {key: value}}
        # - Multiple collections: self._users = {}, self._sessions = {}
        self._state = ...

    def <Method1>(self, request, context):
        # Access request fields: request.<field_name>
        # Return response: <module>_pb2.<ResponseType>(<field>=<value>, ...)
        ...

    def <Method2>(self, request, context):
        ...


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    # Check return value: returns port number on success, 0 on failure
    port = server.add_insecure_port('[::]:<port>')
    if port == 0:
        raise RuntimeError('Failed to bind to port <port> — is another process using it?')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

### State Management Patterns

**Namespace isolation**: Use nested dicts `{namespace: {key: value}}`. Always
ensure the namespace dict exists before accessing:
```python
def _get_ns(self, namespace):
    if namespace not in self._store:
        self._store[namespace] = {}
    return self._store[namespace]
```

**Default values for missing keys**: Proto3 scalar fields default to 0/""/false.
When a key is missing from state, return the proto default (usually 0 for int32).

**Delete semantics**: Return both a success flag and the removed value. If key
doesn't exist, return `success=False` with default value. Use the
sentinel-based `pop` idiom to avoid TOCTOU races under concurrent deletes:
```python
_MISSING = object()  # sentinel — must not be None or 0 (both valid values)

def Delete(self, request, context):
    ns = self._get_ns(request.namespace)
    value = ns.pop(request.key, _MISSING)
    if value is _MISSING:
        return <module>_pb2.DeleteResponse(success=False, value=0)
    return <module>_pb2.DeleteResponse(success=True, value=value)
```
This is atomic under CPython's GIL for single dict operations. The sentinel
must be a unique object (not `None` or `0`) because those can be legitimate
stored values.

**Aggregate operations**: Sum/count over a collection. Return 0 for empty or
absent collections.

**Thread safety**: The `ThreadPoolExecutor` means multiple RPCs can execute
concurrently. Single dict operations (`get`, `pop`, `__setitem__`) are atomic
under CPython's GIL, but **check-then-act patterns are NOT atomic** — two
threads can both pass a `key in dict` check, then one `pop()` raises
`KeyError`. Use the sentinel `pop(key, sentinel)` idiom for delete-style
operations (see above). For multi-step compound operations (read-modify-write
across multiple keys, compare-and-swap, etc.), use an explicit lock:
```python
import threading
self._lock = threading.Lock()
# In methods:
with self._lock:
    # ... compound state mutation
```

### Handling Various Field Types in Implementation

- **Repeated fields**: `request.items` is iterable; build response with
  `response.items.extend([...])` or loop with `response.items.append(val)`
- **Map fields**: Access like dict `request.config["key"]`; build response with
  `response.config["key"] = val`
- **Nested messages**: Create sub-message instances:
  `response.detail = <module>_pb2.DetailMessage(field1=val1, ...)`
- **Enum fields**: Set with integer value or enum name:
  `response.status = <module>_pb2.ACTIVE`

## Phase 5: Launch the Server

This is the most failure-prone phase. The single most impactful failure mode
in this skill family is the **silent port-bind failure**: when an old server
still holds the port, `add_insecure_port()` may still return the port number
(not 0), and `server.start()` succeeds without raising an exception. The new
server appears to start successfully but the old server is the one actually
serving — causing `UNIMPLEMENTED / "Method not found!"` errors that are
extremely confusing because readiness checks pass.

The defense is a mandatory three-layer verification:

### Layer 1: Pre-launch port guard

Before starting the server, verify the port is free. If it is not, kill the
old server first.

```bash
python3 -c "
import socket, sys, os, signal, time

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
if s.connect_ex(('localhost', <port>)) == 0:
    print('Port <port> in use — killing old server')
    # Get own PID and parent PID to exclude from kill
    own_pid = os.getpid()
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('PPid:'):
                    ppid = int(line.split()[1])
                    break
    except:
        ppid = -1
    excluded = {str(own_pid), str(ppid)}
    for f in os.listdir('/proc'):
        if f.isdigit() and f not in excluded:
            try:
                with open(f'/proc/{f}/cmdline', 'r') as fh:
                    cmd = fh.read()
                    if 'server.py' in cmd:
                        os.kill(int(f), signal.SIGKILL)
            except: pass
    time.sleep(2)
    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if s2.connect_ex(('localhost', <port>)) == 0:
        print('FATAL: port still in use')
        sys.exit(1)
    s2.close()
    print('Old server killed, port freed')
else:
    print('Port <port> is free')
s.close()
"
```

**Critical**: The `os.getpid()` check alone is insufficient. The parent bash shell's PID must also be excluded because the bash command string contains "server.py". Without excluding the parent PID, the kill script will terminate the parent shell, causing exit code 137 (SIGKILL). Reading `/proc/self/status` to get the PPid prevents this.

### Layer 2: Launch and capture PID

Start the server in the background and capture its PID for liveness checking:

```bash
cd <app_dir> && python3 server.py &
SERVER_PID=$!
echo "Server started with PID $SERVER_PID"
```

### Layer 3: Post-launch verification (process + channel)

**3a. Verify the NEW process is alive** (didn't crash on startup):

```bash
sleep 1
kill -0 $SERVER_PID 2>/dev/null || { echo "ERROR: server process $SERVER_PID died"; exit 1; }
echo "Server process is alive"
```

**3b. Verify channel readiness** (the new server is accepting connections):

```bash
python3 -c "
import grpc, sys, time
sys.path.insert(0, '<app_dir>')
import <module>_pb2, <module>_pb2_grpc
ready = False
for i in range(20):
    try:
        ch = grpc.insecure_channel('localhost:<port>')
        grpc.channel_ready_future(ch).result(timeout=1)
        ready = True
        break
    except Exception:
        time.sleep(0.5)
if ready:
    print('Server ready on port <port>')
else:
    print('ERROR: server did not become ready')
    sys.exit(1)
"
```

### Why all three layers are necessary

- **Layer 1 alone** is not sufficient: a race could allow another process to
  grab the port between the check and the launch.
- **Layer 2 alone** is not sufficient: the process can start and block on
  `wait_for_termination()` even if port binding failed silently.
- **Layer 3a alone** is not sufficient: the process can be alive but serving
  on the wrong port or not serving at all.
- **Layer 3b alone** is not sufficient: `channel_ready_future` only confirms
  that *something* is accepting TCP connections on the port — it cannot
  distinguish the new correct server from an old stale one with different
  RPC methods registered.

Together, all three layers guarantee that the **new** server is the one
actually serving on the correct port.

### Port Binding

- Use `[::]:<port>` to bind on all interfaces (IPv4 + IPv6)
- The task instruction specifies the port number
- Common ports in test scenarios: 50051, 5328, 8080, etc.
- **Critical**: `add_insecure_port()` returns `0` on failure (e.g., port already
  bound) — the `serve()` template checks this and raises `RuntimeError`.
  However, it may sometimes return the port number even when already bound,
  and `server.start()` succeeds silently. The three-layer launch procedure
  (Phase 5) provides defense-in-depth against these subtle cases.

### Keeping the Server Alive

- `server.wait_for_termination()` blocks the main thread, keeping the process alive
- The background `&` allows the shell to continue for test execution
- Do NOT kill the server process until tests are complete

### Test Infrastructure Expectations

Tests are injected at runtime and typically:
1. Import the generated `_pb2` and `_pb2_grpc` modules from the app directory
2. Create an insecure channel to `localhost:<port>`
3. Create a stub using the generated `<ServiceName>Stub` class
4. Call RPC methods and assert on responses
5. May create multiple channels to test state persistence across connections

The server must already be running and accepting connections when tests begin.
Tests run in a separate process/shell (`run_tests_in_same_shell: false`), so
the server must be a persistent background daemon.

## Debugging Checklist

If tests fail, check these common issues **in this order**:

1. **Silent port-bind failure** (most impactful and most confusing): An old
   server is still holding the port. `add_insecure_port()` may return `0`
   (caught by the `serve()` template's check) or may silently return the
   port number. In the latter case, `server.start()` succeeds, and
   `channel_ready_future` passes — but the old server is the one answering
   RPCs, so methods return `UNIMPLEMENTED / "Method not found!"`. Fix: use
   the three-layer launch procedure (Phase 5), especially the pre-launch
   port guard (Layer 1) which detects and kills the old server.
2. **Import errors**: Module name mismatch (hyphens vs underscores)
3. **Server not started**: Forgot to launch `server.py` in background
4. **State not persisting**: Creating new Server instance per request instead of
   one shared instance
5. **Wrong field numbers**: Proto field numbers don't match instruction
6. **Missing default handling**: Not returning 0/empty for missing keys
7. **Version mismatch**: grpcio version differs from grpcio-tools version
8. **Concurrency bugs**: TOCTOU races in check-then-pop patterns (use sentinel
   idiom) or multi-step compound operations (use `threading.Lock`)

## Complete Worked Example Pattern

Given a task instruction specifying:
- Proto file: `/app/service.proto`
- Service: `MyService` on port `50051`
- RPCs: `Get(GetRequest) -> GetResponse`, `Set(SetRequest) -> SetResponse`
- State: flat key-value store, string keys, int32 values, default 0

The implementation sequence is:

```bash
# 1. Install
pip3 install grpcio==1.73.0 grpcio-tools==1.73.0

# 2. Create proto
cat > /app/service.proto << 'EOF'
syntax = "proto3";
package myservice;
service MyService {
  rpc Get(GetRequest) returns (GetResponse);
  rpc Set(SetRequest) returns (SetResponse);
}
message GetRequest { string key = 1; }
message GetResponse { int32 value = 1; }
message SetRequest { string key = 1; int32 value = 2; }
message SetResponse { int32 value = 1; }
EOF

# 3. Generate
cd /app && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. service.proto

# 4. Implement server.py (extend MyServiceServicer, implement Get/Set)
#    Include port check in serve():
#    port = server.add_insecure_port('[::]:50051')
#    if port == 0: raise RuntimeError('Failed to bind port 50051')

# 5. Launch with three-layer verification:
#    Layer 1: Check port is free (kill old server if needed, exclude own PID + PPID)
#    Layer 2: Launch server and capture PID
#    Layer 3: Verify process alive + channel ready
```

## Variation Handling Guide

### When RPC API Structure Varies

- **More RPCs**: Add each to the service block and implement each method
- **Multiple fields per message**: List all fields with correct types and numbers
- **Nested messages**: Define inner messages, reference them by name
- **Repeated fields**: Use `repeated` keyword; handle as lists in Python
- **Enums**: Define enum type, use as field type; first value must be 0
- **Oneof**: Use `oneof` keyword; in Python, check `request.WhichOneof('name')`

### When State Semantics Varies

- **Multiple namespaces**: Nested dict `{ns: {key: val}}`
- **Conditional updates**: Check current state before writing (compare-and-swap)
- **Aggregate reads**: Sum/count/min/max over collections
- **Multi-key operations**: Batch get/set with repeated fields
- **Deletes with return**: Use sentinel-based `pop(key, _MISSING)` to avoid
  TOCTOU races under concurrent deletes
- **Reset/clear**: Clear dict or specific namespace
- **TTL/expiry**: Store timestamps alongside values, check on read

### When Runtime Requirements Vary

- **Concurrency**: Use `ThreadPoolExecutor(max_workers=N)` with higher N
- **Startup readiness**: Use `grpc.channel_ready_future()` to verify
- **Long-lived sessions**: Ensure `wait_for_termination()` is called
- **Burst handling**: Thread pool handles concurrent requests; add locks if needed
- **Repeated channel creation**: Server handles this naturally; each new channel
  connects to the same running server
