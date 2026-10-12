# Server Implementation Patterns

## Basic Server Skeleton

```python
import grpc
from concurrent import futures
import <module>_pb2
import <module>_pb2_grpc

class Server(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize state here
        pass

    def <RpcMethod>(self, request, context):
        # Process request, return response
        return <module>_pb2.<ResponseMessage>(field=value)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

## State Management Patterns

### Pattern 1: Flat Dictionary (Simple Key-Value)
```python
class Server(Servicer):
    def __init__(self):
        self.store = {}  # {key: value}

    def Get(self, request, context):
        return Response(value=self.store.get(request.key, 0))

    def Set(self, request, context):
        self.store[request.key] = request.value
        return Response(value=request.value)
```

### Pattern 2: Namespace-Isolated Dictionary
```python
class Server(Servicer):
    def __init__(self):
        self.store = {}  # {namespace: {key: value}}

    def _ns(self, namespace):
        """Get or create namespace dict."""
        return self.store.setdefault(namespace, {})

    def Put(self, request, context):
        self._ns(request.namespace)[request.key] = request.value
        return Response(value=request.value)

    def Fetch(self, request, context):
        ns = self.store.get(request.namespace, {})
        return Response(value=ns.get(request.key, 0))

    def Delete(self, request, context):
        ns = self.store.get(request.namespace, {})
        if request.key in ns:
            val = ns.pop(request.key)
            return DeleteResponse(success=True, value=val)
        return DeleteResponse(success=False, value=0)

    def Total(self, request, context):
        ns = self.store.get(request.namespace, {})
        return TotalResponse(total=sum(ns.values()))
```

### Pattern 3: Composite Key (Flat but Namespaced)
```python
class Server(Servicer):
    def __init__(self):
        self.store = {}  # {(namespace, key): value}

    def Put(self, request, context):
        self.store[(request.namespace, request.key)] = request.value
        return Response(value=request.value)

    def Fetch(self, request, context):
        return Response(value=self.store.get((request.namespace, request.key), 0))
```

### Pattern 4: Multi-Collection State
```python
class Server(Servicer):
    def __init__(self):
        self.users = {}       # {id: User}
        self.sessions = {}    # {token: user_id}
        self.counters = {}    # {name: count}

    def Register(self, request, context):
        self.users[request.id] = request.name
        return Response(success=True)

    def IncrementCounter(self, request, context):
        self.counters[request.name] = self.counters.get(request.name, 0) + 1
        return Response(count=self.counters[request.name])
```

### Pattern 5: Conditional Updates
```python
class Server(Servicer):
    def __init__(self):
        self.store = {}

    def CompareAndSet(self, request, context):
        current = self.store.get(request.key)
        if current == request.expected:
            self.store[request.key] = request.new_value
            return Response(success=True, value=request.new_value)
        return Response(success=False, value=current if current is not None else 0)
```

## Thread Safety

Python's GIL provides basic thread safety for dict operations. For complex multi-step operations that must be atomic, use a lock:

```python
import threading

class Server(Servicer):
    def __init__(self):
        self.store = {}
        self.lock = threading.Lock()

    def AtomicUpdate(self, request, context):
        with self.lock:
            current = self.store.get(request.key, 0)
            new_val = current + request.delta
            self.store[request.key] = new_val
            return Response(value=new_val)
```

## Server Lifecycle

### Basic Launch (Background)
```bash
cd /app && python server.py &
sleep 2
```

### Launch with PID Tracking
```bash
cd /app && python server.py &
echo $! > /tmp/server.pid
sleep 2
```

### Readiness Verification
```python
import grpc
import time

def wait_for_server(port, timeout=10):
    """Block until server is ready or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            channel = grpc.insecure_channel(f'localhost:{port}')
            grpc.channel_ready_future(channel).result(timeout=1)
            return True
        except grpc.FutureTimeoutError:
            continue
    return False
```

### Graceful Shutdown
```python
import signal
import sys

server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
# ... setup ...
server.start()

def shutdown(signum, frame):
    server.stop(grace=5)  # 5 second grace period
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
server.wait_for_termination()
```

## Multiple Services on One Server

```python
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    # Add multiple servicers
    module_pb2_grpc.add_ServiceAServicer_to_server(ServiceAImpl(), server)
    module_pb2_grpc.add_ServiceBServicer_to_server(ServiceBImpl(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    server.wait_for_termination()
```

## Client-Side Patterns

### Basic Client
```python
channel = grpc.insecure_channel('localhost:5328')
stub = module_pb2_grpc.ServiceStub(channel)
response = stub.Method(module_pb2.Request(field=value))
```

### Repeated Channel Creation
```python
# Each call creates a new channel — tests state persistence across channels
for i in range(10):
    channel = grpc.insecure_channel('localhost:5328')
    stub = module_pb2_grpc.ServiceStub(channel)
    response = stub.Method(module_pb2.Request(field=i))
    channel.close()
```

### Concurrent Client Calls
```python
import concurrent.futures

def call_rpc(value):
    channel = grpc.insecure_channel('localhost:5328')
    stub = module_pb2_grpc.ServiceStub(channel)
    return stub.Method(module_pb2.Request(field=value))

with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(call_rpc, i) for i in range(100)]
    results = [f.result() for f in futures]
```
