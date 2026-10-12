---
name: kv-store-grpc
description: >
  Build and run a Python gRPC service backed by an in-memory stateful store.
  Covers proto file authoring, code generation, servicer implementation with
  correct state semantics, and launching a long-lived server process that
  passes real gRPC client tests.
---

# KV-Store gRPC Service — Skill Guide

## 1. Family Overview

Every task in this family requires the agent to:

1. Install pinned `grpcio` and `grpcio-tools` packages.
2. Author a `.proto` file (proto3 syntax) defining a service with one or more
   unary RPCs and their request/response messages.
3. Generate Python bindings (`*_pb2.py` and `*_pb2_grpc.py`).
4. Implement a Python servicer class that manages in-memory state and fulfills
   the RPC semantics described in the task.
5. Start the gRPC server on a specified port and **leave it running** so that
   an external test harness can connect.

What varies across tasks (see `spec.yaml` axes):

| Axis | What changes |
|------|-------------|
| `rpc_api_structure` | Service name, number of RPCs, message field names/types/numbers, nested or repeated fields, enums |
| `stateful_service_semantics` | Data structures (flat dict, nested dict, list, counter), CRUD semantics, default values, multi-key ops, namespaces |
| `runtime_interaction_requirements` | Port number, concurrency expectations, startup timing, process longevity |

---

## 2. Execution Plan

Follow these steps in order. Do not skip the verification step.

### Step 1 — Parse the Task Specification

Extract and record the following from the task YAML / instruction:

- **Dependency versions**: `grpcio==X.Y.Z` and `grpcio-tools==X.Y.Z`
- **Proto file path**: e.g. `/app/kv-store.proto`
- **Service name**: e.g. `KVStore`
- **RPC list**: For each RPC, note method name, request message, response message
- **Message definitions**: For each message, note field name, protobuf type, field number
- **State semantics**: Data structure, default values, mutation rules per RPC
- **Server port**: e.g. `5328`
- **Server module path**: e.g. `/app/server.py`
- **Server class name**: e.g. `Server`

Create a quick-reference table before writing any code.

### Step 2 — Install Dependencies

```bash
pip3 install grpcio==<VERSION> grpcio-tools==<VERSION>
```

Verify:
```bash
python3 -c "import grpc; print(grpc.__version__)"
```

### Step 3 — Write the Proto File

Use **proto3** syntax. Template:

```protobuf
syntax = "proto3";
package <lowercase_service_name>;

service <ServiceName> {
  rpc <MethodName>(<MethodRequest>) returns (<MethodResponse>);
  // ... more RPCs
}

message <MethodRequest> {
  <type> <field_name> = <field_number>;
  // ...
}

message <MethodResponse> {
  <type> <field_name> = <field_number>;
  // ...
}
```

**Rules and pitfalls:**

- Field numbers start at **1** and must be unique within each message.
- Protobuf scalar types: `string`, `int32`, `int64`, `bool`, `float`, `double`,
  `bytes`, `uint32`, `uint64`, `sint32`, `sint64`, `fixed32`, `fixed64`,
  `sfixed32`, `sfixed64`.
- For `enum` fields, define the enum type at package scope and use it as the
  field type. The first enum value must be `UNSPECIFIED = 0` (or equivalent)
  per proto3 convention.
- For `repeated` fields, prefix the type with `repeated`.
- For nested messages, either define them inline or at package scope and
  reference by name.
- The `package` directive determines the fully-qualified name but does **not**
  affect generated Python module names.

### Step 4 — Generate Python Bindings

```bash
python3 -m grpc_tools.protoc \
  -I<proto_dir> \
  --python_out=<output_dir> \
  --grpc_python_out=<output_dir> \
  <proto_dir>/<proto_filename>.proto
```

**Critical naming rule**: If the proto file is named `my-service.proto`, the
generated files are `my_service_pb2.py` and `my_service_pb2_grpc.py`
(hyphens → underscores). Always `ls` after generation to confirm exact names.

