---
name: kv-store-grpc
description: >
  Build and deploy a stateful Python gRPC service from a proto specification.
  Covers proto file authoring, Python binding generation, servicer implementation
  with in-memory state management, and robust server startup on a designated port.
  Handles arbitrary RPC structures (unary RPCs, nested/repeated/enum fields),
  varied stateful semantics (namespaced stores, aggregates, conditional updates,
  deletes), and runtime requirements (concurrent requests, persistent state across
  client channels, long-lived server processes).
---

# Python gRPC Stateful Service Construction

## Overview

This skill builds a running Python gRPC server from a task specification that defines:
- A `.proto` file with service, RPCs, and message definitions
- In-memory state semantics (how data is stored, read, written, deleted, aggregated)
- A port number and runtime requirements

## Step-by-Step Procedure

### 1. Install Dependencies

```bash
pip install grpcio==<version> grpcio-tools==<version>
```

Use the exact versions specified in the task. If no version is specified, use a recent stable pair (e.g., `grpcio==1.73.0 grpcio-tools==1.73.0`). Both packages must match in major.minor version.

### 2. Create the Proto File

Write the `.proto` file at the path specified by the task (typically `/app/<name>.proto`).

**Proto file structure:**
```protobuf
syntax = "proto3";
package <package_name>;

service <ServiceName> {
  rpc <MethodName>(<RequestMessage>) returns (<ResponseMessage>);
  // ... more RPCs
}

message <RequestMessage> {
  <type> <field_name> = <field_number>;
  // ... more fields
}

message <ResponseMessage> {
  <type> <field_name> = <field_number>;
}
```

**Key rules:**
- Field numbers must be unique within a message and match the spec exactly
- Field numbers start at 1
- Use `int32` for integers, `string` for text, `bool` for booleans
- For nested messages, define them separately and reference by name
- For repeated fields: `repeated <type> <name> = <number>;`
- For enums: define the enum block, then use the enum name as a field type
- The proto filename can contain hyphens; protoc will convert them to underscores in generated Python filenames

### 3. Generate Python Bindings

```bash
cd /app
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_file>.proto
```

This produces:
- `<proto_name>_pb2.py` — message classes
- `<proto_name>_pb2_grpc.py` — stub, servicer, and registration functions

**Critical naming detail:** If the proto file is `kv-store.proto`, the generated files are `kv_store_pb2.py` and `kv_store_pb2_grpc.py` (hyphens → underscores).

**Verify generation succeeded** by checking both files exist and are non-empty.

### 4. Implement the Servicer

Create `server.py` (or whatever filename the task specifies).

**Structure:**
```python
import grpc
from concurrent import futures
import <proto_name>_pb2
import <proto_name>_pb2_grpc

class Server(<proto_name>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize in-memory state here
        self._store = {}  # or whatever structure the semantics require

    def <MethodName>(self, request, context):
        # Access request fields as attributes: request.field_name
        # Return the response message type
        return <proto_name>_pb2.<ResponseMessage>(field=value)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <proto_name>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

**State management patterns:**

| Semantic Requirement | Implementation Pattern |
|---|---|
| Key-value store | `dict[key] = value`, `.get(key, default)` |
| Namespaced/isolated collections | `dict[namespace][key]` — nested dicts |
| Default for missing keys | `.get(key, default_value)` — typically 0 for int |
| Delete with return | Check existence, pop and return, or return failure |
| Aggregate (sum, count) | Iterate over values, compute, return |
| Conditional update | Check current state before modifying |
| Multi-key operations | Iterate over dict items or keys |

**Critical: Classify operations by mutation guarantee, not just read vs write.**

The rule isn't "writes use `_ns_write`, reads use `.get()`" — it's "only use `_ns_write()` when you're guaranteed to write regardless of current state."

| Operation Type | Pattern | Rationale |
|---|---|---|
| Unconditional write (Put) | `_ns_write(ns)` | Always creates/overwrites — namespace must exist |
| Conditional write (Delete) | `.get(ns, {})` | Only modifies if target exists — don't create phantom ns |
| Read (Fetch, aggregate) | `.get(ns, {})` | Never modifies — don't create phantom ns |

Both conditional writes and reads share the same `.get()` pattern. The key question: **does this RPC always write, or only sometimes?**

```python
def _ns_write(self, namespace):
    """Only for unconditional writes — creates namespace if missing."""
    if namespace not in self._store:
        self._store[namespace] = {}
    return self._store[namespace]

