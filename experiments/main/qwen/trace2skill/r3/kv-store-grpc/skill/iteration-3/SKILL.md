---
name: kv-store-grpc
description: General starting point for solving tasks in the kv-store-grpc family.
---

# kv-store-grpc

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Implementation Workflow

1. **Proto Definition & Generation**: Define the gRPC service and messages in a `.proto` file. Generate Python bindings:
   ```bash
   python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <filename>.proto
   ```
   *Note: Hyphenated filenames (e.g., `kv-store.proto`) map to underscored modules (`kv_store_pb2.py`); protoc handles import conversion automatically.*

2. **Servicer & State Management**: Implement the servicer using a thread-safe nested dictionary for isolated namespaced state:
   ```python
   import threading
   from collections import defaultdict

   class KVStoreServicer:
       def __init__(self):
           self.store = defaultdict(dict)
           self.lock = threading.Lock()
   ```
   Use explicit checks or `.get()` chains to avoid `KeyError` and return protocol-defined defaults.

3. **Server Lifecycle & Verification**: 
   - Wrap the server lifecycle to initialize `grpc.server(futures.ThreadPoolExecutor(...))`, bind to the port, and call `server.start()` followed by `server.wait_for_termination()`.
   - Launch in the background (`python server.py &`).
   - Verify liveness and stateful behavior using an inline Python client probe to test RPCs and edge cases, especially in minimal containers lacking `ps` or `netstat`.
