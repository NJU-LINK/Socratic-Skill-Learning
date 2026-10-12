#!/usr/bin/env python3
"""Self-cleaning concurrency burst probe for a gRPC key-value store.

Warranty, stated honestly: this probe's core guarantee is DETERMINISM — the
exact final total (computed client-side by replaying each worker's op
sequence, never hard-coded) and the clean-zero assertion after self-clean.
A broken server fails these. [direct: 20x40 runs on v01, no exceptions]

What this probe is NOT: at v01 scale (hundreds of keys) it is not a reliable
race detector. `RuntimeError: dictionary changed size during iteration`
fires only when a concurrent thread changes the dict's SIZE (insert/delete,
not value overwrite) between iterator next() calls, and `sum(ns.values())`
is a tight C-level loop that holds the GIL (~5ms thread-switch interval vs
microsecond sums over ~100 keys). An unlocked server at this scale would
almost always pass anyway. The worker loop still inserts AND deletes keys
(size churn) for the whole run — not just ramp-up — so the race window
exists, but the detector only becomes decisive at scale.

Race-detector levers for variants with larger key spaces (per the
stateful_service_semantics axis): raise KEYS_PER_WORKER x WORKERS so a
namespace holds 10^4-10^5 keys (each sum spans multiple GIL windows), keep
churn on, and only then interpret a failure as proof the lock is missing.

Two invariants the probe enforces about ITSELF:
  * churn is real, not a no-op: each churn deletes the PREVIOUS churn's
    fresh key (guaranteed to exist at delete time), so the dict size
    oscillates by construction; the probe counts Delete responses with
    success=True and asserts it equals the expected churn cycles — a silent
    no-op churn fails loudly.
  * replay accounting is exact only while workers own DISJOINT key prefixes
    (overwrite order is otherwise unmirrorable); keep per-worker prefixes.

Adapt for a variant: message classes/RPC names, PORT, and the total/fetch
response attribute names. Usage: python3 burst.py (run from the directory
containing the generated modules).
"""
import concurrent.futures as cf
import sys

import grpc

import kv_store_pb2
import kv_store_pb2_grpc

PORT = "localhost:5328"
NS = "burst_shared"
WORKERS = 20
OPS_PER_WORKER = 40
KEYS_PER_WORKER = 7
CHURN_EVERY = 5   # every Nth op (from N onward): delete prev fresh, insert new


def worker(wid):
    """Replay the op sequence in a thread-local dict so the expected final
    total stays exact even with deletes+inserts (size churn). Returns
    (local_dict, churn_delete_successes)."""
    local = {}
    churn_successes = 0
    ch = grpc.insecure_channel(PORT)
    stub = kv_store_pb2_grpc.KVStoreStub(ch)
    for i in range(OPS_PER_WORKER):
        k = f"w{wid}-k{i % KEYS_PER_WORKER}"
        stub.Put(kv_store_pb2.PutRequest(namespace=NS, key=k, value=i))
        local[k] = i
        if i == 0:
            # seed the churn chain: n0 must exist before the first churn
            # deletes it (a victim that was never Put silently no-ops).
            stub.Put(kv_store_pb2.PutRequest(
                namespace=NS, key=f"w{wid}-n0", value=0))
            local[f"w{wid}-n0"] = 0
        elif i % CHURN_EVERY == 0:
            # victim is the PREVIOUS churn's fresh key: provably exists, so
            # this Delete MUST return success=True (missing-key delete would
            # prove the churn is a silent no-op).
            victim = f"w{wid}-n{i - CHURN_EVERY}"
            resp = stub.Delete(kv_store_pb2.DeleteRequest(namespace=NS, key=victim))
            churn_successes += 1 if resp.success else 0
            local.pop(victim, None)
            fresh = f"w{wid}-n{i}"
            stub.Put(kv_store_pb2.PutRequest(namespace=NS, key=fresh, value=i))
            local[fresh] = i
        if i % 3 == 0:   # aggregate + point reads interleaved with mutations
            stub.ListNamespaceTotal(
                kv_store_pb2.ListNamespaceTotalRequest(namespace=NS))
            stub.Fetch(kv_store_pb2.FetchRequest(namespace=NS, key=k))
    ch.close()
    return local, churn_successes


def main():
    errors = []
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        locals_ = list(ex.map(worker, range(WORKERS)))  # worker exceptions propagate

    expected = sum(v for local, _ in locals_ for v in local.values())
    expected_churn = WORKERS * len(range(CHURN_EVERY, OPS_PER_WORKER, CHURN_EVERY))
    total_successes = sum(s for _, s in locals_)
    print(f"churn deletes with success=True: {total_successes} (expected {expected_churn})")
    if total_successes != expected_churn:
        errors.append(f"churn no-op suspected: {total_successes} != {expected_churn}")

    ch = grpc.insecure_channel(PORT)
    stub = kv_store_pb2_grpc.KVStoreStub(ch)
    t = stub.ListNamespaceTotal(
        kv_store_pb2.ListNamespaceTotalRequest(namespace=NS))
    print(f"final burst total: {t.total} (expected {expected})")
    if t.total != expected:
        errors.append(f"total mismatch: {t.total} != {expected}")

    # self-clean: delete every key this probe ever wrote, assert empty
    for local, _ in locals_:
        for k in local:
            stub.Delete(kv_store_pb2.DeleteRequest(namespace=NS, key=k))
    t = stub.ListNamespaceTotal(
        kv_store_pb2.ListNamespaceTotalRequest(namespace=NS))
    print(f"post-clean total: {t.total}")
    if t.total != 0:
        errors.append(f"cleanup failed: total {t.total} != 0")
    ch.close()

    print("burst result:", "FAIL" if errors else "PASS")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())