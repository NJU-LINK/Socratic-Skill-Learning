---
name: kv-store-grpc
description: >
  Build and deploy Python gRPC stateful services from task specifications.
  Handles the full pipeline: proto definition, code generation, server
  implementation with configurable state semantics, and reliable server
  lifecycle management. Covers variation in RPC API structure (service
  definitions, message types, field combinations), stateful service
  semantics (namespaces, aggregates, conditional updates, deletes), and
  runtime interaction requirements (concurrency, startup delays, health).
---

# gRPC Stateful Service Builder

## Overview

This skill builds real Python gRPC servers from task specifications. Every task
in this family follows the same three-phase pipeline with parameterizable inputs.

## Naming Derivation Procedure

**CRITICAL**: All naming must be derived deterministically from the proto filename and service name. Get this wrong and nothing works.

Given a proto file `<proto_filename>.proto` and service name `<ServiceName>`:

1. **Base module name**: Replace all non-alphanumeric characters (hyphens, spaces, etc.) with underscores
   - `kv-store.proto` → `kv_store`
   - `my-custom-service.proto` → `my_custom_service`
   - `data_store.proto` → `data_store`

2. **Generated Python modules**:
   - Protobuf module: `{base}_pb2.py` (e.g., `kv_store_pb2.py`)
   - gRPC module: `{base}_pb2_grpc.py` (e.g., `kv_store_pb2_grpc.py`)

3. **Python imports in server.py**:
   ```python
   import {base}_pb2
   import {base}_pb2_grpc
   ```

4. **Servicer class name**: `{ServiceName}Servicer`
   - Service `KVStore` → class `KVStoreServicer`
   - Service `TestService` → class `TestServiceServicer`
   - Inherit from: `{base}_pb2_grpc.{ServiceName}Servicer`

5. **Registration function**: `add_{ServiceName}Servicer_to_server`
   - Call: `{base}_pb2_grpc.add_{ServiceName}Servicer_to_server(Server(), server)`

6. **Message classes**: Use exact names from proto
   - Access via: `{base}_pb2.{MessageName}`
   - Example: `kv_store_pb2.PutRequest`, `kv_store_pb2.PutResponse`

**Verification checklist**:
- [ ] Proto filename has correct `.proto` extension
- [ ] Base module name has no hyphens or special characters
- [ ] Both `_pb2.py` and `_pb2_grpc.py` files were generated
- [ ] Server imports use underscore form (not hyphen form)
- [ ] Servicer class inherits from correct generated base class
- [ ] `add_XxxServicer_to_server` matches exact service name from proto

## Quick Start Procedure

Follow this exact sequence for any task in this family:

1. **Parse task specification**: Extract from task.yaml:
   - Proto filename (e.g., `kv-store.proto`)
   - Service name (e.g., `KVStore`)
   - RPC methods with request/response message definitions
   - Field names, types, and field numbers for each message
   - State semantics (what data structure, default values, operations)
   - Port number (e.g., `5328`)

2. **Derive all names** using the Naming Derivation Procedure above:
   - Base module name from proto filename
   - All Python module names, class names, function names

3. **Install dependencies**:
   ```bash
   pip install grpcio==1.73.0 grpcio-tools==1.73.0
   ```

4. **Write proto file** to `/app/<proto_filename>.proto` using the template

5. **Generate Python bindings**:
   ```bash
   cd /app
   python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_filename>.proto
   ```
   Verify both `<base>_pb2.py` and `<base>_pb2_grpc.py` exist.

6. **Write server.py** to `/app/server.py`:
   - Import correct modules (using derived names)
   - Inherit from correct Servicer class
   - Implement all RPC methods with correct state logic
   - Use threading.Lock() for thread safety
   - Register with correct `add_XxxServicer_to_server` function
   - Bind to correct port

7. **Start server as background process**:
   ```bash
   cd /app && python server.py &
   sleep 2
   ```

8. **Verify server is running**:
   ```python
   import grpc
   import <base>_pb2
   import <base>_pb2_grpc
   channel = grpc.insecure_channel('localhost:<port>')
   stub = <base>_pb2_grpc.<ServiceName>Stub(channel)
   # Test one RPC call
   ```

## Three-Phase Architecture

### Phase A: Proto Definition

Generate a `.proto` file from the task's service specification.

**Input**: Task description specifying service name, RPC methods, request/response
messages with field names, types, and field numbers.

**Output**: A valid `.proto` file.

**Critical rules**:
- Field numbers start at 1, never 0
- Proto3 defaults: int32→0, string→"", bool→False — these often match "missing" semantics
- Hyphens in proto filename become underscores in generated Python modules
- Package name should be simple lowercase (becomes part of module path)
- `repeated` for lists, `map<K,V>` for dictionaries, nested messages for complex types
- Enum values must start at 0

**Proto template**:
```protobuf
syntax = "proto3";
package <package_name>;

service <ServiceName> {
  rpc <MethodName>(<RequestMsg>) returns (<ResponseMsg>);
  // ... more RPCs
}

message <RequestMsg> {
  <type> <field_name> = <number>;
  // ... more fields
}

message <ResponseMsg> {
  <type> <field_name> = <number>;
}
```

Use `scripts/generate_proto.py` with a JSON config for complex protos.

### Phase B: Code Generation

Run protoc to generate Python bindings.

```bash
pip install grpcio==1.73.0 grpcio-tools==1.73.0
cd <work_dir>
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_file>.proto
```

