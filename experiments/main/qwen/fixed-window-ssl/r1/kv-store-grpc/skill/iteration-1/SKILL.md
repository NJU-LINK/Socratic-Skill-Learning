---
name: kv-store-grpc
description: Build stateful Python gRPC services with in-memory state, handling proto definition, code generation, server implementation, and lifecycle management
---

# Python gRPC Stateful Service Implementation

## Overview

This skill covers building real Python gRPC services that maintain in-memory state across RPC calls. The pattern applies to any task requiring: proto file definition, Python binding generation, servicer implementation with state management, and reliable server lifecycle.

## Core Workflow

Every gRPC service task follows this sequence:

1. **Install dependencies**: `grpcio` and `grpcio-tools` (pin versions if specified)
2. **Create proto file**: Define service, RPCs, and messages with exact field numbers
3. **Generate Python bindings**: Use `grpc_tools.protoc` to produce `*_pb2.py` and `*_pb2_grpc.py`
4. **Implement servicer**: Create class extending generated `*Servicer` base, with in-memory state
5. **Start server**: Configure gRPC server, bind port, start, and wait for termination

## Proto File Construction

### Extract Requirements from Task Specification

Tasks specify:
- Service name (e.g., `KVStore`)
- RPC methods with request/response message types
- Message fields with exact types and field numbers

**Critical**: Field numbers must match the specification exactly. Do not renumber or skip.

### Proto File Template

```protobuf
syntax = "proto3";

package <package_name>;

service <ServiceName> {
  rpc <Method1>(<Request1>) returns (<Response1>);
  rpc <Method2>(<Request2>) returns (<Response2>);
  // ... more RPCs
}

message <Request1> {
  <type> <field_name> = <field_number>;
  // ... more fields
}

message <Response1> {
  <type> <field_name> = <field_number>;
}
```

### Common Field Types

- `string` - text data
- `int32`, `int64` - integers
- `bool` - boolean
- `repeated <type>` - lists/arrays
- Nested messages - define separately, reference by name

## Code Generation

Run from the directory containing the proto file:

```bash
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_file>.proto
```

**Naming convention**: Hyphens in proto filename become underscores in generated Python files:
- `kv-store.proto` → `kv_store_pb2.py` and `kv_store_pb2_grpc.py`

## Server Implementation

### Class Structure

```python
import grpc
from concurrent import futures
import <proto_name>_pb2
import <proto_name>_pb2_grpc

class Server(<proto_name>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize in-memory state
        self._store = {}  # Structure depends on task requirements
    
    def <MethodName>(self, request, context):
        # Extract fields from request
        field1 = request.<field1>
        field2 = request.<field2>
        
        # Perform operation on state
        # ...
        
        # Return response using generated message class
        return <proto_name>_pb2.<ResponseName>(<field>=<value>)
```

### State Management Patterns

**Flat key-value store**:
```python
self._store = {}  # key -> value
```

**Namespaced/multi-collection store**:
```python
self._store = {}  # namespace -> {key -> value}
```

**Multiple related collections**:
```python
self._users = {}
self._sessions = {}
self._counters = {}
```

### Handling Missing Data

Tasks often specify default return values for missing keys/namespaces. Common patterns:

- **Fetch missing key**: Return default value (e.g., `0`, `""`, `False`)
- **Delete missing key**: Return `success=False` with default value
- **Aggregate on empty collection**: Return `0` or appropriate identity value

Always check task specification for exact default behavior.

### Server Startup Pattern

```python
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <proto_name>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

**Key points**:
- Use `[::]:<port>` to listen on all interfaces
- `wait_for_termination()` keeps server running
- Server must be running before tests connect

## Testing Your Implementation

### Basic Functionality Test

```python
import grpc
import <proto_name>_pb2
import <proto_name>_pb2_grpc

channel = grpc.insecure_channel('localhost:<port>')
stub = <proto_name>_pb2_grpc.<ServiceName>Stub(channel)

# Test each RPC method
response = stub.<Method>(<proto_name>_pb2.<Request>(<field>=<value>))
assert response.<field> == <expected_value>

channel.close()
```

### State Persistence Test

Verify state persists across multiple calls:
```python
stub.Put(..., value=42)
resp = stub.Fetch(...)
assert resp.value == 42  # State persisted
```

### Cross-Channel State Test

Verify state is shared across different client channels:
```python
ch1 = grpc.insecure_channel('localhost:<port>')
stub1 = <ServiceName>Stub(ch1)
stub1.Put(...)

