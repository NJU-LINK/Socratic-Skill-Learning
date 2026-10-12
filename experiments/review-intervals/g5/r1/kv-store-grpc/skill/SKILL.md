---
name: kv-store-grpc
description: Build a Python gRPC stateful service with in-memory storage, implementing custom RPC methods with proper proto definitions, generated bindings, and server lifecycle management.
---

# gRPC Stateful Service Implementation

This skill guides the implementation of a Python gRPC server with in-memory state management. The service definition (RPCs, messages, fields) and state semantics (data structure, CRUD behavior, aggregates) are specified per-task; this skill provides the general procedure.

**⚠️ WORKFLOW**: 
1. **Phase 0: Extract parameters** from the task instruction (service name, RPCs, state structure, port, etc.)
2. **Phases 1-6: Fill templates** with your extracted parameters to create proto, generate bindings, implement server, and launch

**About `assets/`**: The assets directory contains **reference examples** (e.g., `assets/v01/`) that demonstrate the pattern. **Do NOT copy them verbatim.** Each task variant has different parameters. Extract your parameters first, then construct your implementation from the templates.

## Phase 0: Parameter Extraction (DO THIS FIRST)

**⚠️ CRITICAL: Extract parameters from the task instruction BEFORE reading any assets or writing any code.**

The `assets/` directory contains **reference examples only**. Do NOT copy them verbatim. Each task variant has different service definitions, state semantics, and runtime requirements. You must extract the specific parameters from your task instruction first.

### Extraction Checklist

Systematically extract the following 7 parameters from the task instruction:

1. **Service name**: What is the gRPC service called? (e.g., `KVStore`, `UserService`)
2. **Proto filename**: What should the `.proto` file be named? (e.g., `kv-store.proto`)
   - Derive module prefix: replace hyphens with underscores (e.g., `kv-store.proto` → `kv_store`)
3. **RPC definitions**: For each RPC method, extract:
   - Method name (e.g., `Put`, `Fetch`, `Delete`)
   - Request message name and fields (field name, type, field number)
   - Response message name and fields (field name, type, field number)
4. **State data structure**: How should in-memory state be organized?
   - Flat key-value? (e.g., `{key: value}`)
   - Namespaced? (e.g., `{namespace: {key: value}}`)
   - Multiple collections? (e.g., separate dicts for users, sessions, etc.)
5. **Per-RPC state semantics**: What does each RPC do to the state?
   - Create/overwrite behavior
   - Default values for missing keys (0 for int, "" for string, False for bool)
   - Delete behavior (return removed value? success flag?)
   - Aggregate operations (sum, count, etc.)
6. **Port number**: What port should the server listen on? (e.g., `5328`, `50051`)
7. **Server class name**: What should the servicer class be named? (e.g., `Server`, `KVStoreServer`)

### Example Extraction (v01)

From the v01 task instruction:
- Service: `KVStore`, Proto: `kv-store.proto` → module: `kv_store`
- RPCs: `Put`, `Fetch`, `Delete`, `ListNamespaceTotal` (see task.yaml for field details)
- State: `{namespace: {key: int32}}`
- Semantics: Put overwrites, Fetch returns 0 for missing, Delete returns success+value, ListNamespaceTotal sums values
- Port: `5328`, Class: `Server`

### After Extraction

Once you have extracted all 7 parameters, proceed through Phases 1-6 by filling in the templates with your extracted values. The `assets/v01/` directory contains a working example of this pattern, but you should construct your implementation from the extracted parameters, not by copying the assets.

## Phase 1: Environment Setup

1. **Install gRPC packages** (versions specified in task, or use latest stable):
   ```bash
   pip install grpcio==<version> grpcio-tools==<version>
   ```
   Common versions: 1.73.0, 1.62.0, or omit version for latest.

2. **Verify installation**:
   ```bash
   python3 -c "import grpc; print(grpc.__version__)"
   ```

## Phase 2: Proto File Creation

Create the `.proto` file at the path specified in the task (typically `/app/<service-name>.proto`).

### Proto File Structure

```protobuf
syntax = "proto3";

package <package-name>;

service <ServiceName> {
  // RPC definitions from task spec
  rpc <MethodName>(<RequestMessage>) returns (<ResponseMessage>);
  // ... more RPCs
}

// Message definitions from task spec
message <RequestMessage> {
  <field-type> <field-name> = <field-number>;
  // ... more fields
}

message <ResponseMessage> {
  <field-type> <field-name> = <field-number>;
  // ... more fields
}
```

### Key Points

- **Field numbers** must match the task specification exactly (1, 2, 3, etc.)
- **Field types**: Use `string`, `int32`, `bool`, `float`, `double`, etc.
- **Message names**: Must match task spec exactly (case-sensitive)
- **Service name**: Must match task spec exactly
- **Proto filename**: Typically matches service name in kebab-case (e.g., `kv-store.proto`)

### Example Proto (v01 instance)

