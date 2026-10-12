---
name: kv-store-grpc
description: Build stateful Python gRPC services with in-memory state management, namespace isolation, and concurrent request handling
---

# KV Store gRPC Service

Build production-ready Python gRPC services that maintain in-memory state across multiple client connections and RPC calls.

## Procedure

Follow these steps in order for any variant in this family:

### Step 1: Install Dependencies

```bash
pip install grpcio==<version> grpcio-tools==<version>
```

Check the task instruction for the exact version. If not specified, use a recent stable version (e.g., 1.73.0).

### Step 2: Create Proto File

Parse the task instruction to extract:
- Service name
- RPC methods with request/response message types
- Message field names, types, and field numbers
- Package name (if specified)

Create `<service-name>.proto` in `/app/` with the exact structure from the task.

**Naming convention**: Hyphens in proto filenames become underscores in generated Python modules:
- `kv-store.proto` → `kv_store_pb2.py` and `kv_store_pb2_grpc.py`

### Step 3: Generate Python Code

```bash
cd /app && python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto-file>.proto
```

Verify that `<name>_pb2.py` and `<name>_pb2_grpc.py` were created.

### Step 4: Implement Server

Create `/app/server.py` with this structure:

```python
import os
import sys
# CRITICAL: Add this before any other imports to ensure generated modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import grpc
from concurrent import futures
import threading
import <generated>_pb2
import <generated>_pb2_grpc


class Server(<generated>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize state based on task requirements
        self._state = {}
        self._lock = threading.Lock()
    
    def <MethodName>(self, request, context):
        with self._lock:
            # Implement RPC logic based on task requirements
            # Access request fields as Python attributes
            # Return response message with appropriate fields
            return <generated>_pb2.<ResponseMessage>(field=value)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <generated>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<PORT>')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

**Key points**:
- The `sys.path.insert` line is mandatory for pytest compatibility
- Use `threading.Lock()` for all state access to handle concurrent requests
- Implement all RPC methods defined in the proto file
- Use the exact port specified in the task

### Step 5: Start Server

```bash
cd /app && python server.py &
sleep 2
```

The `&` runs the server in the background. The `sleep 2` gives it time to start.

### Step 6: Verify Server is Running

**Do NOT use `ps`** — it's not available in minimal containers. Instead, use a gRPC connectivity test:

```python
import grpc
import <generated>_pb2
import <generated>_pb2_grpc

channel = grpc.insecure_channel('localhost:<PORT>')
try:
    grpc.channel_ready_future(channel).result(timeout=3)
    stub = <generated>_pb2_grpc.<ServiceName>Stub(channel)
    # Make a test RPC call
    resp = stub.<MethodName>(<generated>_pb2.<RequestMessage>(...))
    print(f'✓ Server running on port <PORT>')
except Exception as e:
    print(f'✗ Server not reachable: {e}')
finally:
    channel.close()
```

### Step 7: Test All Functionality

Write a comprehensive test script that exercises all RPC methods with various scenarios:
- Basic operations (create, read, update, delete)
- Missing keys/records (verify default behavior)
- Namespace isolation (if applicable)
- Aggregate operations (if applicable)
- State persistence across client channels

## Handling Variations

The spec defines three variation axes. Parse the task instruction to identify which variations are present and apply the appropriate patterns.

### RPC API Structure Variations

**Enums**: Define in proto, access as Python attributes
```protobuf
enum Status { ACTIVE = 0; INACTIVE = 1; }
message Item { Status status = 1; }
```
```python
# In servicer: request.status returns the enum value (int)
# To set: response.status = kv_store_pb2.ACTIVE
```

**Nested messages**: Define inner message, use as field type
```protobuf
message Address { string city = 1; }
message Person { Address addr = 1; }
```
```python
# Access: request.addr.city
# Set: response.addr.CopyFrom(kv_store_pb2.Address(city="NYC"))
```

**Repeated fields**: Use `repeated` keyword
```protobuf
message ListRequest { repeated string keys = 1; }
```
```python
# Access: for key in request.keys: ...
# Set: response.items.extend([item1, item2])
```

### Stateful Service Semantics Variations

**Conditional updates (check-then-set)**:
```python
def ConditionalPut(self, request, context):
    with self._lock:
        ns = self._get_ns(request.namespace)
        current = ns.get(request.key)
        if request.expected_value == current:
            ns[request.key] = request.new_value
            return Response(success=True)
        return Response(success=False)
```

**Aggregate operations beyond sum**:
```python
# Count
def Count(self, request, context):
    with self._lock:
        return Response(count=len(self._namespaces.get(request.namespace, {})))