ch2 = grpc.insecure_channel('localhost:<port>')
stub2 = <ServiceName>Stub(ch2)
resp = stub2.Fetch(...)  # Should see data from ch1
```

### Concurrency Test

For tasks requiring concurrent request handling:
```python
import concurrent.futures

def operation(i):
    ch = grpc.insecure_channel('localhost:<port>')
    s = <ServiceName>Stub(ch)
    # perform operation
    ch.close()
    return result

with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(operation, i) for i in range(20)]
    results = [f.result() for f in futures]
```

## Common Pitfalls and Solutions

### 1. Wrong Field Numbers in Proto

**Symptom**: Generated code doesn't match expected schema, serialization fails

**Solution**: Copy field numbers exactly from task specification. Verify each field has unique number.

### 2. Incorrect Servicer Base Class

**Symptom**: gRPC doesn't recognize service implementation

**Solution**: Class must extend `<ServiceName>Servicer` from generated `*_pb2_grpc` module, not just implement methods.

### 3. Missing Default Values

**Symptom**: Tests fail on missing key/namespace operations

**Solution**: Check task spec for default return values. Use `.get()` with defaults:
```python
value = self._store.get(namespace, {}).get(key, 0)
```

### 4. Server Not Running When Tests Connect

**Symptom**: Connection refused errors

**Solution**: 
- Start server in background: `python3 server.py &`
- Add sleep to ensure startup: `sleep 2`
- Verify process is running: `ps aux | grep server.py`

### 5. State Not Shared Across Channels

**Symptom**: Data written via one channel not visible via another

**Solution**: Ensure single server instance with shared state. State must be in servicer instance variables, not local to RPC methods.

### 6. Import Errors for Generated Files

**Symptom**: `ModuleNotFoundError` for `*_pb2` modules

**Solution**: 
- Run generation command from correct directory
- Check filename: hyphens become underscores in Python imports
- Ensure generated files are in Python path

## Handling Spec Variations

### Variation: RPC API Structure

**What changes**: Number of RPCs, message complexity (nested, repeated fields, enums)

**How to handle**:
- Parse task spec carefully for all RPC methods
- For nested messages, define inner messages first
- For repeated fields, use `repeated` keyword
- For enums, define enum type separately
- Field numbers still matter—copy exactly from spec

### Variation: Stateful Service Semantics

**What changes**: State structure, operations (deletes, aggregates, conditional updates, multi-key ops)

**How to handle**:
- Choose appropriate data structure (dict, nested dict, multiple dicts, lists)
- Implement each operation according to spec semantics
- Pay attention to:
  - Overwrite vs. append behavior
  - Aggregate operations (sum, count, average)
  - Conditional updates (only if exists, only if not exists)
  - Multi-key operations (batch put, batch fetch)
- Test edge cases: empty collections, missing keys, concurrent modifications

### Variation: Runtime Interaction Requirements

**What changes**: Server lifetime, concurrency, startup delays, repeated channel creation

**How to handle**:
- Use `ThreadPoolExecutor` with sufficient workers (10+ for concurrent load)
- Ensure server stays alive: `wait_for_termination()`
- For startup delays, add readiness checks or sleep
- State must be thread-safe (Python's GIL helps, but be careful with complex operations)
- Test with multiple simultaneous channels and rapid successive connections

## Verification Checklist

Before submitting, verify:

- [ ] Proto file has correct service name, RPCs, messages, and field numbers
- [ ] Generated Python files exist and are importable
- [ ] Server class extends correct servicer base class
- [ ] All RPC methods implemented with correct signatures
- [ ] State structure matches task requirements
- [ ] Default values for missing data match specification
- [ ] Server starts and listens on specified port
- [ ] State persists across multiple RPC calls
- [ ] State is shared across different client channels
- [ ] Server handles concurrent requests correctly
- [ ] All edge cases tested (missing keys, empty collections, etc.)

## Example: Complete Implementation

See `/app/` for a working example implementing a namespaced integer store with Put, Fetch, Delete, and ListNamespaceTotal operations.

Key files:
- `kv-store.proto` - Service definition
- `kv_store_pb2.py`, `kv_store_pb2_grpc.py` - Generated bindings
- `server.py` - Server implementation

The example demonstrates:
- Proto file with exact field numbers
- Namespaced state using nested dictionaries
- Correct default values for missing data
- Server startup and lifecycle management
- Thread-safe concurrent request handling
