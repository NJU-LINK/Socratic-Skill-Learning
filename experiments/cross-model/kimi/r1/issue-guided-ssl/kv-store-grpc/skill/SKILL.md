---
name: kv-store-grpc
description: Build and run stateful Python gRPC services with namespaced key-value semantics, covering proto definition, code generation, thread-safe server implementation, daemonized lifecycle management, and client verification.
---

# KV Store gRPC Skill

This skill covers the end-to-end workflow for building stateful Python gRPC key-value stores with namespace isolation.

## Family Dimensions (from spec.yaml)

1. **rpc_api_structure**: Varying proto complexity - services with multiple RPCs, nested/repeated fields, enums
2. **stateful_service_semantics**: Varying state behaviors - deletes, resets, conditional updates, multi-key operations
3. **runtime_interaction_requirements**: Varying serving conditions - long-lived tests, concurrent requests, readiness requirements

## Core Workflow

### Step 1: Extract Task Parameters

From the task specification, extract:
- Proto filename (e.g., `kv-store.proto`)
- Service name (e.g., `KVStore`)
- RPC methods with exact message fields, types, and **field numbers**
- Target class name for server (e.g., `Server`)
- Target port (e.g., `5328`)
- Output paths for generated files

**Critical**: Field numbers in proto must match task specification exactly. Task may specify `string field 1`, `int32 field 3`, etc. Wrong field numbers cause wire-format incompatibility.

**Never hardcode** - these vary across family instances.

### Step 2: Write Proto File

```protobuf
syntax = "proto3";

package <package_name>;

service <ServiceName> {
  rpc <MethodName>(<RequestType>) returns (<ResponseType>);
  // ... more RPCs
}

message <RequestType> {
  <type> <field_name> = <field_number>;
}

message <ResponseType> {
  <type> <field_name> = <field_number>;
}
```

### Step 3: Generate Python Bindings

```bash
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_file>.proto
```

**Naming mechanics**: The proto filename is transformed:
- `kv-store.proto` → `kv_store_pb2.py` and `kv_store_pb2_grpc.py`
- Non-alphanumeric characters become underscores
- **Always `ls` outputs and import what actually exists**

### Step 4: Implement Thread-Safe Server

Core pattern (see `scripts/server_template.py` for complete working example):

```python
import threading
from collections import defaultdict
from concurrent import futures
import grpc
import <proto_module>_pb2
import <proto_module>_pb2_grpc


class Server(<proto_module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        self._lock = threading.Lock()
        self._store = defaultdict(dict)  # namespace -> {key: value}
    
    def <Method>(self, request, context):
        with self._lock:
            # ... implementation
            pass


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=32))
    <proto_module>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    if server.add_insecure_port("[::]:<port>") == 0:
        raise SystemExit("bind failed")
    server.start()
    server.wait_for_termination()  # Blocks forever


if __name__ == "__main__":
    serve()
```

**Critical**: Always use `threading.Lock()` - RPC handlers run concurrently on thread pool threads.

### Step 5: Handle Port Conflicts and Daemonize

**Important**: The task container is minimal - `ps`, `pgrep`, `pkill`, `ss`, `netstat`, `lsof`, `fuser` are NOT available. Use `/proc`-based process management instead.

Before starting, kill any existing server processes:

```bash
python3 - <<'PYEOF'
import os, signal
for pid in os.listdir('/proc'):
    if pid.isdigit():
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                if b'server.py' in f.read():
                    os.kill(int(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, FileNotFoundError):
            pass
PYEOF
sleep 1
```

Then daemonize the server to survive shell exit:

```bash
cd /app && nohup setsid python3 server.py >/app/server.log 2>&1 </dev/null &
```

Components:
- Python `/proc` scan: Find and kill existing server processes without external tools
- `nohup`: Ignore SIGHUP when terminal closes
- `setsid`: Create new session, detach from terminal
- `</dev/null`: Redirect stdin to prevent blocking
- `>/app/server.log 2>&1`: Capture output for debugging

Check logs if server fails silently:
```bash
cat /app/server.log
```

### Step 6: Verify with Client

