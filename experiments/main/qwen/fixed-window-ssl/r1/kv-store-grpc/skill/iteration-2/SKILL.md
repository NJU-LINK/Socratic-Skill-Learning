---
name: kv-store-grpc
description: Build stateful Python gRPC services with in-memory state, handling proto definition, code generation, server implementation, and lifecycle management
---

# Python gRPC Stateful Service Implementation

## Quick Start Checklist

When you encounter a gRPC service task:

1. **Read task spec carefully** - extract service name, RPC methods, message fields with exact field numbers, port, class name
2. **Install dependencies** - `pip install grpcio==<version> grpcio-tools==<version>`
3. **Create proto file** - copy field numbers exactly from spec
4. **Generate bindings** - `python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <file>.proto`
5. **Implement servicer** - extend `<ServiceName>Servicer`, add in-memory state
6. **Start server** - bind to specified port, use `wait_for_termination()`
7. **Test thoroughly** - verify all RPCs, defaults, state persistence, cross-channel sharing

## Core Pattern

### 1. Proto File Structure

```protobuf
syntax = "proto3";
package <package>;

service <ServiceName> {
  rpc <Method1>(<Request1>) returns (<Response1>);
  // ... more RPCs
}

message <Request1> {
  <type> <field> = <number>;  // ← field numbers MUST match spec exactly
}

message <Response1> {
  <type> <field> = <number>;
}
```

**Critical rules:**
- Field numbers must match task specification exactly - do not renumber
- Hyphens in proto filename become underscores in generated Python files
- Example: `kv-store.proto` → `kv_store_pb2.py`, `kv_store_pb2_grpc.py`

### 2. Server Implementation Template

```python
import grpc
from concurrent import futures
import <proto_name>_pb2
import <proto_name>_pb2_grpc

class Server(<proto_name>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize state structure based on task requirements
        self._store = {}  # See "State Structures" section
    
    def <MethodName>(self, request, context):
        # Extract request fields
        field1 = request.<field1>
        
        # Perform operation on state
        # ...
        
        # Return response using generated message class
        return <proto_name>_pb2.<ResponseName>(<field>=<value>)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <proto_name>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

### 3. State Structures

Choose based on task requirements:

**Flat key-value store:**
```python
self._store = {}  # key -> value
# Access: self._store.get(key, default_value)
```

**Namespaced/multi-collection store:**
```python
self._store = {}  # namespace -> {key -> value}
# Access: self._store.get(namespace, {}).get(key, default_value)
```

**Multiple related collections:**
```python
self._users = {}
self._sessions = {}
self._counters = {}
```

**Aggregates (sum, count, etc.):**
```python
# Sum values in a namespace
total = sum(self._store.get(namespace, {}).values())

# Count items
count = len(self._store.get(namespace, {}))
```

### 4. Default Value Patterns

Tasks often specify exact defaults for missing data. Common patterns:

```python
# Fetch missing key → return default value
def Fetch(self, request, context):
    value = self._store.get(namespace, {}).get(key, 0)  # or "", False, etc.
    return pb2.FetchResponse(value=value)

# Delete missing key → return success=False with default
def Delete(self, request, context):
    if ns in self._store and key in self._store[ns]:
        removed = self._store[ns].pop(key)
        return pb2.DeleteResponse(success=True, value=removed)
    return pb2.DeleteResponse(success=False, value=0)

# Aggregate on empty → return identity value
def ListTotal(self, request, context):
    total = sum(self._store.get(namespace, {}).values())  # sum of empty = 0
    return pb2.TotalResponse(total=total)
```

**Always check task spec for exact default values** - they vary by task.

## Handling Spec Variations

### Variation 1: RPC API Structure

**What changes:** Number of RPCs, message complexity (nested, repeated, enums)

**Adaptation patterns:**

**More RPC methods:**
```protobuf
service MyService {
  rpc Method1(Req1) returns (Resp1);
  rpc Method2(Req2) returns (Resp2);
  rpc Method3(Req3) returns (Resp3);
  // Just add more - pattern is the same
}
```

**Nested messages:**
```protobuf
message Address {
  string street = 1;
  string city = 2;
}

message Person {
  string name = 1;
  Address address = 2;  // Reference to another message
}
```

**Repeated fields (lists):**
```protobuf
message ItemList {
  repeated string items = 1;  // List of strings
}

// In Python:
request.items  # Returns a list
response.items.append("new_item")
```

**Enums:**
```protobuf
enum Status {
  UNKNOWN = 0;
  ACTIVE = 1;
  INACTIVE = 2;
}

message Record {
  Status status = 1;
}

// In Python:
pb2.Record(status=pb2.ACTIVE)
```

### Variation 2: Stateful Service Semantics

**What changes:** State operations (deletes, aggregates, conditional updates, multi-key ops)

**Adaptation patterns:**

**Conditional updates (only if exists/not exists):**
```python
def PutIfAbsent(self, request, context):
    ns, key, value = request.namespace, request.key, request.value
    if ns not in self._store:
        self._store[ns] = {}
    if key not in self._store[ns]:
        self._store[ns][key] = value
        return pb2.PutResponse(success=True, value=value)
    return pb2.PutResponse(success=False, value=self._store[ns][key])
```

**Batch operations:**
```python
def BatchPut(self, request, context):
    # request.items is repeated KeyValue
    for item in request.items:
        self._store[item.namespace][item.key] = item.value
    return pb2.BatchResponse(count=len(request.items))
```

**Atomic increments:**
```python
def Increment(self, request, context):
    ns, key = request.namespace, request.key
    if ns not in self._store:
        self._store[ns] = {}
    current = self._store[ns].get(key, 0)
    self._store[ns][key] = current + request.amount
    return pb2.IncrementResponse(value=self._store[ns][key])