# Average
def Average(self, request, context):
    with self._lock:
        ns = self._namespaces.get(request.namespace, {})
        if not ns:
            return Response(average=0)
        return Response(average=sum(ns.values()) / len(ns))

# Min/Max
def Min(self, request, context):
    with self._lock:
        ns = self._namespaces.get(request.namespace, {})
        return Response(value=min(ns.values()) if ns else 0)
```

**Multi-key atomic operations**:
```python
def BatchPut(self, request, context):
    with self._lock:
        ns = self._get_ns(request.namespace)
        for item in request.items:
            ns[item.key] = item.value
        return Response(count=len(request.items))
```

**Delete and reset**:
```python
def ClearNamespace(self, request, context):
    with self._lock:
        if request.namespace in self._namespaces:
            del self._namespaces[request.namespace]
        return Response(success=True)
```

### Runtime Interaction Requirements Variations

**Tuning for burst traffic**:
```python
# Increase worker pool for high concurrency
server = grpc.server(futures.ThreadPoolExecutor(max_workers=50))

# Add options for better performance
options = [
    ('grpc.max_send_message_length', 50 * 1024 * 1024),
    ('grpc.max_receive_message_length', 50 * 1024 * 1024),
]
server = grpc.server(futures.ThreadPoolExecutor(max_workers=20), options=options)
```

**Health checks and readiness**:
```python
class Server(kv_store_pb2_grpc.KVStoreServicer, health.HealthServicer):
    def check(self, request, context):
        # Return SERVING if ready
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.SERVING
        )
```

**Graceful shutdown for long-running tests**:
```python
import signal

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port('[::]:5328')
    server.start()
    
    # Handle SIGTERM for clean shutdown
    stop_event = threading.Event()
    def _signal_handler(sig, frame):
        stop_event.set()
    signal.signal(signal.SIGTERM, _signal_handler)
    
    # Wait for termination signal or block forever
    stop_event.wait()
    server.stop(grace=5).wait()
```

**Connection pooling for repeated channel creation**:
The server handles this automatically. Ensure your implementation doesn't create per-request resources that leak.

## State Management Patterns

### Namespace Isolation

For multi-tenant or categorized data:
```python
self._namespaces = {}  # {namespace: {key: value}}

def _get_ns(self, namespace):
    if namespace not in self._namespaces:
        self._namespaces[namespace] = {}
    return self._namespaces[namespace]
```

### Default Values

Always return sensible defaults for missing data rather than raising errors:
- Missing integer keys: return `0`
- Missing boolean checks: return `False`
- Empty aggregations: return `0` or empty collection

### Thread Safety

Wrap all state mutations and reads in locks:
```python
with self._lock:
    # Access or modify self._state
```

This ensures correctness under concurrent gRPC requests handled by ThreadPoolExecutor.

### CRUD Operations

**Create/Update (Put)**:
- Overwrite existing values
- Return the written value for confirmation

**Read (Fetch/Get)**:
- Return stored value or default for missing keys
- Never raise KeyError

**Delete**:
- Return success flag + removed value
- Return success=False + default value for missing keys

**Aggregate (List/Total/Count)**:
- Iterate over collection under lock
- Return 0 for empty or non-existent collections

## Runtime Requirements

### Server Lifecycle

- `server.start()` returns immediately; server runs in background threads
- `server.wait_for_termination()` blocks main thread until shutdown signal
- Server must remain alive across multiple client connections
- State persists in memory for the server's lifetime

### Port Binding

- Use `[::]:<PORT>` to listen on all IPv4/IPv6 interfaces
- Check task instruction for the exact port

### Concurrency

- `ThreadPoolExecutor(max_workers=10)` handles concurrent unary RPCs
- Each RPC runs in a separate thread from the pool
- Thread-safe state access is mandatory

### Client Channel Behavior

- Multiple client channels can connect to the same server
- State is shared across all channels (server-side persistence)
- Clients should close channels when done to avoid resource leaks

## Troubleshooting

**Import path errors (ModuleNotFoundError)**: Always add `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` at the top of `server.py` before any other imports. This ensures generated `_pb2` modules are importable regardless of working directory. Without this, pytest runners that import `server.py` from a different directory will fail. Also verify that generated file module names match proto filenames (hyphens → underscores).

**Connection refused**: Verify server is running using gRPC connectivity test (not `ps`). Check that the port matches the task specification.

**State not persisting**: Ensure single Server instance is shared across all RPCs; check that state is instance-level, not method-local

**Race conditions**: All state access must be protected by locks; check for lock-free reads

**Channel resource leaks**: Clients should close channels; server-side state is unaffected by client channel lifecycle

**`ps` command not found**: This is normal in minimal containers. Use gRPC connectivity test to verify server is running.