**Generated artifacts you will use:**

| Symbol | Pattern |
|--------|---------|
| Message classes | `<MessageName>` in `*_pb2` |
| Stub class | `<ServiceName>Stub` in `*_grpc` |
| Servicer base | `<ServiceName>Servicer` in `*_grpc` |
| Registration fn | `add_<ServiceName>Servicer_to_server` in `*_grpc` |

Verify generation:
```bash
python3 -c "import <module>_pb2; import <module>_pb2_grpc; print('OK')"
```

### Step 5 — Implement the Server

Template:

```python
import grpc
from concurrent import futures
import threading
import <module>_pb2
import <module>_pb2_grpc


class Server(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        self._lock = threading.Lock()
        # Initialize state structures here
        self._store = {}

    def <MethodName>(self, request, context):
        with self._lock:
            # Implement RPC logic
            # Return <module>_pb2.<ResponseMessage>(field=value, ...)
            pass


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<PORT>')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

**Implementation decision rules:**

1. **Always use a threading lock** around state mutations. gRPC serves requests
   on a thread pool; without a lock, concurrent calls can corrupt state.

2. **Return the correct protobuf response type.** Construct it directly:
   `return <module>_pb2.<ResponseMessage>(field1=val1, field2=val2)`.

3. **Default values**: Return proto3 defaults (0 for int, "" for string, false
   for bool) when data is absent, unless the task specifies otherwise.

4. **Namespace/collection isolation**: If the task has namespaces or separate
   collections, use nested dicts: `self._store[namespace][key] = value`.

5. **Overwrite semantics**: `Put`/`Set` typically overwrites. Check the task
   for conditional-update rules (e.g., "only set if key doesn't exist").

6. **Delete semantics**: Return the removed value with a success flag. If the
   key is missing, return success=False with the default value.

7. **Aggregate reads** (sum, count, list): Compute over the current state
   snapshot inside the lock to avoid torn reads.

8. **sys.path**: If the generated files and server.py are in the same
   directory (e.g., `/app`), imports work when the working directory is that
   directory. If needed, add `sys.path.insert(0, '<dir>')` at the top of
   server.py.

### Step 6 — Start the Server and Verify

First, kill any prior server process to avoid port conflicts:

```bash
kill $(pidof -f "python3 server.py") 2>/dev/null; sleep 1
```

Then start the server in the background:

```bash
cd /app && python3 server.py &
sleep 2
```

The `&` backgrounds the process. `sleep 2` gives it time to bind the port.

**Self-test with a client script:**

```python
import grpc
import <module>_pb2
import <module>_pb2_grpc

channel = grpc.insecure_channel('localhost:<PORT>')
stub = <module>_pb2_grpc.<ServiceName>Stub(channel)

# Exercise each RPC with representative inputs
# Verify response fields match expected values
# Test edge cases: missing keys, empty namespaces, overwrites, deletes

