# Stateful Service Patterns

## State Structure Patterns

### Flat Dictionary
```python
self._store = {}  # {key: value}
```
Use when: single namespace, simple key-value lookup.

### Nested Dictionary (Namespaced)
```python
self._store = {}  # {namespace: {key: value}}
```
Use when: multiple namespaces or partitions that must be isolated.
Access pattern: `self._store.get(ns, {}).get(key, default)`

### List-Based State
```python
self._items = []  # ordered collection
```
Use when: order matters, append/remove semantics.

### Set-Based State
```python
self._members = set()  # unique elements
```
Use when: membership testing, no duplicates.

### Counter/Accumulator
```python
self._counters = {}  # {key: int} with increment semantics
```
Use when: additive updates, running totals.

## Common Operation Semantics

### Put/Create/Update
- **Overwrite**: `store[key] = value` (last write wins)
- **Conditional**: only set if key absent or value meets condition
- **Increment**: `store[key] = store.get(key, 0) + delta`

### Fetch/Get/Read
- **Default on miss**: return 0, "", False, or empty collection
- **Error on miss**: raise exception or return error status
- **Aggregate reads**: sum, count, min, max over a collection

### Delete/Remove
- **Return removed value**: pop and return
- **Return success flag**: bool + optional value
- **Cascade delete**: remove related entries

### List/Scan
- **Full list**: return all keys or values
- **Filtered list**: return entries matching criteria
- **Aggregate**: sum, count, average over entries

## Thread Safety

For concurrent access, wrap all state mutations and reads in a lock:
```python
import threading

class Server:
    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()

    def Put(self, request, context):
        with self._lock:
            self._store[request.key] = request.value
            return Response(value=request.value)
```

**When to use locks**: Any time the server might handle concurrent requests
(multiple clients, burst traffic, long-running test windows).

**When locks may be unnecessary**: Single-client, sequential request patterns
(but adding them is always safe and costs little).

## Server Lifecycle Patterns

### Basic (v01-style)
```python
server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
add_Servicer_to_server(Server(), server)
server.add_insecure_port('[::]:PORT')
server.start()
server.wait_for_termination()
```

### With Health Check
```python
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
health_servicer = health.HealthServicer()
health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
health_servicer.set_status("", health_pb2.HealthCheckResponse.SERVING)
```

### Graceful Shutdown
```python
server.start()
# ... handle SIGTERM/SIGINT ...
server.stop(grace=5)  # 5 second grace period
```

## Default Value Patterns

Proto3 defaults align with common "missing" semantics:
- `int32` → 0 (natural default for counters, missing values)
- `string` → "" (natural default for missing text)
- `bool` → False (natural default for "not found", "not successful")
- `repeated` → [] (natural default for empty collections)

When the task says "return 0 for missing", proto3 defaults handle this automatically
if you construct the response without explicitly setting the field.
