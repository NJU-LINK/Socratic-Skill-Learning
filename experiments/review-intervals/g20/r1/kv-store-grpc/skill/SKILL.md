---
name: kv-store-grpc
description: >
  Build a real Python gRPC stateful service from a proto specification.
  Covers: writing proto3 definitions with arbitrary service/RPC/message structures,
  generating Python bindings, implementing servicer classes with in-memory state
  semantics, and running a robust gRPC server. Handles variation in RPC API
  complexity, stateful service semantics, and runtime/serving requirements.
---

# Python gRPC Stateful Service Construction

## Quick Reference Checklist

For each task, execute these steps in order:

1. **Install**: `pip install grpcio==<ver> grpcio-tools==<ver>`
2. **Proto**: Write `<name>.proto` with syntax, package, service, RPCs, messages
3. **Generate**: `python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <name>.proto`
4. **Server**: Implement servicer with `threading.Lock`, Server class, readiness probe
5. **Launch**: `python3 server.py &` then verify with readiness check
6. **Test**: Verify all RPCs, state persistence, namespace isolation, defaults

## Phase 1: Install Dependencies

```bash
pip install grpcio==<version> grpcio-tools==<version>
```

Use exact versions from task. If unspecified, use `grpcio>=1.60.0` with matching `grpcio-tools`.

## Phase 2: Write the Proto File

### Proto3 Skeleton

```protobuf
syntax = "proto3";

package <package_name>;

service <ServiceName> {
  rpc <MethodA>(<RequestA>) returns (<ResponseA>);
  // ... more RPCs
}

message <RequestA> {
  <type> <field_name> = <field_number>;
  // ... more fields
}

message <ResponseA> {
  <type> <field_name> = <field_number>;
}
```

### Critical Rules

**Field numbers**: Start at 1, unique within each message. Define wire format.

**Type mapping** (proto3 → Python):
- `string` → `str`
- `int32`, `int64`, `uint32`, `uint64` → `int`
- `float`, `double` → `float`
- `bool` → `bool`
- `bytes` → `bytes`
- `repeated <type>` → `list`
- Nested message → nested object
- `enum` → `int` (first value must be 0)
- `map<K,V>` → `dict`

**Proto3 zero-defaults** (critical for "missing" semantics):

| Type | Default |
|------|---------|
| `int32`, `int64`, etc. | `0` |
| `float`, `double` | `0.0` |
| `string` | `""` |
| `bool` | `False` |
| `bytes` | `b""` |
| message | `None` |
| `repeated` | `[]` |
| `map` | `{}` |

**Check**: Does the spec's "missing" return value match the proto3 default? If not, set it explicitly.

**Naming**: Proto file `my-service.proto` → generated `my_service_pb2.py` (hyphens become underscores).

### Handling RPC Structure Variation

**Multiple services**: Each generates separate `*Servicer` and `add_*_to_server`

**Nested messages**: Define separately, reference by name
```protobuf
message Address {
  string street = 1;
  string city = 2;
}

message Person {
  string name = 1;
  Address address = 2;  // Nested message
}
```
In Python: `request.address.street` accesses nested fields.

**Repeated fields**: Use `repeated` keyword
```protobuf
message TagList {
  repeated string tags = 1;
}
```
In Python: `request.tags` is a list. Iterate with `for tag in request.tags:`

**Enums**: First value must be 0
```protobuf
enum Status {
  UNKNOWN = 0;
  ACTIVE = 1;
  INACTIVE = 2;
}

message Item {
  Status status = 1;
}
```
In Python: `request.status` is an int. Compare with `kv_store_pb2.ACTIVE`.

**Map fields**: Become Python dicts
```protobuf
message Metadata {
  map<string, string> labels = 1;
}
```
In Python: `request.labels` is a dict. Access with `request.labels['key']`.

**Oneof**: Mutually exclusive fields
```protobuf
message Filter {
  oneof criteria {
    string name = 1;
    int32 age = 2;
  }
}
```
In Python: Check which field is set with `request.WhichOneof('criteria')`. Returns the field name as a string, or `None` if not set.

## Phase 3: Generate Python Bindings

```bash
cd <working_directory>
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <file>.proto
```

Produces:
- `<name>_pb2.py` — message classes
- `<name>_pb2_grpc.py` — stub (client) and servicer (server) base classes

**Critical**: Run from the directory containing the proto file. The `-I.` flag sets import path. Generated `_pb2_grpc.py` imports `_pb2` using underscore-converted filename.