Test pattern covering state semantics (see `scripts/smoke_client.py` for complete working example):

```python
import grpc
import <proto>_pb2 as pb
import <proto>_pb2_grpc as pbg

# Connect and wait for readiness
ch = grpc.insecure_channel("localhost:<port>")
grpc.channel_ready_future(ch).result(timeout=10)
stub = pbg.<ServiceName>Stub(ch)

# Basic operations
stub.Put(pb.PutRequest(namespace="ns", key="k", value=1))

# Fresh channel test (cross-channel persistence)
stub2 = pbg.<ServiceName>Stub(grpc.insecure_channel("localhost:<port>"))
assert stub2.Fetch(pb.FetchRequest(namespace="ns", key="k")).value == 1

# Missing key semantics
assert stub2.Fetch(pb.FetchRequest(namespace="ns", key="missing")).value == 0

# Empty namespace
assert stub2.ListNamespaceTotal(pb.ListNamespaceTotalRequest(namespace="empty")).total == 0

# Delete semantics
del_ok = stub2.Delete(pb.DeleteRequest(namespace="ns", key="k"))
assert (del_ok.success, del_ok.value) == (True, 1)
del_missing = stub2.Delete(pb.DeleteRequest(namespace="ns", key="k"))
assert (del_missing.success, del_missing.value) == (False, 0)
```

## State Implementation Patterns

### Namespace-Isolated Store
```python
self._store = defaultdict(dict)  # {namespace: {key: value}}
```

### Thread-Safe Access
Always wrap state access in `with self._lock:`.

### Missing Key Handling
```python
# For Fetch: return default
default_value = self._store.get(namespace, {}).get(key, 0)

# For Delete: check membership before pop
ns = self._store.get(request.namespace)
if ns and request.key in ns:
    value = ns.pop(request.key)
    return DeleteResponse(success=True, value=value)
else:
    return DeleteResponse(success=False, value=0)
```

## Quick Reference Checklist

When solving a kv-store-grpc task, follow this sequence:

1. **Install packages**: `pip install grpcio==<version> grpcio-tools==<version>`
2. **Extract from task**: proto filename, service name, RPCs with field numbers, port, class name
3. **Write proto**: Match field numbers exactly as specified in task
4. **Generate bindings**: `python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <file>.proto`
5. **List outputs**: `ls *_pb2.py` to confirm module names
6. **Kill existing** (if any): Use Python `/proc` scan from Step 5 above
7. **Implement server**: Copy from `scripts/server_template.py`, adjust imports and class name
8. **Start daemonized**: `nohup setsid python3 server.py >server.log 2>&1 </dev/null &`
9. **Verify**: Use `grpc.channel_ready_future(ch).result(timeout=10)` then test all RPCs
10. **Debug if needed**: `cat server.log`

## Stateful Service Semantics Patterns

All state operations must be atomic within a single lock acquisition:

```python
# Conditional update (compare-and-swap)
def ConditionalUpdate(self, request, context):
    with self._lock:
        ns = self._store.get(request.namespace, {})
        if ns.get(request.key) == request.expected:
            ns[request.key] = request.value
            return pb.Resp(success=True)
        return pb.Resp(success=False)

# Multi-key read
def FetchMany(self, request, context):
    with self._lock:
        ns = self._store.get(request.namespace, {})
        return pb.FetchManyResp(
            values=[ns.get(k, 0) for k in request.keys])

# Namespace reset
def ResetNamespace(self, request, context):
    with self._lock:
        self._store.pop(request.namespace, None)
        return pb.ResetResp()
```

**Rule**: The entire decision-and-mutation sequence must live inside a single `with self._lock:` block.

## Files in This Skill

- `scripts/server_template.py` - Complete working server implementation for v01
- `scripts/generate.sh` - Proto compilation script with verification
- `scripts/smoke_client.py` - Complete working verification client with concurrency burst test
- `references/gotchas.md` - Detailed pitfalls, edge cases, and verified tool inventory
- `references/proto3-python.md` - Proto3 to Python mechanics for enums, repeated, nested, map, oneof, presence