channel.close()
```

If any assertion fails, fix the server, kill the old process, and restart.

**Confirm the server is still running before finishing:**

```bash
# Method 1: Check if the port is accepting connections (most portable)
python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = s.connect_ex(('localhost', <PORT>))
s.close()
print('Server is UP on port <PORT>' if result == 0 else 'SERVER NOT RUNNING')
"
```

```bash
# Method 2: Process check (if available)
pidof -f "python3 server.py" || echo "SERVER NOT RUNNING"
```

If neither method confirms the server is running, check for startup errors:
```bash
cd /app && python3 -c "exec(open('server.py').read().replace('server.wait_for_termination()', 'pass'))" 2>&1
```

---

## 3. Decision Rules by Variation Axis

### rpc_api_structure

| Situation | Action |
|-----------|--------|
| Single service, ≤4 RPCs, scalar fields only | Standard template above |
| Many RPCs (>5) | List all RPCs in the proto; implement each method in the servicer. Double-check field numbers across all messages |
| `repeated` fields | In Python, repeated fields are list-like. Populate with `response.items.extend([...])` or `response.items.append(...)` |
| Nested messages | Define sub-messages in proto. Access in Python as `request.sub_message.field` |
| `enum` fields | Define enum in proto. In Python, enum values are integers. Compare with `request.status == pb2.ENUM_VALUE` |
| `oneof` fields | Access with `request.WhichOneof('group_name')` to determine which field is set |
| `map<K,V>` fields | Behave like Python dicts in generated code |

### stateful_service_semantics

| Semantic | Implementation pattern |
|----------|----------------------|
| Flat key-value store | `self._store = {}` with `self._store[key] = value` |
| Namespaced store | `self._store = {}` with `self._store[ns][key] = value` |
| Multiple collections | Separate dicts: `self._users = {}`, `self._items = {}` |
| Counter / accumulator | `self._counters = {}` with increment logic |
| Ordered log / history | `self._log = []` with append; use lock for thread safety |
| Conditional update | Check current value before writing; return status indicating whether update happened |
| Bulk / multi-key ops | Iterate inside the lock; return repeated or aggregated result |
| Reset / clear | `self._store.clear()` or `self._store[ns].clear()` inside lock |

### runtime_interaction_requirements

| Requirement | Action |
|-------------|--------|
| Server must survive test duration | Use `server.wait_for_termination()` and background the process |
| High concurrency | Increase `max_workers` (e.g., 50 or 100) |
| Readiness check | Sleep after start; optionally poll with a health-check RPC or TCP connect |
| Specific port | Use `server.add_insecure_port('[::]:<PORT>')` — `[::]` binds all interfaces |
| Graceful shutdown | Not usually required for tests; `wait_for_termination()` blocks until signal |
| Re-entrant client channels | State lives in the Servicer instance, not in channels — multiple clients share state |

---

## 4. Common Pitfalls

1. **Wrong generated module name**: Proto file `foo-bar.proto` generates
   `foo_bar_pb2.py`, not `foo-bar_pb2.py`. Always `ls` to confirm.

2. **Missing sys.path**: If running server.py from a different directory,
   the import of `_pb2` modules fails. Either `cd` to the directory or
   add `sys.path.insert(0, ...)` at the top.

3. **No threading lock**: Data races under concurrent gRPC calls cause
   intermittent test failures. Always wrap state access in `with self._lock`.

4. **Wrong response type**: Each RPC must return its specific response message
   type. Returning the wrong type causes a serialization error.

5. **Field number collisions**: Each field in a message must have a unique
   number. Reusing numbers causes proto compilation errors.

6. **Forgetting to start the server**: The task requires the server to be
   **running** when tests execute. Background it with `&` and verify by
   testing the port with a socket connect or `pidof`.

7. **Port conflicts**: If a previous server is still running on the port,
   `add_insecure_port` silently fails. Kill old processes first:
   `kill $(pidof -f "python3 server.py")` or use `fuser -k <PORT>/tcp` if
   available. Verify the port is free with a socket connect test before
   restarting.

8. **Proto3 default values**: Unset fields default to `0`, `""`, `false`, or
   the first enum value. Do not confuse "field not set" with "field set to
   default" — proto3 does not distinguish these for scalar fields.

---

## 5. Self-Verification Checklist

Before declaring the task complete, confirm:

- [ ] `grpcio` and `grpcio-tools` installed at the exact versions specified
- [ ] Proto file exists at the specified path with correct syntax
- [ ] Generated `_pb2.py` and `_pb2_grpc.py` files exist and import cleanly
- [ ] `server.py` exists with the specified class name inheriting the correct
      Servicer base class
- [ ] Every RPC defined in the proto has a corresponding method implementation
- [ ] State semantics match the specification (defaults, overwrites, deletes,
      aggregates)
- [ ] Threading lock protects all shared state
- [ ] Server process is running and listening on the specified port
- [ ] A manual client test exercising all RPCs passes
- [ ] Server process is confirmed alive (port accepts connections or process is visible)