## Phase 4: Implement the Server

### Thread Safety Is Mandatory

gRPC uses `ThreadPoolExecutor` — multiple requests execute simultaneously. **All mutable shared state must be protected with `threading.Lock`.**

**Why**: Check-then-act patterns are inherently unsafe under concurrency. The GIL does NOT protect multi-step operations. Race conditions are non-deterministic — absence in testing ≠ safety. Correctness is established by design (locks), not testing.

**Cost**: Lock overhead is microseconds. Race cost is silent corruption. **Always lock.**

### Servicer Template

```python
import grpc
import threading
from concurrent import futures
import <name>_pb2
import <name>_pb2_grpc


class MyServicer(<name>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        self._lock = threading.Lock()  # ALWAYS include for mutable state
        self._data = {}  # Initialize state

    def <MethodA>(self, request, context):
        with self._lock:  # ALL state access inside lock
            # Access: request.<field_name>
            # Return: <name>_pb2.<ResponseA>(<field>=<value>)
            ...
```

**Lock granularity**: One lock per servicer is fine for simple stores. Acquire per-method. Even read-only operations need the lock if state can change concurrently.

### State Management Patterns

| Requirement | Implementation |
|-------------|----------------|
| Key-value store | `dict` |
| Namespaced collections | `dict[str, dict[...]]` |
| Default for missing | `.get(key, default)` |
| Aggregates (sum, count) | `sum()`, `len()` |
| Delete with return | `dict.pop(key, default)` |
| Reset/clear | `self._data.clear()` or `del self._data[ns]` |
| Conditional updates | Check condition, then modify — **all inside the lock** |
| Multi-key ops | Iterate/batch — **all inside the same lock acquisition** |

**Atomic multi-step operations**: When a variant requires read-modify-write or multi-key operations, the lock must cover the **entire sequence**, not just individual steps. Example:

```python
def Increment(self, request, context):
    with self._lock:  # Lock covers the entire read-modify-write
        ns_data = self._data.get(request.namespace, {})
        current = ns_data.get(request.key, 0)
        new_value = current + request.amount
        if request.namespace not in self._data:
            self._data[request.namespace] = {}
        self._data[request.namespace][request.key] = new_value
        return kv_store_pb2.IncrementResponse(value=new_value)

def ConditionalSet(self, request, context):
    """Set only if current value < new value."""
    with self._lock:  # Lock covers check + set atomically
        ns_data = self._data.get(request.namespace, {})
        current = ns_data.get(request.key, 0)
        if current < request.value:
            if request.namespace not in self._data:
                self._data[request.namespace] = {}
            self._data[request.namespace][request.key] = request.value
            return kv_store_pb2.ConditionalSetResponse(applied=True)
        return kv_store_pb2.ConditionalSetResponse(applied=False)

def SwapValues(self, request, context):
    """Atomically swap values of two keys."""
    with self._lock:  # Lock covers both reads and both writes
        ns_data = self._data.get(request.namespace, {})
        val_a = ns_data.get(request.key_a, 0)
        val_b = ns_data.get(request.key_b, 0)
        if request.namespace not in self._data:
            self._data[request.namespace] = {}
        self._data[request.namespace][request.key_a] = val_b
        self._data[request.namespace][request.key_b] = val_a
        return kv_store_pb2.SwapResponse()
```

All patterns execute inside the lock to ensure atomicity.

### Server Class and Launch

```python
class Server:
    def __init__(self, port=<port>):
        self.port = port
        self._server = None

    def start(self):
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        <name>_pb2_grpc.add_<ServiceName>Servicer_to_server(
            MyServicer(), self._server
        )
        self._server.add_insecure_port(f'[::]:{self.port}')
        self._server.start()

    def stop(self):
        if self._server:
            self._server.stop(0)

    def wait_for_termination(self):
        if self._server:
            self._server.wait_for_termination()


def wait_until_ready(port, timeout=10):
    """Two-phase readiness probe: transport + application level."""
    import time
    deadline = time.time() + timeout
    ch = grpc.insecure_channel(f'localhost:{port}')
    
    # Phase 1: Transport-level — wait for TCP connectivity
    try:
        grpc.channel_ready_future(ch).result(timeout=timeout)
    except grpc.FutureTimeoutError:
        ch.close()
        return False
    
    # Phase 2: Application-level — verify with actual RPC
    # Use the simplest idempotent RPC (e.g., Fetch with empty key)
    stub = <name>_pb2_grpc.<ServiceName>Stub(ch)
    while time.time() < deadline:
        try:
            stub.<SimplestRpc>(<SimplestRequest>())
            ch.close()
            return True
        except grpc.RpcError:
            time.sleep(0.2)
    ch.close()
    return False


if __name__ == '__main__':
    server = Server(port=<port>)
    server.start()
    print(f"Server started on port {server.port}", flush=True)
    if wait_until_ready(<port>, timeout=10):
        print("Server is ready", flush=True)
    else:
        print("WARNING: Server may not be ready", flush=True)
    server.wait_for_termination()
```

