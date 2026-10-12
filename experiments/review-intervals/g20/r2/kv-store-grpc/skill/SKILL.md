---
name: kv-store-grpc
description: >
  Build a real Python gRPC stateful service from a proto specification.
  Covers: writing .proto files with arbitrary service/message definitions,
  generating Python gRPC bindings with grpc_tools.protoc, implementing a
  servicer with in-memory state that persists across RPC calls, and launching
  a long-lived gRPC server on a specified port. Handles varying RPC structures,
  stateful semantics (namespaces, aggregates, conditional updates, deletes),
  and runtime requirements (concurrency, readiness, lifecycle).
---

# Python gRPC Stateful Service

## Overview

This skill builds a complete Python gRPC server from a task specification that defines:
1. A `.proto` file with service and message definitions
2. Generated Python bindings
3. A server implementation with in-memory state
4. A running gRPC server on a specified port

## Step-by-Step Procedure

### 1. Install Dependencies

Install `grpcio` and `grpcio-tools` at the version specified in the task. If no version is specified, use the latest stable.

```bash
pip install grpcio==<VERSION> grpcio-tools==<VERSION>
```

**Key detail**: Both packages must be the same version. The generated `_grpc.py` file checks version compatibility at import time and will raise a `RuntimeError` if versions mismatch.

### 2. Create the Proto File

Write the `.proto` file at the exact path specified in the task. For this task family, the typical locations are:
- Proto file: `/app/<service-name>.proto` (e.g., `/app/kv-store.proto`)
- The filename determines the generated Python module names (hyphens become underscores)

**Proto file structure:**
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
}
```

**Critical rules:**
- Field numbers must be sequential starting from 1, matching the task spec exactly
- The `package` name affects the generated service path (e.g., `kvstore.KVStore/Put`)
- Use `int32` for integers, `string` for strings, `bool` for booleans, `repeated` for lists
- Nested messages are supported: define them as separate message types
- The proto filename determines the generated Python module names (hyphens become underscores)

### 3. Generate Python Bindings

```bash
cd <working_dir>
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_file>.proto
```

This produces:
- `<proto_name>_pb2.py` — message classes
- `<proto_name>_pb2_grpc.py` — stub and servicer base classes

**Important**: The proto filename with hyphens (e.g., `kv-store.proto`) generates Python modules with underscores (`kv_store_pb2.py`). Import statements in server code must use the underscore version.

### 4. Verify Generated Code Structure (MANDATORY)

**Before implementing the servicer, you MUST read the generated `_pb2_grpc.py` to extract the exact class and function names.** This is not optional—these names vary with the proto service declaration and will cause silent failures if guessed incorrectly.

```bash
# Find the servicer base class name
grep -E "^class.*Servicer" <proto_name>_pb2_grpc.py
# Example output: class KVStoreServicer(object):

# Find the registration function name
grep -E "^def add_" <proto_name>_pb2_grpc.py
# Example output: def add_KVStoreServicer_to_server(servicer, server):
```

**Why this is critical:**
- The servicer base class name is `<ServiceName>Servicer` (e.g., `KVStoreServicer`, `InventoryServicer`)
- The registration function is `add_<ServiceName>Servicer_to_server` (e.g., `add_KVStoreServicer_to_server`)
- These are derived from the `service` declaration in the .proto file, NOT from your Python class names
- If you guess incorrectly, you'll get `AttributeError` at runtime with no clear indication of the root cause

**Record these names and use them exactly in Step 5.**

### 5. Implement the Servicer

**Use the exact class names you extracted in Step 4.** The servicer class must:

1. **Inherit from the generated servicer base class** (e.g., `KVStoreServicer` from Step 4)
2. **Override each RPC method** with signature `def MethodName(self, request, context):`
3. **Use the generated message classes** for constructing responses

**Thread safety (CRITICAL):**
The gRPC server uses a `ThreadPoolExecutor` with multiple workers, so RPC methods execute concurrently on the same servicer instance. While CPython's GIL makes simple dict operations (single get/set) atomic, this is fragile:

- **Read-modify-write patterns** (increment, conditional update, compare-and-swap) are NOT atomic
- **Iteration over collections** while another thread modifies them can raise `RuntimeError`
- **Multi-step operations** on shared state can interleave and corrupt data

**Always use a `threading.Lock` to protect state access:**
```python
import threading

