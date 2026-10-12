---
name: kv-store-grpc
description: General starting point for solving tasks in the kv-store-grpc family.
---

# kv-store-grpc

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Implementation Patterns

### Proto Definition and gRPC Bindings
- Define the `.proto` file with exact message fields, types, and field numbers as specified.
- Generate Python bindings: `python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <file>.proto`
- Remember that hyphens in `.proto` filenames become underscores in generated `_pb2.py` files.
- `grep` the generated `_grpc.py` for `class.*Servicer` to confirm the exact base class name before implementing the server.

### Thread-Safe Namespaced State Management
- Implement in-memory namespaced key-value state using `collections.defaultdict(dict)` protected by a `threading.Lock` to safely handle concurrent unary RPC calls:
```python
import collections
import threading

class MyServicer(pb2_grpc.MyServiceServicer):
    def __init__(self):
        self._lock = threading.Lock()
        self._namespaces = collections.defaultdict(dict)

    def Put(self, request, context):
        with self._lock:
            self._namespaces[request.namespace][request.key] = request.value
```
- Handle missing keys/namespaces gracefully on reads (e.g., `.get(namespace, {}).get(key, default)`). Return default values for missing keys on Fetch, and structured success/failure responses on Delete.
- Aggregate safely: `sum(store.get(namespace, {}).values())` returns `0` for empty/absent namespaces.

### Server Launch and Verification
- Start the server in the background: `python server.py > /tmp/server.log 2>&1 &` and sleep briefly to allow startup.
- Verify server readiness by executing an inline Python script that creates a gRPC channel and performs a basic round-trip RPC call, or use a socket connection check:
```bash
python -c "import socket; s = socket.socket(); result = s.connect_ex(('localhost', PORT)); s.close(); print('Open' if result == 0 else 'Closed')"
```
- Avoid `ps` or `netstat`, which may be missing in minimal containers.
