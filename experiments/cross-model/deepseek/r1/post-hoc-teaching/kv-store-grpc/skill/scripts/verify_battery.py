#!/usr/bin/env python3
"""verify_battery.py — idempotent verification battery for kv-store-grpc.

Why this file exists: hand-written batteries in fresh sessions repeatedly
fail on harmless typos (e.g. a comprehension used as a statement) and —
worse — leave residue that contaminates the NEXT run ("why is the total
1800, not 1600?" is usually YOUR leftover keys, not a server bug).  This
skeleton owns the fiddly machinery correctly:

  * real gRPC handshake first (distinguishes the endpoint from a bare TCP
    listener);
  * import-safety: `import <server>` must not hang, and the servicer class
    must subclass the generated <Service>Servicer (both generic checks);
  * IDEMPOTENCY: cleanup_keys() runs BEFORE the semantic checks AND after
    the burst, so a crashed previous run cannot poison this one and this
    run cannot poison the grader;
  * distinct per-thread burst keys (t{tid}_{i}), so concurrent writes never
    collide;
  * TIER 4: after post-cleanup, final_default_checks() re-verifies the
    store matches the task's initial state (default reads) — the grader's
    first RPCs must see exactly the world the task prose assumes.

You only edit the four marked SLOT functions to match the task's exact
prose; the default content is the v01 semantics and doubles as a worked
example.  Use ONLY the NS prefix / zzt_-style names — never generic
identifiers (test/key/foo/"" collide with graders).

Usage (run in a fresh shell; bindings must be importable):
  cd <outdir> && PYTHONPATH=<outdir> python3 verify_battery.py \
      --port 5328 --out <outdir> --module kv_store --service KVStore \
      --prefix zzt_<task>
"""
import argparse
import importlib
import sys
import threading

import grpc


# ---------------------------------------------------------------------------
# MANDATORY patterns (both presence traps) — include these in EVERY battery:
#
# TRAP 1 (proto3 absence): `optional` scalar -> HasField("f"), oneof ->
#   WhichOneof("g") (member name or None).  Absent != zero on the REQUEST.
#   If any RPC has an optional/oneof field, the battery MUST call it with
#   the field ABSENT and with the field = 0, and assert the two outcomes
#   differ per the task prose.  Example (Update semantics: set only when
#   present):
#     stub.Update(pb2.UpdateRequest(key=k))            # absent -> unchanged
#     stub.Update(pb2.UpdateRequest(key=k, new_value=0))  # present 0 -> sets
#
# TRAP 2 (stored zero vs missing): if 0 is a legal stored value, presence
#   reads must use membership, not the value.  The one test that separates
#   the two readings: Put(k, 0), then run every conditional/presence RPC on
#   k and assert the outcome that requires "key exists".  Example:
#     stub.Put(pb2.PutRequest(key=k, value=0))
#     assert stub.SetIfAbsent(...key=k...).success is False   # exists!
# ---------------------------------------------------------------------------
# SLOT 1: task semantics as asserts.  Any WRITE must be undone in
# cleanup_keys() (tier 4).  Edge branches first, then happy paths.
# ---------------------------------------------------------------------------
def semantic_checks(stub, pb2, NS, a):
    # v01 defaults — replace with the task's exact prose:
    assert stub.Fetch(pb2.FetchRequest(namespace=NS, key="x")).value == 0       # missing -> 0
    d = stub.Delete(pb2.DeleteRequest(namespace=NS, key="x"))                    # delete-missing
    assert d.success is False and d.value == 0
    assert stub.ListNamespaceTotal(pb2.ListNamespaceTotalRequest(namespace=NS)).total == 0
    assert stub.Put(pb2.PutRequest(namespace=NS, key="a", value=5)).value == 5   # put returns value
    assert stub.Put(pb2.PutRequest(namespace=NS, key="a", value=7)).value == 7   # overwrite
    assert stub.Fetch(pb2.FetchRequest(namespace=NS, key="a")).value == 7
    assert stub.ListNamespaceTotal(pb2.ListNamespaceTotalRequest(namespace=NS)).total == 7
    d = stub.Delete(pb2.DeleteRequest(namespace=NS, key="a"))
    assert d.success is True and d.value == 7                                    # delete returns value
    assert stub.Fetch(pb2.FetchRequest(namespace=NS, key="a")).value == 0
    # namespace isolation (namespaced variants only): a value in _other must
    # not leak into NS reads/aggregates
    stub.Put(pb2.PutRequest(namespace=NS + "_other", key="z", value=999))
    assert stub.Fetch(pb2.FetchRequest(namespace=NS, key="a")).value == 0
    assert stub.ListNamespaceTotal(pb2.ListNamespaceTotalRequest(namespace=NS)).total == 0
    print("semantic checks OK")


