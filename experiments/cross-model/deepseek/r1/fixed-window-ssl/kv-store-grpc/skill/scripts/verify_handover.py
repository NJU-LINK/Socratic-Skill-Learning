#!/usr/bin/env python3
"""Final NON-MUTATING handover verification for a gRPC task server.

Runs after smoke (and optionally burst) when handover state already exists:
  (1) exactly ONE server interpreter running the server script
      (scan /proc cmdlines — $! wrapper pids are not the interpreter)
  (2) connect oracle: BOTH ::1 and 127.0.0.1 accept on the port
  (3) optional: ListNamespaceTotal == 0 for every namespace named on argv
      (a read-only emptiness check through the generated stubs)
Kills/relaunches/rebinds nothing. Exits nonzero on any failure.

Adapt: SERVER_SCRIPT basename, PORT, message/RPC names for the emptiness
check (pass 0 namespaces to skip it). Usage:
  python3 verify_handover.py [namespace ...]
"""
import os
import socket
import sys

import grpc

import kv_store_pb2
import kv_store_pb2_grpc

SERVER_BASENAME = "server.py"
PORT = 5328
HOSTS = ("::1", "127.0.0.1")


def server_pids():
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            args = open(f"/proc/{entry}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        args = [a.decode(errors="replace") for a in args if a]
        if not args:
            continue
        if os.path.basename(args[0]) in ("python3", "python") and any(
            a.endswith(SERVER_BASENAME) for a in args[1:]
        ):
            out.append(int(entry))
    return out


def connect_ok(host, port, timeout=2.0):
    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    ok = True

    pids = server_pids()
    good = len(pids) == 1
    ok = ok and good
    print(f"{'PASS' if good else 'FAIL'}  exactly one server interpreter: {pids}")

    for host in HOSTS:
        good = connect_ok(host, PORT)
        ok = ok and good
        print(f"{'PASS' if good else 'FAIL'}  {host}:{PORT} accepts")

    if len(sys.argv) > 1:
        ch = grpc.insecure_channel(f"localhost:{PORT}")
        stub = kv_store_pb2_grpc.KVStoreStub(ch)
        for ns in sys.argv[1:]:
            t = stub.ListNamespaceTotal(
                kv_store_pb2.ListNamespaceTotalRequest(namespace=ns)).total
            good = t == 0
            ok = ok and good
            print(f"{'PASS' if good else 'FAIL'}  namespace {ns!r} empty (total={t})")
        ch.close()

    print("HANDOVER:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())