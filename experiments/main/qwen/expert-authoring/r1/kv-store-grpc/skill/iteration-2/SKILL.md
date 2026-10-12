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

Follow these steps in order. Do not skip verification.

### Step 1 — Parse the Task Specification

Before writing any code, extract these items from the task instruction:

| Item | Where to find it |
|------|-----------------|
| `grpcio` / `grpcio-tools` versions | Explicit version pins in the instruction |
| Proto file path | e.g. `/app/kv-store.proto` |
| Service name | PascalCase, e.g. `KVStore` |
| Each RPC | Method name, request message, response message |
| Each message | Field name, protobuf type, field number |
| State semantics | Default values, overwrite rules, delete behavior, aggregation |
| Server port | Numeric, e.g. `5328` |
| Server file / class | e.g. `/app/server.py`, class `Server` |

**Record every RPC in a table before coding.** Missing a field or field number
is the most common source of test failures.

### Step 2 — Install Dependencies

```bash
pip3 install grpcio==<VERSION> grpcio-tools==<VERSION>
```

Verify:
```bash
python3 -c "import grpc; print(grpc.__version__)"
```

### Step 3 — Write the Proto File and Generate Bindings

Do both in a single shell command to reduce round-trips:

```bash
cat > /app/<PROTO_FILENAME>.proto << 'EOF'
syntax = "proto3";
package <lowercase_service_name>;

service <ServiceName> {
  rpc <MethodName>(<MethodRequest>) returns (<MethodResponse>);
  // ... one rpc line per RPC
}

// One message block per request/response type.
// Field numbers start at 1 and are unique within each message.
message <MethodRequest> {
  <type> <field_name> = <field_number>;
}
// ...
EOF

cd /app && python3 -m grpc_tools.protoc \
  -I. --python_out=. --grpc_python_out=. <PROTO_FILENAME>.proto \
  && ls *_pb2*.py
```

**Critical naming rule**: If the proto file is named `my-service.proto`, the
generated files are `my_service_pb2.py` and `my_service_pb2_grpc.py`
(hyphens → underscores). Always `ls` to confirm.

Verify imports:
```bash
cd /app && python3 -c "import <module>_pb2; import <module>_pb2_grpc; print('OK')"
```

**Generated artifacts:**

| Symbol | Pattern |
|--------|---------|
| Message classes | `<MessageName>` in `*_pb2` |
| Stub class | `<ServiceName>Stub` in `*_grpc` |
| Servicer base | `<ServiceName>Servicer` in `*_grpc` |
| Registration fn | `add_<ServiceName>Servicer_to_server` in `*_grpc` |

**Proto3 field-type quick reference:**
`string`, `int32`, `int64`, `bool`, `float`, `double`, `bytes`,
`uint32`, `uint64`, `sint32`, `sint64`.
For `repeated`, `enum`, nested `message`, `map<K,V>`, and `oneof`
fields, see Section 3 (Decision Rules).

### Step 4 — Implement the Server

Write `server.py` matching the exact class name from the task. Template:

```python
import sys
sys.path.insert(0, '/app')  # ensure pb2 modules are importable

import grpc
from concurrent import futures
from collections import defaultdict
import threading
import <module>_pb2
import <module>_pb2_grpc


class Server(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        self._lock = threading.Lock()
        # Choose the right data structure for the task.
        # Namespaced KV: defaultdict(dict) → self._store[ns][key]
        # Flat KV:       {}               → self._store[key]
        self._store = defaultdict(dict)

    def <MethodName>(self, request, context):
        with self._lock:
            # Implement logic; return the correct response message type.
            return <module>_pb2.<ResponseMessage>(field=value)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<PORT>')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

**Implementation rules (apply to every RPC):**

1. **Thread safety**: Every state read/write must be inside `with self._lock`.
   gRPC dispatches on a thread pool; without the lock you get data races.

2. **Correct response type**: Each RPC must `return` an instance of its
   specific `<module>_pb2.<ResponseMessage>`.

3. **Default values for missing data**: Return proto3 defaults
   (`0` for int, `""` for string, `false` for bool) unless the task
   specifies otherwise.

4. **Namespace isolation**: If the task has namespaces, use nested dicts:
   `self._store = defaultdict(dict)`. Access as `self._store[ns][key]`.

5. **Put/Set**: Usually creates-or-overwrites. Return the written value.
   Watch for conditional-update variants ("set only if absent").

6. **Delete**: Pop the key. Return `(success=True, value=<removed>)`.
   Missing key → `(success=False, value=0)`.

7. **Aggregate reads** (sum, count, list): Compute inside the lock over
   the current state snapshot.

8. **sys.path**: Add `sys.path.insert(0, '/app')` at the top of server.py
   so the pb2 modules import correctly regardless of working directory.

### Step 5 — Start the Server and Verify

**Start the server with `nohup` so it persists** even if the parent shell
exits or the test runner creates a new shell:

```bash
# Kill any prior instance first
kill $(pidof -f "python3 server.py") 2>/dev/null; sleep 1

# Start with nohup; disown to detach from shell
cd /app && nohup python3 server.py > /app/server.log 2>&1 &
disown
sleep 2
```

**Verify with a TCP socket check (the ONLY reliable method in this
container):**

```bash
python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = s.connect_ex(('localhost', <PORT>))
s.close()
print('Server is UP on port <PORT>' if result == 0 else 'SERVER NOT RUNNING')
"
```

> **⚠ Do NOT rely on `pidof`, `ps`, or `pgrep` for liveness checks.**
> These tools are either unavailable or return false negatives in the
> container. The socket connect test is the authoritative check.

If the port is not open, inspect the log:
```bash
cat /app/server.log
```

### Step 6 — Self-Test All RPCs

Run a comprehensive client test covering every RPC and edge case:

```bash
cd /app && python3 << 'TESTEOF'
import grpc
import <module>_pb2
import <module>_pb2_grpc

