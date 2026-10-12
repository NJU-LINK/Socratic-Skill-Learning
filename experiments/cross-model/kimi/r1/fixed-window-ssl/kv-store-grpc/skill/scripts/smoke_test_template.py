"""Smoke test template for kv-store-grpc family.

Tests all RPC methods across two separate channels to verify:
- Server accepts connections (readiness probe)
- All RPC methods work correctly
- State persists across channel switches
- Namespace isolation works
- Concurrent requests handled safely

Usage: python3 smoke_test.py

Prerequisites:
- Server must be running (run launch-side port check first)
- Run from /app directory (for generated module imports)

IMPORTANT: This test WRITES to server state. After verification passes,
kill and relaunch the server fresh before grading.
"""
import grpc
from concurrent.futures import ThreadPoolExecutor

# UPDATE: Match your generated module names
import kv_store_pb2
import kv_store_pb2_grpc


# UPDATE: Port from spec
PORT = 5328

# Use improbable namespace names to avoid collision with graded tests
NS1 = "smoke_ns1_a7d3"
NS2 = "smoke_ns2_e9f5"
BURST_NS = "smoke_burst_c4k8"


def run_tests():
    # Channel 1: Initial operations
    print("=== Channel 1: Initial operations ===")
    channel1 = grpc.insecure_channel(f'localhost:{PORT}')
    grpc.channel_ready_future(channel1).result(timeout=10)
    stub1 = kv_store_pb2_grpc.KVStoreStub(channel1)  # UPDATE: Stub class name
    
    # Test Put
    resp = stub1.Put(kv_store_pb2.PutRequest(namespace=NS1, key="a", value=10))
    print(f"Put {NS1}/a=10: returned {resp.value}")
    assert resp.value == 10
    
    resp = stub1.Put(kv_store_pb2.PutRequest(namespace=NS1, key="b", value=20))
    print(f"Put {NS1}/b=20: returned {resp.value}")
    assert resp.value == 20
    
    # Test Fetch
    resp = stub1.Fetch(kv_store_pb2.FetchRequest(namespace=NS1, key="a"))
    print(f"Fetch {NS1}/a: {resp.value}")
    assert resp.value == 10
    
    resp = stub1.Fetch(kv_store_pb2.FetchRequest(namespace=NS1, key="missing"))
    print(f"Fetch {NS1}/missing: {resp.value}")
    assert resp.value == 0  # Default for missing key
    
    # Test ListNamespaceTotal
    resp = stub1.ListNamespaceTotal(kv_store_pb2.ListNamespaceTotalRequest(namespace=NS1))
    print(f"ListNamespaceTotal {NS1}: {resp.total}")
    assert resp.total == 30
    
    resp = stub1.ListNamespaceTotal(kv_store_pb2.ListNamespaceTotalRequest(namespace=NS2))
    print(f"ListNamespaceTotal {NS2}: {resp.total}")
    assert resp.total == 0  # Empty/absent namespace
    
    # Test Delete existing
    resp = stub1.Delete(kv_store_pb2.DeleteRequest(namespace=NS1, key="a"))
    print(f"Delete {NS1}/a (exists): success={resp.success}, value={resp.value}")
    assert resp.success == True
    assert resp.value == 10
    
    # Test Delete missing
    resp = stub1.Delete(kv_store_pb2.DeleteRequest(namespace=NS1, key="a"))
    print(f"Delete {NS1}/a (missing): success={resp.success}, value={resp.value}")
    assert resp.success == False
    assert resp.value == 0
    
    # Close channel 1
    channel1.close()
    print(f"\n=== Channel 1 closed ===")
    
    # Channel 2: Verify state persistence and namespace isolation
    print(f"\n=== Channel 2: State persistence test ===")
    channel2 = grpc.insecure_channel(f'localhost:{PORT}')
    grpc.channel_ready_future(channel2).result(timeout=10)
    stub2 = kv_store_pb2_grpc.KVStoreStub(channel2)
    
    # Verify NS1/b still exists (from channel 1)
    resp = stub2.Fetch(kv_store_pb2.FetchRequest(namespace=NS1, key="b"))
    print(f"Fetch {NS1}/b after channel switch: {resp.value}")
    assert resp.value == 20, f"State must persist! Expected 20, got {resp.value}"
    
    # Verify NS1/a was deleted
    resp = stub2.Fetch(kv_store_pb2.FetchRequest(namespace=NS1, key="a"))
    print(f"Fetch {NS1}/a (deleted): {resp.value}")
    assert resp.value == 0
    
    # Test namespace isolation
    resp = stub2.Put(kv_store_pb2.PutRequest(namespace=NS2, key="a", value=100))
    print(f"Put {NS2}/a=100: returned {resp.value}")
    
    resp = stub2.ListNamespaceTotal(kv_store_pb2.ListNamespaceTotalRequest(namespace=NS1))
    print(f"ListNamespaceTotal {NS1} (should be 20): {resp.total}")
    assert resp.total == 20, "Namespace isolation violated!"
    
    resp = stub2.ListNamespaceTotal(kv_store_pb2.ListNamespaceTotalRequest(namespace=NS2))
    print(f"ListNamespaceTotal {NS2} (should be 100): {resp.total}")
    assert resp.total == 100
    
    # Close channel 2
    channel2.close()
    print(f"\n=== Channel 2 closed ===")
    
    print(f"\n✓ All smoke tests passed!")


def run_burst_test():
    """Concurrent burst test - 200 parallel Puts, verify no lost updates."""
    print(f"\n=== Burst concurrency test ===")
    channel = grpc.insecure_channel(f'localhost:{PORT}')
    grpc.channel_ready_future(channel).result(timeout=10)
    stub = kv_store_pb2_grpc.KVStoreStub(channel)
    
    def put(i):
        return stub.Put(kv_store_pb2.PutRequest(
            namespace=BURST_NS, key=f"k{i}", value=1
        ))
    
    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(put, range(200)))  # 200 concurrent Puts, distinct keys
    
    total = stub.ListNamespaceTotal(
        kv_store_pb2.ListNamespaceTotalRequest(namespace=BURST_NS)
    ).total
    print(f"ListNamespaceTotal {BURST_NS}: {total}")
    assert total == 200, f"Lost updates detected: {total} != 200"
    print("✓ All 200 concurrent writes persisted correctly")
    
    channel.close()


if __name__ == '__main__':
    run_tests()
    run_burst_test()
    print(f"\n" + "="*50)
    print("VERIFICATION COMPLETE")
    print("="*50)
    print("NOW: Kill server and relaunch fresh before grading!")
    print("pkill -f '^python3.*server\\.py'")
    print("cd /app && nohup python3 -u server.py > /app/server.log 2>&1 &")