```

### Variation 3: Runtime Requirements

**What changes:** Server lifetime, concurrency, startup delays

**Adaptation patterns:**

**Higher concurrency:**
```python
# Increase worker threads for concurrent load
server = grpc.server(futures.ThreadPoolExecutor(max_workers=50))
```

**Startup readiness:**
```python
import time

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    add_servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:5328')
    server.start()
    time.sleep(1)  # Allow startup time
    server.wait_for_termination()
```

**Thread-safe state (if needed beyond GIL):**
```python
import threading

class Server(pb2_grpc.ServiceServicer):
    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()
    
    def Put(self, request, context):
        with self._lock:
            # Critical section
            self._store[request.key] = request.value
        return pb2.PutResponse(value=request.value)
```

## Testing Strategy

### Test Matrix

For every gRPC service, test:

1. **Basic functionality** - each RPC method with valid inputs
2. **Default values** - missing keys, empty collections
3. **State persistence** - data survives across multiple calls
4. **Cross-channel sharing** - data written via one channel visible via another
5. **Edge cases** - empty strings, zero values, overwrites
6. **Concurrency** - multiple simultaneous requests (if required)

### Test Template

```python
import grpc
import <proto>_pb2
import <proto>_pb2_grpc

channel = grpc.insecure_channel('localhost:<port>')
stub = <proto>_pb2_grpc.<Service>Stub(channel)

# Test 1: Basic operation
resp = stub.<Method>(pb2.<Request>(<field>=<value>))
assert resp.<field> == <expected>

# Test 2: Default for missing data
resp = stub.<Method>(pb2.<Request>(<field>="missing"))
assert resp.<field> == <default>

# Test 3: State persistence
stub.<WriteMethod>(pb2.<Request>(<field>=42))
resp = stub.<ReadMethod>(pb2.<Request>(<field>="same_key"))
assert resp.<field> == 42

# Test 4: Cross-channel sharing
ch2 = grpc.insecure_channel('localhost:<port>')
stub2 = <Service>Stub(ch2)
resp = stub2.<ReadMethod>(pb2.<Request>(<field>="same_key"))
assert resp.<field> == 42  # Sees data from first channel

channel.close()
ch2.close()
```

## Troubleshooting

### Problem: Tests fail with "Connection refused"

**Cause:** Server not running when tests connect

**Solution:**
```bash
# Start server in background
python3 server.py &
sleep 2  # Wait for startup

# Verify it's running
# (Note: ps may not be available in container, use alternative)
python3 -c "import grpc; import pb2; import pb2_grpc; \
  ch = grpc.insecure_channel('localhost:<port>'); \
  stub = pb2_grpc.ServiceStub(ch); \
  stub.Method(pb2.Request()); \
  print('Server is running')"
```

### Problem: Generated files not found

**Cause:** Wrong directory or filename mismatch

**Solution:**
- Run protoc from directory containing proto file
- Remember: `my-service.proto` → `my_service_pb2.py` (hyphens become underscores)
- Verify files exist: `ls *_pb2*.py`

### Problem: gRPC doesn't recognize service implementation

**Cause:** Wrong base class

**Solution:**
```python
# WRONG:
class Server:
    def Method(self, request, context): ...

# CORRECT:
class Server(pb2_grpc.ServiceServicer):
    def Method(self, request, context): ...
```

### Problem: Wrong field numbers in generated code

**Cause:** Field numbers don't match task spec

**Solution:**
- Copy field numbers exactly from task specification
- Each field must have unique number within its message
- Verify proto file before generating

### Problem: State not shared across channels

**Cause:** State in wrong scope

**Solution:**
```python
# WRONG: State in method (lost after each call)
def Method(self, request, context):
    store = {}  # Local variable - lost!
    store[key] = value

# CORRECT: State in instance (persists)
class Server(pb2_grpc.ServiceServicer):
    def __init__(self):
        self._store = {}  # Instance variable - persists!
```

## Common Mistakes to Avoid

1. **Renumbering proto fields** - always copy exact field numbers from spec
2. **Forgetting defaults** - check task spec for exact default values
3. **Wrong servicer base** - must extend `<Service>Servicer` from generated code
4. **Server not running** - start in background with `&` and `sleep`
5. **State in wrong scope** - must be instance variable, not local
6. **Import errors** - hyphens in proto filename become underscores in Python
7. **Not testing cross-channel** - state must be shared across different client channels

## Verification Before Submission

Run this checklist:

- [ ] Proto file has correct service name, RPCs, messages, field numbers
- [ ] Generated `*_pb2.py` and `*_pb2_grpc.py` exist
- [ ] Server class extends correct `<Service>Servicer` base
- [ ] All RPC methods implemented with correct signatures `(self, request, context)`
- [ ] State structure matches task requirements
- [ ] Default values for missing data match specification exactly
- [ ] Server starts on specified port and stays running
- [ ] Tested: basic operations, defaults, persistence, cross-channel sharing
- [ ] Tested: edge cases (empty collections, missing keys, overwrites)

## Example: Complete Implementation

See `/app/` for working example:
- `kv-store.proto` - Service with Put, Fetch, Delete, ListNamespaceTotal
- `kv_store_pb2.py`, `kv_store_pb2_grpc.py` - Generated bindings
- `server.py` - Namespaced integer store implementation

Key patterns demonstrated:
- Exact field numbers from spec
- Namespaced state: `Dict[str, Dict[str, int]]`
- Correct defaults: Fetch→0, Delete missing→success=False/value=0, Total empty→0
- Server lifecycle: start, wait_for_termination
- Thread-safe concurrent request handling