```protobuf
syntax = "proto3";
package kvstore;

service KVStore {
  rpc Put(PutRequest) returns (PutResponse);
  rpc Fetch(FetchRequest) returns (FetchResponse);
  rpc Delete(DeleteRequest) returns (DeleteResponse);
  rpc ListNamespaceTotal(ListNamespaceTotalRequest) returns (ListNamespaceTotalResponse);
}

message PutRequest {
  string namespace = 1;
  string key = 2;
  int32 value = 3;
}

message PutResponse {
  int32 value = 1;
}

message FetchRequest {
  string namespace = 1;
  string key = 2;
}

message FetchResponse {
  int32 value = 1;
}

message DeleteRequest {
  string namespace = 1;
  string key = 2;
}

message DeleteResponse {
  bool success = 1;
  int32 value = 2;
}

message ListNamespaceTotalRequest {
  string namespace = 1;
}

message ListNamespaceTotalResponse {
  int32 total = 1;
}
```

## Phase 3: Generate Python Bindings

Run from the directory containing the `.proto` file:

```bash
cd /app
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto-filename>.proto
```

This generates:
- `<proto-name>_pb2.py` - Message classes
- `<proto-name>_pb2_grpc.py` - Service stubs and servicer base class

### ⚠️ CRITICAL: Proto Filename to Module Name Mapping

**The protoc tool replaces hyphens with underscores in generated Python module names.**

Examples:
- `kv-store.proto` → `kv_store_pb2.py`, `kv_store_pb2_grpc.py`
- `my-service.proto` → `my_service_pb2.py`, `my_service_pb2_grpc.py`
- `user_management.proto` → `user_management_pb2.py`, `user_management_pb2_grpc.py`

**Rule**: Take the proto filename (without `.proto` extension), replace all hyphens `-` with underscores `_`, then append `_pb2` or `_pb2_grpc`.

**Common mistake**: If your proto is `my-service.proto`, import `my_service_pb2` (correct). Do NOT try `my-service_pb2` (invalid — hyphens are not valid in Python identifiers) or `my_service` (missing the `_pb2` suffix).

### Generated Class Names

From a proto file `my-service.proto` with service `MyService`:

- **Servicer base class**: `my_service_pb2_grpc.MyServiceServicer`
- **Add to server function**: `my_service_pb2_grpc.add_MyServiceServicer_to_server(servicer, server)`
- **Client stub**: `my_service_pb2_grpc.MyServiceStub`
- **Message classes**: `my_service_pb2.<MessageName>` (e.g., `my_service_pb2.PutRequest`)

## Phase 4: Implement the Servicer

Create the server implementation file (typically `/app/server.py`).

### Server Class Structure

```python
import grpc
import threading
from concurrent import futures
import <module-name>_pb2
import <module-name>_pb2_grpc


class Server(<module-name>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize state storage based on task semantics
        # Common patterns:
        # - Flat dict: self.store = {}  # {key: value}
        # - Namespaced dict: self.store = {}  # {namespace: {key: value}}
        # - Multiple collections: self.users = {}, self.sessions = {}, etc.
        
        # CRITICAL: Add thread safety for concurrent requests
        self.lock = threading.Lock()

    def <MethodName>(self, request, context):
        # Extract fields from request
        # field_value = request.<field-name>
        
        # CRITICAL: Protect state modifications with lock
        with self.lock:
            # Perform operation on state
            # Apply task-specific semantics (CRUD, aggregates, etc.)
            pass
        
        # Return response message
        return <module-name>_pb2.<ResponseMessage>(<field>=<value>)
```

### State Management Patterns

**Pattern 1: Flat Key-Value Store**
```python
self.store = {}  # {key: value}

def Get(self, request, context):
    value = self.store.get(request.key, <default>)
    return pb2.GetResponse(value=value)
```

**Pattern 2: Namespaced Store**
```python
self.store = {}  # {namespace: {key: value}}

def Put(self, request, context):
    ns = request.namespace
    if ns not in self.store:
        self.store[ns] = {}
    self.store[ns][request.key] = request.value
    return pb2.PutResponse(value=request.value)

def Fetch(self, request, context):
    value = self.store.get(request.namespace, {}).get(request.key, 0)
    return pb2.FetchResponse(value=value)
```

**Pattern 3: Delete with Success Flag**
```python
def Delete(self, request, context):
    key = request.key
    if key in self.store:
        value = self.store.pop(key)
        return pb2.DeleteResponse(success=True, value=value)
    else:
        return pb2.DeleteResponse(success=False, value=0)
```

**Pattern 4: Aggregate Operations**
```python
def Sum(self, request, context):
    total = sum(self.store.get(request.namespace, {}).values())
    return pb2.SumResponse(total=total)
```

### Critical Implementation Details

1. **State must be instance-level**: Store state on `self`, not as module globals. This ensures state persists across RPC calls and client channels.

