"""Template: stateful gRPC servicer skeleton (verified mechanism on v01).

Adapt for the variant:
  * module names: {MODULE}_pb2 / {MODULE}_pb2_grpc (from the proto FILENAME)
  * servicer base class: {MODULE}_pb2_grpc.{SERVICE}Servicer
  * one method per RPC, named exactly as the RPC, with the spec's semantics
  * port from the task; bind "[::]:<port>" (dual-stack on Linux)
Non-negotiables:
  * one threading.Lock around ALL state access (mutations AND aggregate
    reads) — unlocked sum() can raise "dictionary changed size during
    iteration" under concurrent writes
  * assert the add_insecure_port result: it returns 0 on bind failure
    instead of raising
  * `if __name__ == "__main__":` guard so graders/clients can import
"""
import threading
from concurrent import futures

import grpc

import kv_store_pb2
import kv_store_pb2_grpc

PORT = 5328


class Server(kv_store_pb2_grpc.KVStoreServicer):
    """In-memory, namespace-isolated integer store; state persists across
    calls and client channels for the process lifetime."""

    def __init__(self):
        self._store = {}          # namespace -> {key: value}
        self._lock = threading.Lock()

    def Put(self, request, context):
        with self._lock:
            self._store.setdefault(request.namespace, {})[request.key] = request.value
        return kv_store_pb2.PutResponse(value=request.value)

    def Fetch(self, request, context):
        with self._lock:
            ns = self._store.get(request.namespace)
            value = ns.get(request.key, 0) if ns is not None else 0
        return kv_store_pb2.FetchResponse(value=value)

    def Delete(self, request, context):
        with self._lock:
            ns = self._store.get(request.namespace)
            if ns is not None and request.key in ns:
                value = ns.pop(request.key)
                response = kv_store_pb2.DeleteResponse(success=True, value=value)
            else:
                response = kv_store_pb2.DeleteResponse(success=False, value=0)
        return response

    def ListNamespaceTotal(self, request, context):
        with self._lock:
            ns = self._store.get(request.namespace)
            total = sum(ns.values()) if ns is not None else 0
        return kv_store_pb2.ListNamespaceTotalResponse(total=total)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    port = server.add_insecure_port(f"[::]:{PORT}")   # returns 0 on failure!
    assert port, f"failed to bind [::]:{PORT} (stale server?)"
    server.start()
    print(f"server listening on [::]:{PORT}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()