**Key points**:
- `Server` class must be importable (tests may do `from server import Server`)
- `if __name__ == '__main__'` starts server as background process
- `wait_until_ready` probes with `channel_ready_future` — more robust than fixed sleep
- Bind to `[::]:<port>` for IPv4+IPv6
- `max_workers=10` handles concurrent requests; increase for heavy load

### Launching the Server

```bash
cd <working_directory> && python3 server.py &
sleep 2  # Give it time to start
```

The server prints "Server is ready" when the readiness probe succeeds.

**Readiness probe levels**:

The `wait_until_ready` function in the template uses a **two-phase approach**:

1. **Transport-level probe** (`channel_ready_future`): Checks if the TCP port is open and accepting connections. Fast, catches "port not bound" errors immediately.

2. **Application-level probe** (actual RPC call): Verifies the gRPC service is registered and can process requests. This validates the entire stack — transport, protocol, service registration, and servicer initialization.

**When to use each**:
- **Transport-only**: Sufficient for simple servers where `server.start()` immediately registers all services. Fast and lightweight.
- **Application-level (RPC-based)**: Required for servers with post-bind initialization (loading config, registering services dynamically, warming up caches). This is the production pattern (Kubernetes readiness probes).

For variants with complex startup, use the RPC-based probe. For simple servers, transport-level is adequate.

**If server fails to start**:
1. Check port is not in use: `lsof -i :<port>` or `netstat -tlnp | grep <port>`
2. Check imports: `python3 -c "import <name>_pb2; import <name>_pb2_grpc"`
3. Check server.py syntax: `python3 -m py_compile server.py`
4. Check logs: Run `python3 server.py` without `&` to see errors

## Handling Runtime Variation

### Concurrent Requests
- `ThreadPoolExecutor(max_workers=N)` with N ≥ 10
- `threading.Lock` protects all shared state — **mandatory**
- Avoid blocking operations in servicer methods

### Startup Delays / Readiness
- `wait_until_ready` probes with `channel_ready_future` — handles variable startup times
- For built-in delays, increase timeout parameter
- Server prints readiness status to stdout

### Longer-Lived Sessions
- No memory leaks: use bounded data structures or implement cleanup
- `wait_for_termination()` keeps server alive
- Graceful shutdown: `server.stop(grace_period)`

### Repeated Channel Creation
- Server handles multiple channels automatically
- State persists across channels (lives in servicer instance)
- No special handling needed

## Verification Checklist

After implementation, verify:

1. ✅ Proto compiles without errors
2. ✅ Generated files exist and are importable
3. ✅ Server starts and binds to correct port
4. ✅ Each RPC returns correct types and values
5. ✅ State persists across calls on same channel
6. ✅ State persists across different channels
7. ✅ Default/missing values match spec (check proto3 defaults)
8. ✅ Namespace isolation (if applicable)
9. ✅ Edge cases: empty state, missing keys, duplicate puts
10. ✅ Thread safety: all methods use locks
11. ✅ Readiness probe confirms server is accepting connections

## Common Pitfalls

1. **Proto filename vs import**: Hyphens → underscores. `my-service.proto` → `import my_service_pb2`
2. **Field number collisions**: Unique within each message
3. **Missing `syntax = "proto3"`**: Required at top
4. **Wrong port**: Check task specification
5. **State not persisting**: Servicer instance created once, reused across requests
6. **Import errors**: Run protoc from correct directory
7. **Response field names**: Must match proto message fields exactly
8. **Enum zero value**: First enum value must be 0
9. **Missing locks**: Check-then-act unsafe without them
10. **Proto3 defaults vs spec**: Verify "missing" return values match zero-defaults
11. **Server not ready**: Use readiness probe, not fixed sleep
12. **Server class not importable**: Must be importable for tests
