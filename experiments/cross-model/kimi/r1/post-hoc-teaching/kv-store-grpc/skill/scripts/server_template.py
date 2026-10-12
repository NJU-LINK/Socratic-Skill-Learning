#!/usr/bin/env python3
"""
Template for implementing a thread-safe gRPC service.

Copy and customize for the specific task:
1. Update imports based on proto file name
2. Choose state management pattern based on task semantics
3. Implement each RPC method with proper locking
4. Set the correct port
"""

import grpc
from concurrent import futures
import threading
import os
import pathlib

# TODO: Update these imports based on your proto file name
# For "my-service.proto", use: import my_service_pb2, my_service_pb2_grpc
import kv_store_pb2
import kv_store_pb2_grpc


class ServicerName(kv_store_pb2_grpc.KVStoreServicer):
    """Thread-safe implementation of the gRPC service.
    
    State Management Patterns (choose based on task):
    
    A. Simple KV (no namespaces):
       self._store = {}  # key -> value
       value = self._store.get(key, DEFAULT)
    
    B. Namespace-isolated:
       self._store = {}  # namespace -> key -> value
       ns = self._store.setdefault(request.namespace, {})
       value = ns.get(request.key, DEFAULT)
    
    C. Multi-collection:
       self._store = {}  # collection -> namespace -> key -> value
    
    D. Conditional operations (check-then-act):
       with self._lock:
           current = self._store.get(key)
           if current is None or current != expected:
               return Response(success=False)
           self._store[key] = new_value
           return Response(success=True)
    
    E. Multi-key operations:
       with self._lock:
           values = [self._store.get(k, DEFAULT) for k in request.keys]
    
    F. Aggregate operations:
       with self._lock:
           total = sum(self._store.get(ns, {}).values())
    
    G. Read-modify-write (Increment/Decrement):
       with self._lock:
           current = self._store.get(key, 0)
           new_value = current + delta
           self._store[key] = new_value
           return Response(value=new_value)
    """
    
    def __init__(self):
        # Initialize state storage and lock
        self._store = {}
        self._lock = threading.Lock()
    
    def MethodName(self, request, context):
        """Handle RPC - thread-safe template.
        
        Pattern for check-then-act (e.g., Delete):
            with self._lock:
                if key not in self._store:
                    return Response(success=False)
                value = self._store.pop(key)  # atomic
                return Response(success=True, value=value)
        
        Pattern for read-modify-write (e.g., Increment):
            with self._lock:
                current = self._store.get(key, 0)
                new_value = current + delta
                self._store[key] = new_value
                return Response(value=new_value)
        
        Pattern for iteration (e.g., Sum, List):
            with self._lock:
                # Safe: iteration under lock
                total = sum(self._store.values())
        """
        with self._lock:
            # All state reads/writes inside the lock
            # Access request fields: request.field_name
            # Return: kv_store_pb2.ResponseType(field=value)
            pass


def serve(port=5328):
    """Start the gRPC server with proper lifecycle."""
    # CRITICAL: Disable SO_REUSEPORT to prevent split-brain
    # Without this, multiple processes can bind the same port silently
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=(('grpc.so_reuseport', 0),),
    )
    
    # Register the servicer
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(ServicerName(), server)
    
    # [::] is dual-stack (serves both IPv4 and IPv6 clients)
    bound = server.add_insecure_port(f'[::]:{port}')
    if bound == 0:
        raise RuntimeError(f"Failed to bind to port {port} (already in use?)")
    
    # Write pidfile AFTER successful bind - this is the REAL server PID
    # Do NOT rely on shell $! which may capture subshell instead of python
    pathlib.Path('/tmp/server.pid').write_text(f'{os.getpid()}\n')
    
    print(f"Server started on port {bound}", flush=True)
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