def Put(self, request, context):
    # Unconditional write: always creates/overwrites
    ns = self._ns_write(request.namespace)
    ns[request.key] = request.value
    return ...

def Delete(self, request, context):
    # Conditional write: only modifies if key exists
    ns = self._store.get(request.namespace, {})
    if request.key in ns:
        value = ns.pop(request.key)
        return ...Response(success=True, value=value)
    else:
        return ...Response(success=False, value=0)

def Fetch(self, request, context):
    # Read: never modifies
    ns = self._store.get(request.namespace, {})
    return ...Response(value=ns.get(request.key, 0))

def ListNamespaceTotal(self, request, context):
    # Read: never modifies
    ns = self._store.get(request.namespace, {})
    return ...Response(total=sum(ns.values()))
```

This framing transfers to harder variants:
- `Increment(key, delta)`: conditional write (key must exist) → `.get()`
- `PutIfAbsent(key, value)`: conditional write (key must not exist) → `.get()`
- `Replace(key, new_value)`: conditional write (key must exist) → `.get()`

Phantom empty dicts from incorrect mutations cause incorrect behavior in any variant that enumerates namespaces, checks namespace existence, or reports namespace-level metadata.

**Important state invariants:**
- State lives in the `Server` instance — it persists across all RPC calls
- State persists across different client channels connecting to the same server
- Use a single `Server()` instance passed to `add_*_to_server` — do NOT create a new instance per request
- For thread safety with concurrent requests, Python's GIL protects simple dict operations; for complex multi-step operations, consider using `threading.Lock`

### 5. Start the Server (Self-Cleaning Pattern)

**Critical insight**: Each `task_shell` call runs in an isolated shell session. Background processes started in one shell become orphans when that shell exits. Shell-level kill commands (`fuser -k`, `pkill`) are fragile because they operate in the current shell's context, not across sessions.

**The robust solution**: Embed the cleanup inside the server code itself. When `python3 server.py` runs, it self-cleans before binding:

```python
import subprocess, signal, os, time

