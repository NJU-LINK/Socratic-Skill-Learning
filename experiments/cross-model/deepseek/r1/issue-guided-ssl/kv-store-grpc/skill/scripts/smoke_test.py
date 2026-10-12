#!/usr/bin/env python3
"""smoke_test.py — verify every semantic branch of a running kv-store-grpc
server over a FRESH channel (state must persist across channels by design).

Usage:
  python3 smoke_test.py [--port 5328] [--proto-dir /app]

The assertion set is the family's default leaf-operation table (SKILL.md
step 3). For a variant with different semantics, extend the table below
rather than weakening existing checks. Import contract: the client imports
the generated *_pb2 modules, so either run from the codegen directory or
pass --proto-dir (inserted into sys.path).
"""
import argparse
import sys
import time

import grpc

NS_A = "n1"
NS_B = "n2"
KEY = "k"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5328)
    ap.add_argument("--proto-dir", default="/app")
    args = ap.parse_args()

    sys.path.insert(0, args.proto_dir)
    import kv_store_pb2
    import kv_store_pb2_grpc

    ch = grpc.insecure_channel(f"localhost:{args.port}")
    stub = kv_store_pb2_grpc.KVStoreStub(ch)

    # Readiness: channel READY = TCP + HTTP/2 handshake done.
    deadline = time.time() + 15
    while True:
        try:
            grpc.channel_ready_future(ch).result(timeout=2)
            break
        except grpc.FutureTimeoutError:
            assert time.time() < deadline, "server never became ready"

    req = kv_store_pb2
    # missing key -> default 0
    assert stub.Fetch(req.FetchRequest(namespace=NS_A, key=KEY)).value == 0
    # put returns the written value
    assert stub.Put(req.PutRequest(namespace=NS_A, key=KEY, value=7)).value == 7
    # overwrite-on-put
    assert stub.Put(req.PutRequest(namespace=NS_A, key=KEY, value=3)).value == 3
    # namespace isolation
    assert stub.Put(req.PutRequest(namespace=NS_B, key=KEY, value=10)).value == 10
    assert stub.Fetch(req.FetchRequest(namespace=NS_A, key=KEY)).value == 3
    assert stub.Fetch(req.FetchRequest(namespace=NS_B, key=KEY)).value == 10
    # namespace-scoped totals
    assert stub.ListNamespaceTotal(req.ListNamespaceTotalRequest(namespace=NS_A)).total == 3
    assert stub.ListNamespaceTotal(req.ListNamespaceTotalRequest(namespace=NS_B)).total == 10
    # delete present
    d = stub.Delete(req.DeleteRequest(namespace=NS_A, key=KEY))
    assert (d.success, d.value) == (True, 3), (d.success, d.value)
    assert stub.Fetch(req.FetchRequest(namespace=NS_A, key=KEY)).value == 0
    # delete absent
    d = stub.Delete(req.DeleteRequest(namespace=NS_A, key=KEY))
    assert (d.success, d.value) == (False, 0), (d.success, d.value)
    # absent namespace total -> 0
    assert stub.ListNamespaceTotal(req.ListNamespaceTotalRequest(namespace="n3")).total == 0

    print("smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())