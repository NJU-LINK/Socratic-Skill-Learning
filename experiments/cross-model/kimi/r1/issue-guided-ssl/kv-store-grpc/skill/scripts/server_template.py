#!/usr/bin/env python3
"""
Complete working gRPC KV Store server implementation.
This is the v01 reference implementation - copy and modify for other variants.
"""
import threading
from collections import defaultdict
from concurrent import futures
import grpc
import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    """
    Thread-safe namespaced key-value store servicer.
    
    State structure: {namespace: {key: value}}
    All handlers acquire self._lock for thread safety.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._store = defaultdict(dict)  # namespace -> {key: value}
    
    def Put(self, request, context):
        """Create or overwrite a key, return the written value."""
        with self._lock:
            self._store[request.namespace][request.key] = request.value
            return kv_store_pb2.PutResponse(value=request.value)
    
    def Fetch(self, request, context):
        """Return value for key, or 0 if missing."""
        with self._lock:
            v = self._store.get(request.namespace, {}).get(request.key, 0)
            return kv_store_pb2.FetchResponse(value=v)
    
    def Delete(self, request, context):
        """
        Delete key and return (success, value).
        Returns (False, 0) if key missing.
        Returns (True, value) if key existed.
        """
        with self._lock:
            ns = self._store.get(request.namespace)
            if not ns or request.key not in ns:
                return kv_store_pb2.DeleteResponse(success=False, value=0)
            v = ns.pop(request.key)
            return kv_store_pb2.DeleteResponse(success=True, value=v)
    
    def ListNamespaceTotal(self, request, context):
        """Sum all values in namespace, return 0 if absent or empty."""
        with self._lock:
            return kv_store_pb2.ListNamespaceTotalResponse(
                total=sum(self._store.get(request.namespace, {}).values()))


def serve(port=5328):
    """Start the gRPC server on the specified port."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=32))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    bound_port = server.add_insecure_port(f"[::]:{port}")
    if bound_port == 0:
        raise SystemExit(f"Failed to bind to port {port}")
    print(f"Server listening on port {port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
