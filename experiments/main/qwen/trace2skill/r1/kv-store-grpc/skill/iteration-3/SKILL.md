---
name: kv-store-grpc
description: General starting point for solving tasks in the kv-store-grpc family.
---

# kv-store-grpc

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Implementation Patterns

### 1. Proto Definition & Generation
- Define the `.proto` file matching exact service, RPC, message, and field names, types, and numbers from the task.
- Generate Python stubs: `python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <file>.proto`

### 2. Service Implementation & State Management
- Implement a Servicer class inheriting from the generated `<Service>Servicer`.
- Store namespaced state using `collections.defaultdict(dict)` (outer keys = namespaces, inner = key-value pairs).
- Handle CRUD and aggregate edge cases exactly:
  - **Put**: `self.namespaces[ns][key] = value`
  - **Fetch**: `self.namespaces.get(ns, {}).get(key, 0)` (return `0` for missing keys).
  - **Delete**: Check membership and use `.pop()`. Return `success=False, value=0` for missing keys.
  - **Aggregates (e.g., ListNamespaceTotal)**: `sum(self.namespaces.get(ns, {}).values())` (return `0` if empty/missing).
- Wrap server initialization in a `Server` class that initializes `grpc.server(futures.ThreadPoolExecutor(...))`, registers the servicer via `add_<Service>Servicer_to_server`, binds the port with `add_insecure_port('[::]:<port>')`, and exposes `start()`, `stop()`, and `wait_for_termination()`.

### 3. Background Launch & Verification
- Start the server detached in the background: `nohup python server.py > /tmp/server.log 2>&1 &` and sleep briefly.
- **Do not rely on `ps` or `pgrep`** as they may be missing in minimal containers.
- Verify readiness and correctness by executing an inline Python client script (`python -c "..."`) that creates a `grpc.insecure_channel`, instantiates the Stub, and performs smoke-test RPC calls covering all edge cases (missing keys, namespace isolation, overwrites, sums). Assert or print results to confirm before finishing.