channel = grpc.insecure_channel('localhost:<PORT>')
stub = <module>_pb2_grpc.<ServiceName>Stub(channel)

# --- For each RPC, test: ---
# 1. Happy path (normal input → expected output)
# 2. Edge case (missing key, empty namespace, overwrite, etc.)
# 3. Cross-namespace isolation (if applicable)
# 4. State persistence (write then read via separate call)

# Example for a Put/Fetch/Delete/List service:
# r = stub.Put(pb2.PutRequest(namespace='ns1', key='a', value=10))
# assert r.value == 10, f"Put: {r.value}"
#
# r = stub.Fetch(pb2.FetchRequest(namespace='ns1', key='a'))
# assert r.value == 10, f"Fetch: {r.value}"
#
# r = stub.Fetch(pb2.FetchRequest(namespace='ns1', key='missing'))
# assert r.value == 0, f"Fetch missing: {r.value}"
#
# r = stub.Delete(pb2.DeleteRequest(namespace='ns1', key='a'))
# assert r.success and r.value == 10
#
# r = stub.Delete(pb2.DeleteRequest(namespace='ns1', key='a'))
# assert not r.success and r.value == 0

# Test cross-channel persistence:
# ch2 = grpc.insecure_channel('localhost:<PORT>')
# stub2 = <module>_pb2_grpc.<ServiceName>Stub(ch2)
# ... read data written by stub ...
# ch2.close()

channel.close()
print("All self-tests passed")
TESTEOF
```

If any assertion fails: read the error, fix server.py, kill the old server,
restart, and re-test.

**Final liveness confirmation (socket check only):**
```bash
python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
r = s.connect_ex(('localhost', <PORT>))
s.close()
print('UP' if r == 0 else 'DOWN')
"
```

---

## 3. Decision Rules by Variation Axis

### rpc_api_structure

| Situation | Action |
|-----------|--------|
| Single service, ≤4 RPCs, scalar fields | Standard template above |
| Many RPCs (>5) | Implement every method; double-check all field numbers |
| `repeated` fields | Populate with `response.field.append(v)` or `.extend([...])` |
| Nested messages | Define sub-messages in proto; access as `request.sub.field` |
| `enum` fields | Define enum in proto; compare as integers in Python |
| `oneof` fields | Check with `request.WhichOneof('group_name')` |
| `map<K,V>` fields | Behave like Python dicts in generated code |

### stateful_service_semantics

| Semantic | Implementation pattern |
|----------|----------------------|
| Flat key-value | `self._store = {}` with `self._store[key] = value` |
| Namespaced store | `self._store = defaultdict(dict)` |
| Multiple collections | Separate dicts per collection |
| Counter / accumulator | `self._counters = defaultdict(int)` with `+=` |
| Ordered log | `self._log = []` with `.append()` inside lock |
| Conditional update | Read-then-write inside lock; return status |
| Bulk / multi-key | Iterate inside lock; aggregate result |
| Reset / clear | `.clear()` on the target dict inside lock |

### runtime_interaction_requirements

| Requirement | Action |
|-------------|--------|
| Server must survive test duration | Use `nohup ... &` + `disown` + `wait_for_termination()` |
| High concurrency | Increase `max_workers` (e.g. 50) |
| Readiness check | Sleep after start; socket-connect to confirm |
| Specific port | `server.add_insecure_port('[::]:<PORT>')` |
| Re-entrant channels | State lives in Servicer instance, shared across all clients |

---

## 4. Common Pitfalls

1. **Wrong generated module name**: `foo-bar.proto` → `foo_bar_pb2.py`.
   Always `ls` after generation.

2. **Missing sys.path**: Add `sys.path.insert(0, '/app')` at the top of
   server.py so imports work regardless of working directory.

3. **No threading lock**: Data races cause intermittent failures. Every
   state access must be inside `with self._lock`.

4. **Wrong response type**: Each RPC returns its own response message.
   Returning the wrong type causes serialization errors.

5. **Field number collisions**: Each field in a message must have a unique
   number. Reusing numbers causes compilation errors.

6. **Server dies with parent shell**: Use `nohup python3 server.py &`
   followed by `disown` to ensure the server survives shell exit.

7. **False liveness readings**: `pidof` and `ps` are unreliable in this
   container. Use the TCP socket connect test as the sole authority.

8. **Port conflicts**: Kill prior servers before restarting. If the port
   is still busy, `fuser -k <PORT>/tcp` or wait for TIME_WAIT to clear.

9. **Proto3 default values**: Unset fields default to `0`, `""`, `false`.
   Proto3 does not distinguish "unset" from "set to default" for scalars.

---

## 5. Self-Verification Checklist

Before declaring the task complete:

- [ ] `grpcio` and `grpcio-tools` installed at exact specified versions
- [ ] Proto file at specified path with correct syntax and all fields
- [ ] Generated `_pb2.py` and `_pb2_grpc.py` import cleanly
- [ ] `server.py` has correct class name inheriting correct Servicer base
- [ ] Every proto RPC has a corresponding method implementation
- [ ] State semantics match spec (defaults, overwrites, deletes, aggregates)
- [ ] Threading lock protects all shared state
- [ ] Server started with `nohup ... &` and `disown`
- [ ] TCP socket check confirms port is accepting connections
- [ ] Self-test exercises all RPCs including edge cases
