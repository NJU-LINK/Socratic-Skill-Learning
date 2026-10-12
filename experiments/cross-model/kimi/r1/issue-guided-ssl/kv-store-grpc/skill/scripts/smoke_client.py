#!/usr/bin/env python3
"""
Complete working smoke test client for KV Store gRPC services.
This is the v01 reference implementation.
"""
import sys
from concurrent.futures import ThreadPoolExecutor
import grpc
import kv_store_pb2 as pb
import kv_store_pb2_grpc as pbg


def run_smoke_test(host="localhost", port=5328, timeout=10):
    """Run comprehensive smoke tests against the server."""
    
    # Connect with readiness check
    channel = grpc.insecure_channel(f"{host}:{port}")
    try:
        grpc.channel_ready_future(channel).result(timeout=timeout)
        print(f"✓ Server ready at {host}:{port}")
    except grpc.FutureTimeoutError:
        print(f"✗ Server not ready after {timeout}s")
        return False
    
    stub = pbg.KVStoreStub(channel)
    
    # Test 1: Put operation
    put_resp = stub.Put(pb.PutRequest(namespace="test", key="foo", value=42))
    assert put_resp.value == 42, f"Put returned {put_resp.value}, expected 42"
    print("✓ Put operation")
    
    # Test 2: Fetch existing key
    fetch_resp = stub.Fetch(pb.FetchRequest(namespace="test", key="foo"))
    assert fetch_resp.value == 42, f"Fetch returned {fetch_resp.value}, expected 42"
    print("✓ Fetch existing key")
    
    # Test 3: Cross-channel persistence
    channel2 = grpc.insecure_channel(f"{host}:{port}")
    stub2 = pbg.KVStoreStub(channel2)
    fetch2 = stub2.Fetch(pb.FetchRequest(namespace="test", key="foo"))
    assert fetch2.value == 42, f"Cross-channel fetch returned {fetch2.value}"
    print("✓ Cross-channel persistence")
    
    # Test 4: Fetch missing key returns 0
    missing = stub2.Fetch(pb.FetchRequest(namespace="test", key="nonexistent"))
    assert missing.value == 0, f"Missing key returned {missing.value}, expected 0"
    print("✓ Missing key Fetch returns 0")
    
    # Test 5: Empty/absent namespace total is 0
    empty_total = stub2.ListNamespaceTotal(pb.ListNamespaceTotalRequest(namespace="empty"))
    assert empty_total.total == 0, f"Empty namespace total {empty_total.total}, expected 0"
    print("✓ Empty namespace total is 0")
    
    # Test 6: Delete returns (success=True, value) for existing key
    del_resp = stub2.Delete(pb.DeleteRequest(namespace="test", key="foo"))
    assert del_resp.success is True, f"Delete success={del_resp.success}, expected True"
    assert del_resp.value == 42, f"Delete value={del_resp.value}, expected 42"
    print("✓ Delete existing key")
    
    # Test 7: Delete returns (success=False, 0) for missing key
    del_missing = stub2.Delete(pb.DeleteRequest(namespace="test", key="foo"))
    assert del_missing.success is False, f"Delete success={del_missing.success}, expected False"
    assert del_missing.value == 0, f"Delete value={del_missing.value}, expected 0"
    print("✓ Delete missing key returns (False, 0)")
    
    # Test 8: Namespace isolation
    stub.Put(pb.PutRequest(namespace="ns1", key="k", value=10))
    stub.Put(pb.PutRequest(namespace="ns2", key="k", value=20))
    ns1_total = stub.ListNamespaceTotal(pb.ListNamespaceTotalRequest(namespace="ns1"))
    ns2_total = stub.ListNamespaceTotal(pb.ListNamespaceTotalRequest(namespace="ns2"))
    assert ns1_total.total == 10, f"ns1 total {ns1_total.total}, expected 10"
    assert ns2_total.total == 20, f"ns2 total {ns2_total.total}, expected 20"
    print("✓ Namespace isolation")
    
    # Test 9: Concurrency burst - thread safety verification
    print("  Running concurrency burst (16 workers × 25 ops each)...")
    workers = 16
    ops_per_worker = 25
    burst_ns = "burst_test"
    
    def burst_worker(worker_id):
        # Each worker creates fresh channel (tests "repeated channel creation")
        ch = grpc.insecure_channel(f"{host}:{port}")
        s = pbg.KVStoreStub(ch)
        for j in range(ops_per_worker):
            s.Put(pb.PutRequest(namespace=burst_ns, key=f"k{worker_id}-{j}", value=1))
        return True
    
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(burst_worker, range(workers)))
    
    # Verify all writes present
    total = stub.ListNamespaceTotal(pb.ListNamespaceTotalRequest(namespace=burst_ns)).total
    expected = workers * ops_per_worker
    assert total == expected, f"Burst lost updates: {total} != {expected}"
    print(f"✓ Concurrency burst test ({expected} ops, distinct keys)")
    
    print("\n✅ All smoke tests passed!")
    return True


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
