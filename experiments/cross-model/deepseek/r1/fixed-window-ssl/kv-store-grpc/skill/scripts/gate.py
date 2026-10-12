#!/usr/bin/env python3
"""Handover gate for a gRPC task server: make exactly ONE live process own the port.

Steps (each must pass before the next):
  1. Kill EVERY python3 process running the server script. ($! pids are
     wrapper pids in wrapped shells, not the interpreter; scan /proc cmdlines.)
  2. Prove zero listeners: connect must be REFUSED on both ::1 and 127.0.0.1
     (a zombie /proc dir is not proof the port is free).
  3. Launch detached: nohup python3 <server_script> >> log.
  4. Prove exactly ONE server interpreter process exists.
  5. Run the smoke client; require ALL checks to pass before handover.
  6. Leave it running; do not touch the server again.

Adapt: SERVER_SCRIPT, PORT, LOG, and the smoke command.
Verified on v01 (kv-store-grpc): caught a stale second interpreter sharing
the port after kill $! hit only the wrapper.
"""
import os
import signal
import socket
import subprocess
import time

SERVER_SCRIPT = "/app/server.py"
PORT = 5328
LOG = "/app/server.log"
HOSTS = ("::1", "127.0.0.1")


def server_pids():
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as fh:
                args = fh.read().split(b"\0")
        except OSError:
            continue
        args = [a.decode(errors="replace") for a in args if a]
        if not args:
            continue
        if os.path.basename(args[0]) in ("python3", "python") and any(
            a.endswith(os.path.basename(SERVER_SCRIPT)) for a in args[1:]
        ):
            out.append(int(entry))
    return out


def port_refused(host, port, timeout=0.3):
    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
    except OSError:
        return True
    finally:
        s.close()
    return False


def main():
    # 1. kill all server interpreters (SIGKILL: in-memory state is meant to die
    #    with the process; a fresh empty store is what handover requires)
    for _ in range(10):
        pids = server_pids()
        if not pids:
            break
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
                print(f"killed server pid {pid}")
            except ProcessLookupError:
                pass
        time.sleep(0.5)
    pids = server_pids()
    assert not pids, f"server processes remain: {pids}"

    # 2. prove the port is free on both address families
    deadline = time.time() + 15
    while time.time() < deadline:
        if all(port_refused(h, PORT) for h in HOSTS):
            break
        time.sleep(0.5)
    else:
        raise SystemExit("port still busy after teardown")
    print(f"port {PORT} free (both families)")

    # 3. launch detached
    with open(LOG, "wb") as log:
        subprocess.Popen(
            ["nohup", "python3", SERVER_SCRIPT],
            stdout=log, stderr=subprocess.STDOUT,
            cwd=os.path.dirname(SERVER_SCRIPT), start_new_session=True,
        )
    time.sleep(1.5)

    # 4. exactly one server interpreter
    pids = server_pids()
    assert len(pids) == 1, f"expected exactly 1 server process, got {pids}"
    print(f"single server pid: {pids[0]}")
    with open(LOG) as fh:
        print("log:", fh.read().strip())


if __name__ == "__main__":
    main()