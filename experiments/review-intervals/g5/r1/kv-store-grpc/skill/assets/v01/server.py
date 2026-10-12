import grpc
import threading
from concurrent import futures
import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self):
        # Namespaced store: {namespace: {key: value}}
        self.store = {}
        # Thread safety for concurrent requests
        self.lock = threading.Lock()

    def Put(self, request, context):
        ns = request.namespace
        key = request.key
        value = request.value
        with self.lock:
            if ns not in self.store:
                self.store[ns] = {}
            self.store[ns][key] = value
        return kv_store_pb2.PutResponse(value=value)

    def Fetch(self, request, context):
        ns = request.namespace
        key = request.key
        with self.lock:
            value = self.store.get(ns, {}).get(key, 0)
        return kv_store_pb2.FetchResponse(value=value)

    def Delete(self, request, context):
        ns = request.namespace
        key = request.key
        with self.lock:
            if ns in self.store and key in self.store[ns]:
                value = self.store[ns].pop(key)
                return kv_store_pb2.DeleteResponse(success=True, value=value)
            else:
                return kv_store_pb2.DeleteResponse(success=False, value=0)

    def ListNamespaceTotal(self, request, context):
        ns = request.namespace
        with self.lock:
            total = sum(self.store.get(ns, {}).values())
        return kv_store_pb2.ListNamespaceTotalResponse(total=total)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port('[::]:5328')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