def kill_existing_server(port):
    """Kill any process already bound to our port."""
    try:
        result = subprocess.run(
            ['fuser', f'{port}/tcp'],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            for pid in result.stdout.strip().split():
                try:
                    os.kill(int(pid.strip()), signal.SIGKILL)
                except (ValueError, ProcessLookupError):
                    pass
    except FileNotFoundError:
        # fuser not available
        pass

def serve():
    kill_existing_server(<port>)
    time.sleep(0.5)
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    ...
    port = server.add_insecure_port('[::]:<port>')
    if port == 0:
        raise RuntimeError("Failed to bind port — is another server running?")
    server.start()
    server.wait_for_termination()
```

This way, when the test harness (or any client) runs `python3 server.py`, the server **self-cleans** before binding. No external kill step needed.

**Start the server:**
```bash
cd /app && python3 server.py &
sleep 2
```

**After starting, verify the server is ready:**
```python
import grpc
channel = grpc.insecure_channel('localhost:<port>')
grpc.channel_ready_future(channel).result(timeout=5)
```

### 6. Verification

Write a quick test client to verify all RPCs work correctly:

```python
import grpc
import <proto_name>_pb2
import <proto_name>_pb2_grpc

channel = grpc.insecure_channel('localhost:<port>')
stub = <proto_name>_pb2_grpc.<ServiceName>Stub(channel)

# Test each RPC method
response = stub.<MethodName>(<proto_name>_pb2.<RequestMessage>(field=value))
assert response.field == expected_value

# Test state persistence across channels
channel.close()
channel2 = grpc.insecure_channel('localhost:<port>')
stub2 = <proto_name>_pb2_grpc.<ServiceName>Stub(channel2)
# State should still be present
```

## Common Pitfalls

1. **Proto filename vs generated module name**: Hyphens in `.proto` filenames become underscores in generated Python modules. Import using the underscore version.

2. **Field numbers must match exactly**: The test harness will use the generated protobuf classes with specific field numbers. If your proto has wrong field numbers, serialization will be incompatible.

3. **Server must be a long-lived background process**: Use `&` to background it. The test harness will connect as a separate client process. The server must remain running throughout the test window.

4. **`wait_for_termination()`**: This blocks the main thread, keeping the server alive. Without it (or `server.start()` alone), the script would exit immediately.

5. **Port binding**: Use `'[::]:<port>'` to listen on all interfaces (both IPv4 and IPv6). Using `'localhost:<port>'` may fail for some client connection patterns.

6. **State initialization**: Initialize all state in `__init__`. Do not use class-level mutable state (shared across instances) unless intentionally sharing.

7. **Response construction**: Always return the correct response message type. Use keyword arguments matching the proto field names.

8. **Missing key defaults**: The spec typically defines what to return for missing data (often 0 for integers, empty for strings, false for bools). Implement these explicitly.

9. **Classify operations by mutation guarantee, not just read vs write**: The rule isn't "writes use `_ns_write`, reads use `.get()`" — it's "only use `_ns_write()` when you're guaranteed to write regardless of current state." Unconditional writes (Put) use `_ns_write()`. Conditional writes (Delete, Increment, PutIfAbsent) and reads (Fetch, aggregates) both use `.get(ns, {})` to avoid creating phantom namespace entries. Ask: "does this RPC always write, or only sometimes?"

10. **Shell sessions are isolated**: Each `task_shell` call runs in a new shell. Background processes from previous calls become orphans. Don't rely on shell-level kill commands (`fuser -k`, `pkill`) for cross-session process management — embed the cleanup inside the server code itself using `fuser` to find and kill processes bound to the port before starting.

## Handling Variation Dimensions

### RPC Structure Variation
- **More RPCs**: Simply add more `rpc` lines in the service block and corresponding `def` methods in the servicer
- **Nested messages**: Define inner message types, reference them by name in other messages
- **Repeated fields**: Use `repeated` keyword; access as Python lists in generated code
- **Enums**: Define enum blocks; use in message fields; access as integer values in Python
- **Oneof**: Use `oneof` blocks; check which field is set with `HasField()`

### State Semantics Variation
- **Multiple namespaces**: Use nested dicts `{namespace: {key: value}}`
- **Aggregate operations**: Iterate over values with `sum()`, `len()`, etc.
- **Conditional operations**: Check preconditions before modifying state — use `.get(ns, {})` pattern, not `_ns_write()`
  - `Delete`: only remove if key exists
  - `Increment`: only modify if key exists
  - `PutIfAbsent`: only write if key does NOT exist
  - `Replace`: only modify if key exists
- **Delete semantics**: Return both success flag and the removed value (or default)
- **Reset/clear operations**: Re-initialize the relevant portion of state

### Runtime Requirements Variation
- **Concurrency**: `ThreadPoolExecutor(max_workers=N)` with N ≥ 10 handles typical test loads
- **Startup readiness**: Add `sleep(2)` after starting before running tests
- **Long-lived tests**: `wait_for_termination()` ensures the server stays up
- **Multiple client channels**: State lives in the server process, not in channels — this works automatically
- **Thread safety for compound operations**: If an RPC must perform multiple state mutations atomically (e.g., check-then-act), use `threading.Lock`:
  ```python
  import threading
  class Server(...):
      def __init__(self):
          self._lock = threading.Lock()
          self._store = {}
      def SomeRPC(self, request, context):
          with self._lock:
              # compound read-modify-write is atomic
  ```

## Additional Technical Notes

### Import Path for Generated Code
The generated `_pb2_grpc.py` file imports the `_pb2` module using a bare name (e.g., `import kv_store_pb2`). This means `server.py` must either:
- Live in the same directory as the generated files, OR
- Have the directory added to `sys.path` before importing

The simplest approach: keep `server.py` in the same directory as the proto and generated files (typically `/app/`).

### Protoc Working Directory
Run `protoc` from the directory containing the `.proto` file with `-I.` so that import paths resolve correctly. The generated files will be placed in the same directory.

### Server Graceful Shutdown
For test scenarios where the server must be stopped and restarted, consider catching SIGTERM:
```python
import signal, sys
def handle_sigterm(*args):
    server.stop(grace=5)
    sys.exit(0)
signal.signal(signal.SIGTERM, handle_sigterm)
```

### Verifying Server Health
After starting the server, a reliable health check:
```python
import grpc
channel = grpc.insecure_channel(f'localhost:{port}')
try:
    grpc.channel_ready_future(channel).result(timeout=5)
    print('Server is ready')
except grpc.FutureTimeoutError:
    print('Server not ready')
```