2. **Thread safety for concurrent requests**: gRPC uses `ThreadPoolExecutor`, so multiple RPC handlers can execute simultaneously. **Always protect shared state with a lock**:
   ```python
   self.lock = threading.Lock()
   
   def Put(self, request, context):
       with self.lock:
           # Modify state here
   ```
   Without locking, concurrent writes can cause race conditions, data corruption, or incorrect results. This is especially critical under burst loads or concurrent client connections.

3. **Method signatures**: Each RPC method takes `(self, request, context)`.

4. **Default values**: When a key is missing, return the appropriate default (0 for int, "" for string, False for bool) as specified in the task.

5. **Return response objects**: Always return the generated response message class, not raw values.

## Phase 5: Server Lifecycle

### Server Function

```python
def serve():
    # Create server with thread pool
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # Add servicer
    <module>_pb2_grpc.add_<Service>Servicer_to_server(Server(), server)
    
    # Bind to port (from task spec, default 50051)
    port = <port-number>
    server.add_insecure_port(f'[::]:{port}')
    
    # Start server (non-blocking)
    server.start()
    
    # Block until termination
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

### Launch the Server

The server must be running when tests execute. Launch as a background process:

```bash
cd /app
python3 server.py &
sleep 2  # Allow time for port binding
```

**Verify the server is running**:

**⚠️ DO NOT use `ps aux` or `ps` commands** — they are not available in minimal containers and will fail.

Instead, verify via a gRPC call:
```bash
python3 -c "
import grpc
import <module>_pb2
import <module>_pb2_grpc
channel = grpc.insecure_channel('localhost:<port>')
stub = <module>_pb2_grpc.<Service>Stub(channel)
# Make a simple RPC call to verify connectivity
print('Server is running')
"
```

If the call succeeds without error, the server is running and ready.

### Common Runtime Issues

1. **Port already in use**: Kill existing server process before restarting
   ```bash
   pkill -f "python3 server.py"
   sleep 1
   ```

2. **Server not ready**: Add sleep after launch to allow port binding
   ```bash
   python3 server.py &
   sleep 2
   ```

3. **Import errors**: Ensure generated `_pb2.py` files are in the same directory as `server.py`, or adjust `sys.path`.

## Phase 6: Verification

Write a test client to verify all RPCs work correctly:

```python
import grpc
import <module>_pb2
import <module>_pb2_grpc

channel = grpc.insecure_channel('localhost:<port>')
stub = <module>_pb2_grpc.<Service>Stub(channel)

# Test each RPC method
# Example for Put/Fetch:
resp = stub.Put(<module>_pb2.PutRequest(<field1>=<val1>, <field2>=<val2>))
assert resp.<field> == <expected>

resp = stub.Fetch(<module>_pb2.FetchRequest(<field1>=<val1>))
assert resp.<field> == <expected>

print("All tests passed!")
```

## Checklist

- [ ] gRPC packages installed
- [ ] Proto file created with correct service, RPCs, messages, and field numbers
- [ ] Python bindings generated (`_pb2.py` and `_pb2_grpc.py`)
- [ ] Servicer class implements all RPC methods with correct state semantics
- [ ] State storage is instance-level (on `self`)
- [ ] Server listens on the specified port
- [ ] Server launched as background process
- [ ] Server verified with test client

## Variation Handling

### Different RPC Structures

- **More RPCs**: Add additional `rpc` definitions in proto and corresponding methods in servicer
- **Nested messages**: Define nested message types in proto, access via `request.field.subfield`
- **Repeated fields**: Use `repeated` keyword in proto, access as Python lists
- **Enums**: Define enum types in proto, use integer values in Python

### Different State Semantics

- **Multiple namespaces**: Use nested dict `{namespace: {key: value}}`
- **Conditional updates**: Check conditions before modifying state
- **Aggregate reads**: Use `sum()`, `len()`, or other aggregations on state
- **Multi-key operations**: Iterate over state or accept lists of keys

### Different Runtime Requirements

- **Different port**: Change port number in `server.add_insecure_port()`
- **Concurrent requests**: Increase `max_workers` in `ThreadPoolExecutor`
- **Startup delays**: Add longer sleep after server launch
- **Health checks**: Implement additional RPC for health/status

## Reference Implementation: v01 Example

See `assets/v01/` for a **complete working example** of a namespaced integer key-value store:
- `kv-store.proto` - Proto definition
- `server.py` - Thread-safe server implementation

**⚠️ DO NOT COPY THESE FILES VERBATIM.** They are reference examples to help you understand the pattern. For your task:
1. Extract parameters from your task instruction (Phase 0)
2. Fill the templates in Phases 1-6 with your extracted parameters
3. Construct your own proto and server.py

The v01 example demonstrates:
- Service `KVStore` with 4 RPCs (Put, Fetch, Delete, ListNamespaceTotal)
- Namespaced state `{namespace: {key: value}}`
- Thread-safe operations with `threading.Lock`
- Proper default handling (0 for missing keys, success flag for delete)

For a different task variant, you would extract different parameters (different service name, different RPCs, different state structure, different port) and fill the templates accordingly.
