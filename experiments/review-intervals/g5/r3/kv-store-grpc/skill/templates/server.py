"""
Reference implementation: Namespaced integer key-value store over gRPC.

This demonstrates the pattern for:
- Thread-safe state management with nested dicts
- Multiple RPC methods with different semantics (put, fetch, delete, aggregate)
- Namespace isolation
- Default value handling for missing keys

Adapt the state structure and RPC implementations to match the task requirements.
"""
import threading
from concurrent import futures

import grpc
import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    """
    State: nested dict {namespace -> {key -> value}}
    
    Semantics:
    - Put: create or overwrite, return written value
    - Fetch: return value or 0 if missing
    - Delete: return removed value with success=True, or (0, False) if missing
    - ListNamespaceTotal: sum all values in namespace, or 0 if empty/missing
    """
    
    def __init__(self):
        # namespace -> key -> value
        self._store = {}
        self._lock = threading.Lock()

    def Put(self, request, context):
        ns = request.namespace
        key = request.key
        value = request.value
        with self._lock:
            if ns not in self._store:
                self._store[ns] = {}
            self._store[ns][key] = value
        return kv_store_pb2.PutResponse(value=value)

    def Fetch(self, request, context):
        ns = request.namespace
        key = request.key
        with self._lock:
            value = self._store.get(ns, {}).get(key, 0)
        return kv_store_pb2.FetchResponse(value=value)

    def Delete(self, request, context):
        ns = request.namespace
        key = request.key
        with self._lock:
            ns_dict = self._store.get(ns, {})
            if key in ns_dict:
                value = ns_dict.pop(key)
                success = True
            else:
                value = 0
                success = False
        return kv_store_pb2.DeleteResponse(success=success, value=value)

    def ListNamespaceTotal(self, request, context):
        ns = request.namespace
        with self._lock:
            total = sum(self._store.get(ns, {}).values())
        return kv_store_pb2.ListNamespaceTotalResponse(total=total)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port('[::]:5328')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