**Output**: `<proto_base>_pb2.py` and `<proto_base>_pb2_grpc.py`
(hyphens→underscores in output filenames)

**Critical**: Always import using the underscore form:
- `kv-store.proto` → `import kv_store_pb2` and `import kv_store_pb2_grpc`

### Phase C: Server Implementation

Generate a Python server with the correct servicer class and state logic.

**Server class pattern**:
```python
import grpc
from concurrent import futures
import threading
import <proto_base>_pb2
import <proto_base>_pb2_grpc

class Server(<proto_base>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize state structure based on task semantics
        self._store = {}  # or appropriate structure
        self._lock = threading.Lock()  # always include for safety

    def <MethodName>(self, request, context):
        with self._lock:
            # Implement state logic
            return <proto_base>_pb2.<ResponseMsg>(...)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <proto_base>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

**Key patterns**:
- `add_<ServiceName>Servicer_to_server` — exact generated function name
- Every RPC method takes `(self, request, context)` — context may be unused
- Use `threading.Lock()` for thread safety (always safe, minimal overhead)
- Bind to `'[::]:PORT'` for all interfaces

## State Semantics Guide

### Common State Structures

| Pattern | Structure | Access Pattern |
|---------|-----------|----------------|
| Flat KV | `{key: val}` | `store.get(key, default)` |
| Namespaced KV | `{ns: {key: val}}` | `store.get(ns, {}).get(key, default)` |
| Counter | `{key: int}` | `store[key] = store.get(key, 0) + delta` |
| List | `[items]` | `items.append()`, `items.remove()` |
| Set | `set()` | `members.add()`, `key in members` |

### Default Value Patterns

Proto3 defaults naturally handle "missing" cases:
- `int32` → 0 (for Fetch-missing, aggregate-empty)
- `bool` → False (for Delete-missing success flag)
- `string` → "" (for text lookups)
- `repeated` → [] (for list queries)

### Common Operations

- **Put/Overwrite**: `store[ns][key] = value; return value`
- **Fetch with default**: `return store.get(ns, {}).get(key, 0)`
- **Delete with flag**: `if key in store: val=store.pop(key); return (True, val); else: return (False, 0)`
- **Aggregate (sum)**: `return sum(store.get(ns, {}).values())`
- **Conditional update**: Check condition before mutating
- **Multi-key operation**: Iterate over relevant keys under lock

## Runtime & Lifecycle

### Server Startup (Robust Procedure)

For reliable server startup that works across family variants:

```bash
# 1. Kill any existing server on the target port
python -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = s.connect_ex(('localhost', <port>))
s.close()
if result == 0:
    import os, signal
    # Port is in use - find and kill the process
    os.system('fuser -k <port>/tcp 2>/dev/null || true')
    import time; time.sleep(1)
" 2>/dev/null || true

# 2. Start server in background
cd /app && python server.py > /tmp/server.log 2>&1 &
SERVER_PID=$!

# 3. Wait for readiness with retry loop
python -c "
import grpc, time, sys
channel = grpc.insecure_channel('localhost:<port>')
for i in range(20):
    try:
        grpc.channel_ready_future(channel).result(timeout=0.5)
        print('Server ready')
        sys.exit(0)
    except:
        time.sleep(0.5)
print('Server failed to start')
sys.exit(1)
"
```

**Alternative simple approach** (works for most cases):
```bash
cd /app && python server.py &
sleep 2
```

### Readiness Verification
```python
import grpc
channel = grpc.insecure_channel('localhost:PORT')
grpc.channel_ready_future(channel).result(timeout=5)
```

### Concurrency
- `ThreadPoolExecutor(max_workers=N)` — N=10 is safe default
- `threading.Lock()` around all state access
- For high-concurrency variants, consider `asyncio` gRPC server

### Long-Running Servers
- Use `server.wait_for_termination()` to keep alive
- Handle SIGTERM for graceful shutdown: `server.stop(grace=5)`
- Monitor with health checks if required
- Server must remain alive across multiple client connections and test sequences

## Gotchas

1. **Import naming**: `my-service.proto` → `import my_service_pb2` (hyphen→underscore)
2. **add_XxxServicer_to_server**: Must match exact service name from proto
3. **Field numbers**: Start at 1, must be unique within a message
4. **Proto3 defaults**: Don't explicitly set fields to their default — they're already that value
5. **Background server**: Start with `&` or `subprocess.Popen`, add readiness wait
6. **Port conflicts**: Kill existing processes on the port before starting
7. **context parameter**: Every RPC method must accept it even if unused
8. **Thread safety**: Always use locks — the cost is negligible and prevents race conditions

## Workflow for Any Task

1. **Parse task**: Extract service name, RPCs, messages, fields, state semantics, port
2. **Write proto**: Use template or `scripts/generate_proto.py` with JSON config
3. **Generate code**: Run protoc command
4. **Write server**: Implement servicer with correct state logic
5. **Start server**: Background process with readiness check
6. **Verify**: Test with a client stub to confirm RPCs work

## Scripts

- `scripts/generate_proto.py` — JSON config → .proto file
- `scripts/generate_server.py` — JSON config → server.py
- `scripts/build_and_start.sh` — Full pipeline: install, generate, start

## References

- `references/proto_field_types.md` — Proto3 type system and naming conventions
- `references/state_patterns.md` — State structure patterns and operation semantics