class MyServicer(pb2_grpc.MyServiceServicer):
    def __init__(self):
        self.state = {}
        self.lock = threading.Lock()

    def Put(self, request, context):
        with self.lock:
            # All state mutations inside the lock
            self.state[request.key] = request.value
            return pb2.PutResponse(value=request.value)

    def ListTotal(self, request, context):
        with self.lock:
            # Iteration must also be locked
            total = sum(self.state.values())
            return pb2.TotalResponse(total=total)
```

**Rule of thumb**: Lock all state access unless you can prove the operation is a single bytecode instruction.

**State management pattern:**
- Store state as instance attributes on the servicer (e.g., `self.state = {}`)
- For namespaced data: use nested dicts `{namespace: {key: value}}`
- For flat data: use a simple dict `{key: value}`
- The servicer is instantiated once and reused across all requests, so state persists

**Default value handling:**
- Missing keys should return the type's zero value (0 for int32, "" for string, False for bool) unless the spec says otherwise
- Use `.get()` with defaults: `self.state.get(ns, {}).get(key, 0)`

**Common stateful semantics to implement:**
- **Put/Set**: Create or overwrite, return the written value
- **Fetch/Get**: Return value or default for missing keys
- **Delete**: Return removed value with success flag; handle missing keys gracefully
- **Aggregate (Sum/Count/List)**: Iterate over stored values, return 0/empty for absent collections
- **Conditional updates**: Check preconditions before modifying state

**Response construction:**
```python
return pb2.ResponseType(field1=value1, field2=value2)
```

### 6. Create the Server Class and Start It

The task **requires** a class named `Server` with a `start()` method in the server file. This is not optional—tests will check for this class.

```python
import grpc
from concurrent import futures

class Server:
    def __init__(self):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        self.servicer = MyServicer()  # Your servicer class from Step 5
        
        # CRITICAL: Use the EXACT function name from Step 4 verification
        # This is derived from the proto service declaration, NOT your class name
        # Replace the function name below with the one you found in Step 4
        registration_fn = pb2_grpc.add_KVStoreServicer_to_server  # REPLACE with name from Step 4
        registration_fn(self.servicer, self.server)
        
        self.server.add_insecure_port(f'[::]:{PORT}')

    def start(self):
        self.server.start()
        self.server.wait_for_termination()

if __name__ == '__main__':
    Server().start()
```

**Alternative pattern notation:**
```
Call: pb2_grpc.add_<ServiceName>Servicer_to_server(servicer, server)
Where <ServiceName> is the exact name from Step 4's grep output.
```

**Critical details:**
- Use `futures.ThreadPoolExecutor` for concurrent request handling
- `max_workers=10` is a safe default; increase for high-concurrency requirements
- **`add_<ServiceName>Servicer_to_server` is derived from the proto `service` declaration**, not your Python class name. For `service KVStore`, the function is `add_KVStoreServicer_to_server`. Always verify by reading the generated `_pb2_grpc.py` file for the exact function name.
- `add_insecure_port('[::]:PORT')` binds to all interfaces on the specified port
- `wait_for_termination()` blocks the main thread, keeping the server alive
- The server must be started as a background process or the main process

### 7. Launch the Server

**CRITICAL REQUIREMENT**: The server MUST be left running after implementation. Tests will connect to it and make RPC calls. Do not stop or exit the server process.

Start the server as a background process with robust lifecycle management:

```bash
# Kill any stale server from previous runs
pkill -f 'python3 server.py' 2>/dev/null || true
sleep 1

# Start server with nohup to prevent SIGHUP termination
cd /app && nohup python3 server.py > /app/server.log 2>&1 &
echo $! > /tmp/server.pid

