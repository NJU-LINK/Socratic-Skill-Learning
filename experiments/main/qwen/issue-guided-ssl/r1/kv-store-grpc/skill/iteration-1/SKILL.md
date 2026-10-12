---
name: kv-store-grpc
description: >
  Build and deploy Python gRPC stateful services from proto definitions.
  Covers proto authoring (services, RPCs, messages with scalar/nested/repeated/enum fields),
  protoc code generation, server implementation with in-memory state management,
  and reliable server lifecycle (launch, readiness, concurrent serving).
  Generalizes across varying API complexity, state semantics, and runtime requirements.
---

# gRPC Stateful Service Builder

## Family Definition

This skill covers the family of tasks that require building a Python gRPC server with:
- A `.proto` file defining services, RPCs, and messages
- Generated Python bindings via `grpc_tools.protoc`
- A server implementation with in-memory state that persists across RPC calls
- A running gRPC server accessible on a specified port

The family varies along three axes:
1. **RPC API structure**: Simple unary RPCs → complex services with nested/repeated/enum fields, multiple services, streaming
2. **Stateful service semantics**: Simple key-value → namespaced stores, conditional updates, aggregates, multi-key operations, deletes, resets
3. **Runtime interaction requirements**: Light single-client → concurrent requests, long-lived sessions, readiness probes, repeated channel creation

## Procedure

### Step 1: Install Dependencies

```bash
pip install grpcio==1.73.0 grpcio-tools==1.73.0
```

Pin versions to ensure compatibility. The `grpcio-tools` package provides `grpc_tools.protoc`.

### Step 2: Write the Proto File

Write the `.proto` file to `/app/` using `task_shell` (the `write` tool is workspace-bound and cannot write to `/app/`).

Key proto authoring rules:
- Use `syntax = "proto3";`
- Define a `package` name (e.g., `package kvstore;`)
- Service names use PascalCase; RPC names use PascalCase
- Message names use PascalCase; field names use snake_case
- Field numbers start at 1 and must be unique within a message
- Proto3 field types: `string`, `int32`, `int64`, `float`, `double`, `bool`, `bytes`, plus nested messages, `enum`, `repeated`, `map`
- The filename can contain hyphens (e.g., `kv-store.proto`), but generated Python modules replace hyphens with underscores

### Step 3: Generate Python Bindings

```bash
cd /app && python -m grpc_tools.protoc \
  -I/app \
  --python_out=/app \
  --grpc_python_out=/app \
  /app/<proto-file>.proto
```

This generates:
- `<name>_pb2.py` — message classes
- `<name>_pb2_grpc.py` — service stubs and servicer base classes

**Critical naming rule**: Hyphens in the proto filename become underscores in Python module names. For `kv-store.proto`, the modules are `kv_store_pb2` and `kv_store_pb2_grpc`.

### Step 4: Implement the Server

Create `server.py` implementing the servicer class:

```python
import grpc
from concurrent import futures
import <module>_pb2
import <module>_pb2_grpc

class Server(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize state based on task semantics
        self.store = {}  # or appropriate data structure

    def <RpcMethod>(self, request, context):
        # Access fields: request.<field_name>
        # Return: <module>_pb2.<ResponseMessage>(<field>=<value>)
        pass

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

Key implementation patterns:
- The servicer class inherits from `<module>_pb2_grpc.<ServiceName>Servicer`
- Each RPC method takes `(self, request, context)` and returns the response message
- Access request fields via `request.<field_name>`
- Construct responses via `<module>_pb2.<ResponseMessage>(field1=val1, field2=val2)`
- Use `futures.ThreadPoolExecutor` for concurrent request handling
- `server.wait_for_termination()` blocks the main thread, keeping the server alive

### Step 5: Start the Server

```bash
cd /app && python server.py &
sleep 2  # Allow time for port binding
```

The server must be left **running** as a background process.

### Step 6: Verify

Write a quick client test to confirm each RPC works correctly:

```python
import grpc
import <module>_pb2
import <module>_pb2_grpc

channel = grpc.insecure_channel('localhost:<port>')
stub = <module>_pb2_grpc.<ServiceName>Stub(channel)
# Call each RPC and verify responses
```

## State Management Patterns

### Namespace-Isolated Key-Value Store
```python
self.store = {}  # {namespace: {key: value}}
# Put: self.store.setdefault(ns, {})[key] = value
# Fetch: self.store.get(ns, {}).get(key, default)
# Delete: pop from inner dict, return success/failure
# Aggregate: sum(inner_dict.values())
```

### Flat Key-Value Store
```python
self.store = {}  # {key: value}
# Simpler: no namespace dimension
```

### Multi-Collection State
```python
self.collections = {'collection_a': {}, 'collection_b': []}
# Different data structures for different semantic needs
```

## Proto Complexity Patterns

### Simple Scalars
```protobuf
message Request { string key = 1; int32 value = 2; }
```

### Nested Messages
```protobuf
message Inner { string field = 1; }
message Outer { Inner nested = 1; string name = 2; }
```

### Repeated Fields
```protobuf
message Request { repeated string keys = 1; }
```

### Enums
```protobuf
enum Status { ACTIVE = 0; INACTIVE = 1; }
message Request { Status status = 1; }
```

### Map Fields
```protobuf
message Request { map<string, int32> data = 1; }
```

## Runtime Reliability Patterns

### Thread Pool Sizing
- `max_workers=10` handles moderate concurrency
- For burst workloads, increase to `max_workers=50` or more

### Readiness Verification
After starting the server, verify with a client call before declaring success.

### Long-Lived Sessions
- Use `server.wait_for_termination()` to keep the process alive
- The `ThreadPoolExecutor` handles concurrent requests without blocking

## Common Pitfalls

1. **Writing to /app/**: Use `task_shell` with heredocs, not the `write` tool
2. **Module naming**: Hyphens in proto filenames → underscores in Python imports
3. **Proto3 defaults**: `int32` defaults to `0`, `bool` defaults to `False`, `string` defaults to `""`
4. **Missing keys**: Always handle missing keys explicitly with `.get(key, default)`
5. **Namespace isolation**: Use nested dicts or composite keys to isolate state
6. **Server not running**: Always `sleep` after background launch and verify with a test call
