"""Template gRPC server for kv-store-grpc family.

Copy and adapt this file for each variant:
1. Update import statements to match generated module names
2. Update port in add_insecure_port()
3. Implement all servicer methods from the proto spec
4. Update message field access to match generated types
"""
import grpc
import threading
from concurrent import futures

# UPDATE: Match your generated module names
import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):  # UPDATE: Service class name
    def __init__(self):
        self._lock = threading.Lock()
        self._ns = {}  # namespace -> {key: value}

    def Put(self, request, context):  # UPDATE: Method signatures per proto
        with self._lock:
            if request.namespace not in self._ns:
                self._ns[request.namespace] = {}
            self._ns[request.namespace][request.key] = request.value
            return kv_store_pb2.PutResponse(value=request.value)

    def Fetch(self, request, context):
        with self._lock:
            d = self._ns.get(request.namespace)
            if not d or request.key not in d:
                return kv_store_pb2.FetchResponse(value=0)
            return kv_store_pb2.FetchResponse(value=d[request.key])

    def Delete(self, request, context):
        with self._lock:
            d = self._ns.get(request.namespace)
            if not d or request.key not in d:
                return kv_store_pb2.DeleteResponse(success=False, value=0)
            return kv_store_pb2.DeleteResponse(success=True, value=d.pop(request.key))

    def ListNamespaceTotal(self, request, context):
        with self._lock:
            d = self._ns.get(request.namespace)
            if not d:
                return kv_store_pb2.ListNamespaceTotalResponse(total=0)
            total = sum(d.values())
            return kv_store_pb2.ListNamespaceTotalResponse(total=total)


def serve():
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=(('grpc.so_reuseport', 0),),  # Prevent duplicate binds
    )
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    # With so_reuseport=0, duplicate bind raises RuntimeError (grpcio 1.73+)
    server.add_insecure_port('[::]:5328')  # UPDATE: Port per spec
    server.start()
    print("Server started on port 5328", flush=True)
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