# Readiness loop: poll until server accepts connections
python3 -c "
import time, grpc, sys
for i in range(20):
    try:
        channel = grpc.insecure_channel('localhost:PORT')
        grpc.channel_ready_future(channel).result(timeout=1)
        print(f'Server ready after {(i+1)*0.5:.1f}s')
        channel.close()
        sys.exit(0)
    except Exception:
        time.sleep(0.5)
print('Server failed to start')
sys.exit(1)
"
```

**Why this matters:**
- `nohup` prevents the server from being killed if the parent shell exits
- Output redirect captures logs for debugging startup failures
- Readiness loop is faster than blind `sleep` when the server starts quickly, and more reliable when it's slow
- Port cleanup prevents "address already in use" errors from stale processes

**Note**: Do NOT use `ps`, `ss`, or `netstat` to verify the server is running—these utilities are often missing in minimal containers. The readiness loop above uses gRPC connectivity checks, which work in any environment.

**For servers with startup delays**: Increase the readiness loop iterations or timeout. Some servers may need time to load data or initialize resources.

### 8. Verify with a Test Client

Always verify the server works by creating a client and testing each RPC:

```python
import grpc
import pb2
import pb2_grpc

channel = grpc.insecure_channel('localhost:PORT')
stub = pb2_grpc.ServiceStub(channel)

# Test each RPC method
response = stub.MethodName(pb2.RequestType(...))
assert response.field == expected_value

channel.close()
```

## Variation Handling

### RPC API Structure Variations

- **More RPCs**: Add each to the proto service block and implement each as a servicer method
- **Complex messages**: Use nested messages, `repeated` fields, `enum` types as specified
- **Naming variations**: Follow the exact names in the spec; the generated code uses these names verbatim
- **Multiple services**: If the spec defines multiple services, implement separate servicers and register each

### Stateful Service Semantics Variations

- **Multiple namespaces**: Use nested dict structure; ensure isolation between namespaces
- **Delete semantics**: Return both success flag and the removed value; handle missing keys
- **Aggregate operations**: Sum/count/list operations over collections; return 0/empty for absent
- **Conditional updates**: Check conditions before modifying; return appropriate status
- **Multi-key operations**: Handle batch get/set atomically within the servicer method

### Runtime Requirements Variations

- **Concurrency**: Increase `max_workers` in ThreadPoolExecutor for burst handling
- **Startup delays**: Add readiness polling or longer sleep before test connections
- **Long-lived sessions**: Ensure `wait_for_termination()` is used; handle graceful shutdown
- **Repeated channel creation**: The server handles this naturally; each new channel gets a fresh connection to the same servicer instance

## Troubleshooting

1. **Import errors in generated code**: Ensure proto filename matches import (hyphens → underscores)
2. **Version mismatch errors**: grpcio and grpcio-tools must be the same version
3. **Port already in use**: Kill existing process with `pkill -f 'python3 server.py'` or use a different port
4. **Connection refused**: Use readiness loop instead of blind sleep; check server.log for startup errors
5. **State not persisting**: Ensure servicer is instantiated once in Server.__init__, not per-request
6. **Race conditions / data corruption**: Add `threading.Lock` around all state access; lock iteration over collections
7. **Server killed unexpectedly**: Use `nohup` to prevent SIGHUP termination; redirect output to log file
8. **RuntimeError during iteration**: Dict/list modified by another thread; ensure lock covers the entire iteration
9. **AttributeError on `add_*_to_server`**: The function name is `add_<ProtoServiceName>Servicer_to_server`, derived from the `service` declaration in the .proto file, NOT from your Python class name. Read the generated `_pb2_grpc.py` to find the exact function name.
10. **`ps`/`ss`/`netstat` not found**: Minimal containers lack these utilities. Verify the server is running by making a gRPC client call instead:
    ```bash
    python3 -c "import grpc; ch = grpc.insecure_channel('localhost:PORT'); grpc.channel_ready_future(ch).result(timeout=2); print('Server alive'); ch.close()"
    ```
    This is more reliable than process inspection and works in any environment with Python and grpcio installed.