# ---------------------------------------------------------------------------
# SLOT 2: delete EVERY key written by slots 1 and 3.  Also runs BEFORE the
# run (idempotency) — deleting a missing key is a no-op whose result is
# defined by the task's Delete-missing contract, so a correct server can
# never fail on this.  Edit the key sets/ranges to match your slots.
# ---------------------------------------------------------------------------
def cleanup_keys(stub, pb2, NS, a):
    stub.Delete(pb2.DeleteRequest(namespace=NS, key="x"))
    stub.Delete(pb2.DeleteRequest(namespace=NS, key="a"))
    stub.Delete(pb2.DeleteRequest(namespace=NS + "_other", key="z"))
    for tid in range(a.burst_threads):
        for i in range(a.burst_puts):
            stub.Delete(pb2.DeleteRequest(namespace=NS, key=f"b{tid}_{i}"))


# ---------------------------------------------------------------------------
# SLOT 3: burst worker.  thread_id MUST be part of every key (distinct keys
# per thread) so concurrent puts never overwrite each other.  Values/keys
# are cleaned by cleanup_keys().  The aggregate assertion (if the task has
# one) belongs in semantic_checks or here after the threads join.
# ---------------------------------------------------------------------------
def burst_worker(stub_factory, pb2, NS, tid, per_thread):
    stub = stub_factory()
    for i in range(per_thread):
        stub.Put(pb2.PutRequest(namespace=NS, key=f"b{tid}_{i}", value=1))


# ---------------------------------------------------------------------------
# SLOT 4: TIER 4 — after post-cleanup, the store must be back in its initial
# state.  Re-verify the task's documented defaults (missing fetch -> default,
# empty aggregate -> 0) as the LAST assertions.
# ---------------------------------------------------------------------------
def final_default_checks(stub, pb2, NS, a):
    assert stub.Fetch(pb2.FetchRequest(namespace=NS, key="a")).value == 0
    assert stub.ListNamespaceTotal(pb2.ListNamespaceTotalRequest(namespace=NS)).total == 0
    assert stub.ListNamespaceTotal(pb2.ListNamespaceTotalRequest(namespace=NS + "_other")).total == 0
    print("tier-4 clean (store matches initial state)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=5328)
    ap.add_argument("--out", default="/app", help="dir holding the generated bindings")
    ap.add_argument("--module", default="kv_store", help="proto basename with - -> _ (module prefix)")
    ap.add_argument("--service", default="KVStore", help="service name as declared in the proto")
    ap.add_argument("--server", default="server", help="server module to import-safety check")
    ap.add_argument("--servicer", default="Server", help="servicer class name in that module")
    ap.add_argument("--prefix", default="zzt_task_probe", help="collision-proof namespace/key prefix")
    ap.add_argument("--burst-threads", type=int, default=8)
    ap.add_argument("--burst-puts", type=int, default=100)
    ap.add_argument("--wait", type=int, default=30)
    a = ap.parse_args()

    sys.path.insert(0, a.out)
    pb2 = importlib.import_module(a.module + "_pb2")
    grpc_mod = importlib.import_module(a.module + "_pb2_grpc")
    NS = a.prefix

    # 0. real gRPC handshake (a raw TCP connect proves only that SOMEONE listens)
    ch = grpc.insecure_channel(f"127.0.0.1:{a.port}")
    grpc.channel_ready_future(ch).result(timeout=a.wait)
    print(f"handshake OK on {a.port}")
    stub = getattr(grpc_mod, a.service + "Stub")(ch)

    # 1. import-safety: module import + servicer class contract
    server_mod = importlib.import_module(a.server)
    cls = getattr(server_mod, a.servicer)
    assert issubclass(cls, getattr(grpc_mod, a.service + "Servicer")), \
        f"{a.servicer} must subclass {a.service}Servicer"
    cls()  # must be instantiable without hanging
    print("import-safety OK")

    # 2. pre-clean (idempotency: a crashed prior run must not poison this one)
    cleanup_keys(stub, pb2, NS, a)

    # 3. semantic checks (task prose as asserts)
    semantic_checks(stub, pb2, NS, a)

    # 4. concurrency burst: fresh channel per thread, distinct keys per thread
    def worker(tid):
        c = grpc.insecure_channel(f"127.0.0.1:{a.port}")
        burst_worker(lambda: getattr(grpc_mod, a.service + "Stub")(c),
                     pb2, NS, tid, a.burst_puts)
        c.close()

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(a.burst_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"burst OK: {a.burst_threads} threads x {a.burst_puts} distinct-key writes")

    # 5. post-clean + tier 4
    cleanup_keys(stub, pb2, NS, a)
    final_default_checks(stub, pb2, NS, a)
    print("ALL BATTERY CHECKS PASSED")


if __name__ == "__main__":
    main()