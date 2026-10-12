#!/usr/bin/env python3
"""
verify_with_sqlite.py -- hypothesis-test a recovery against the SQLite engine,
and when the hypothesis is incomplete, SEARCH for the missing single-bit
repairs using the engine itself as an oracle.

Two legs:

1. MANIFEST leg: apply the repair manifest (or inline patches) to a copy of the
   damaged file and run the verification ladder:
       L1 open          sqlite3 --selection of sqlite_master succeeds
       L2 integrity     PRAGMA integrity_check == 'ok'
       L3 dump equality (with --json recover.json) rows read back equal the
                        recovered JSON (this rung excludes payload-data flips,
                        which open fine but do not change the dump)
2. SEARCH leg (automatic when L1/L2 fail): single-bit search over *structural*
   bytes only -- per-page b-tree headers (type, freeblock, ncell, content_start
   both bytes, frag, interior right-most pointer), cell-pointer arrays,
   interior child pointers, plus file-header fields 16..31 (page size,
   versions, reserved, fractions, page count).  Never payload bytes: the dump
   rung makes them useless.  A flip is accepted only when it is load-bearing
   (turns a failing rung into a passing one), so healthy files and files whose
   manifest already satisfies the engine gain nothing:
     stage A (L1): the file does not open; accept the first flip per byte that
                   makes it open
     stage B (L2): the file opens but integrity fails; accept flips that make
                   open AND integrity pass
   If L3 still fails after patching, the remaining difference is payload data
   or unreachable pages: rerun the decoder on the patched copy
   (python3 recover_sqlite.py patched.db --repair-bits --out r.json) and
   re-verify.

Patches (manifest or inline) are the same format recover_sqlite.py writes with
--out-patches: a JSON object {"offset": newbyte, ...} or a list of
{"offset": N, "new": M}.

Usage:
  python3 verify_with_sqlite.py damaged.db patched.db patches.json [--json recover.json]
  python3 verify_with_sqlite.py damaged.db patched.db '[{"offset":106,"new":193}]'
"""
import base64
import json
import os
import sqlite3
import struct
import subprocess
import sys
import tempfile
from collections import Counter

BE16 = lambda b, o: struct.unpack_from(">H", b, o)[0]
BE32 = lambda b, o: struct.unpack_from(">I", b, o)[0]

HEADER_FIELDS = range(16, 32)  # page size, versions, reserved, fractions, page count


def load_patches(s):
    if os.path.isfile(s):
        with open(s) as f:
            s = f.read()
    return parse_patches(s)


def parse_patches(s):
    obj = json.loads(s)
    if isinstance(obj, dict):
        return {int(k): int(v) for k, v in obj.items()}
    return {int(p["offset"]): int(p["new"]) for p in obj}


def apply_patches(src, dst, patches, log=True):
    data = bytearray(open(src, "rb").read())
    for off, val in sorted(patches.items()):
        if not (0 <= off < len(data)):
            print("WARNING: patch offset %d out of range" % off, file=sys.stderr)
            continue
        old = data[off]
        data[off] = val & 0xFF
        if log:
            print("patched 0x%04x: 0x%02x -> 0x%02x" % (off, old, val & 0xFF))
    open(dst, "wb").write(bytes(data))
    if log:
        print("wrote %s (%d bytes)" % (dst, len(data)))
    return data


def open_ok(data):
    """L1: can the engine open this byte image and read the schema?"""
    fd, p = tempfile.mkstemp(suffix=".db")
    try:
        os.write(fd, bytes(data))
        os.close(fd)
        con = sqlite3.connect(p)
        try:
            con.execute("SELECT sql FROM sqlite_master").fetchall()
            return True
        except sqlite3.DatabaseError:
            return False
        finally:
            con.close()
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


def integrity_ok(data):
    """L2: does PRAGMA integrity_check report 'ok'?"""
    fd, p = tempfile.mkstemp(suffix=".db")
    try:
        os.write(fd, bytes(data))
        os.close(fd)
        con = sqlite3.connect(p)
        try:
            cur = con.execute("PRAGMA integrity_check;")
            rows = cur.fetchall()
            return len(rows) == 1 and rows[0][0] == "ok"
        except sqlite3.DatabaseError:
            return False
        finally:
            con.close()
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


def canon(v):
    """Hashable canonical form for L3 comparison: BLOBs become the same
    {'$blob_b64': ...} marker recover_sqlite.py emits, dicts become sorted
    JSON strings; int/float stay numeric so 10 == 10.0 compares equal."""
    if isinstance(v, bytes):
        v = {"$blob_b64": base64.b64encode(v).decode()}
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True)
    return v


def dump_vs_json(data, json_path):
    """L3: multiset-equality between the rows the engine reads back from this
    image and the recovered JSON.

    The recovered JSON is an untagged flat list that speaks only the case's
    public schema, so the comparison rule is:
      * canonical row = frozenset of (column, canon(value)) pairs (hashable);
      * DATABASE side = Counter over rows of every table whose column
        signature (frozenset of column names) appears among the recovered
        dicts -- tables outside the claim's scope can neither fail nor pass it;
      * RECOVERED side = Counter over all recovered dicts;
      * equality = Counter equality: multiplicity matters, so a missing
        duplicate row FAILs and so does any extra row (sets only catch the
        latter); an empty recover.json FAILs explicitly (no vacuous pass).
    Per-table counts (and out-of-scope tables) are diagnostics only.
    """
    if not json_path or not os.path.isfile(json_path):
        return None
    try:
        recovered = json.load(open(json_path))
    except Exception:
        return None
    fd, p = tempfile.mkstemp(suffix=".db")
    try:
        os.write(fd, bytes(data))
        os.close(fd)
        con = sqlite3.connect(p)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")]
            mismatches = []
            # untagged flat-list semantics: multiset equality over canonical
            # rows, database side restricted to tables whose column signature
            # appears in the recovered JSON (Leak-2 scope guard), Counter
            # multiplicity preserving duplicates (Leak-1 completeness guard).
            rec_dicts = [d for d in recovered if isinstance(d, dict)]
            if not rec_dicts:
                return False, []  # empty JSON must FAIL, not pass vacuously
            rec_sigs = {frozenset(d) for d in rec_dicts}
            union_db = Counter()
            for t in tables:
                cur = con.execute('SELECT * FROM "%s"' % t)
                cols = tuple(d[0] for d in cur.description)
                if frozenset(cols) not in rec_sigs:
                    mismatches.append((t, "out-of-scope"))
                    continue
                db_rows = Counter(
                    frozenset((c, canon(v)) for c, v in zip(cols, r))
                    for r in cur.fetchall())
                union_db.update(db_rows)
                rec_rows = Counter(
                    frozenset((k, canon(v)) for k, v in d.items())
                    for d in rec_dicts if set(d.keys()) == set(cols))
                mismatches.append((t, sum(db_rows.values()),
                                   sum(rec_rows.values())))
            union_rec = Counter(
                frozenset((k, canon(v)) for k, v in d.items())
                for d in rec_dicts)
            same = union_db == union_rec
            return same, mismatches
        finally:
            con.close()
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


def structural_positions(buf, page_size):
    """Byte offsets of structural fields: per-page b-tree headers, cell-pointer
    arrays, interior child pointers, and file-header fields 16..31."""
    pos = set(HEADER_FIELDS)
    n_pages = max(1, len(buf) // page_size)
    for pno in range(1, n_pages + 1):
        start = (pno - 1) * page_size
        if start >= len(buf):
            break
        hdr = start + (100 if pno == 1 else 0)  # page 1 carries the file header
        if hdr + 12 > len(buf):
            continue
        ptype = buf[hdr]
        interior = ptype in (2, 5)
        for off in range(hdr, min(hdr + 12, len(buf))):
            pos.add(off)
        ptr_off = hdr + (12 if interior else 8)
        ncell = BE16(buf, hdr + 3)
        ncell = min(ncell, 4096)
        for i in range(ncell):
            o = ptr_off + 2 * i
            if o + 2 > len(buf) or o >= start + page_size:
                break
            pos.add(o)
            pos.add(o + 1)
            if interior:
                co = BE16(buf, o)
                cabs = start + co
                min_cell = start + (100 if pno == 1 else 8)
                if min_cell <= cabs < start + page_size:
                    for k in range(4):
                        if cabs + k < len(buf):
                            pos.add(cabs + k)
    return sorted(pos)


def search(data, positions, stage):
    """Single-bit search toward a stage objective ('open' or 'integrity').

    A flip is load-bearing only: it is accepted iff the stage predicate fails
    on the current image and PASSES after the flip; the scan stops the moment
    the objective is reached, so no junk flips can be accepted once the file is
    healthy.  If one full pass yields no flip that reaches the objective, the
    search is exhausted (multi-flip structural chains are out of scope and
    reported by the caller as a bounded boundary).  Returns {offset: newbyte}
    and the final image.
    """
    def pred(b):
        if stage == "open":
            return open_ok(b)
        return open_ok(b) and integrity_ok(b)

    accepted = {}
    while not pred(data):
        progress = False
        for off in positions:
            if off in accepted or off >= len(data):
                continue
            orig = data[off]
            for bit in range(8):
                data[off] = orig ^ (1 << bit)
                if pred(data):
                    accepted[off] = data[off]
                    progress = True
                    break
            else:
                data[off] = orig
            if pred(data):
                break  # objective reached mid-pass; outer loop re-checks
        if not progress:
            break
    return accepted, data


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    src, dst = sys.argv[1], sys.argv[2]
    json_path = None
    extra = [a for a in sys.argv[3:] if not a.startswith("--")]
    for i, a in enumerate(sys.argv[3:]):
        if a == "--json" and i + 1 < len(sys.argv[3:]):
            json_path = sys.argv[3 + i + 1]
    patches = load_patches(extra[0]) if extra else {}

    if src != dst:
        data = apply_patches(src, dst, patches)
    else:
        data = bytearray(open(src, "rb").read())

    def ladder(data, label):
        print("== ladder %s ==" % label)
        ok1 = open_ok(data)
        print("L1 open          : %s" % ("ok" if ok1 else "FAIL"))
        ok2 = ok1 and integrity_ok(data)
        print("L2 integrity     : %s" % ("ok" if ok2 else "FAIL"))
        dv = dump_vs_json(data, json_path) if ok2 else None
        if dv is None:
            print("L3 dump equality : skipped (no --json or no readable tables)")
            ok3 = True
        else:
            same, mism = dv
            print("L3 dump equality : %s%s" % ("ok" if same else "FAIL",
                                               "" if same else "  " + str(mism)))
            ok3 = same
        return ok1, ok2, ok3

    o1, o2, o3 = ladder(data, "manifest")
    found = {}
    if not (o1 and o2):
        print("== engine-oracle single-bit search over structural bytes ==")
        buf0 = bytearray(open(src, "rb").read())
        page_size = BE16(buf0, 16)
        if page_size == 1:
            page_size = 65536
        positions = structural_positions(buf0, page_size)
        print("structural candidates: %d byte(s) x 8 bits" % len(positions))
        data = bytearray(open(src, "rb").read())
        for off, val in sorted(patches.items()):
            if 0 <= off < len(data):
                data[off] = val & 0xFF
        if not open_ok(data):
            a, data = search(data, positions, "open")
            found.update(a)
        if not (open_ok(data) and integrity_ok(data)):
            a, data = search(data, positions, "integrity")
            found.update(a)
        for off in sorted(found):
            print("search-patched 0x%04x -> 0x%02x" % (off, found[off]))
        open(dst, "wb").write(bytes(data))
        print("wrote %s (%d bytes) with %d search patch(es)" %
              (dst, len(data), len(found)))
        o1, o2, o3 = ladder(data, "patched")
    if not o3:
        print("== L3 failed: rerun the decoder on the patched copy ==")
        print("   python3 recover_sqlite.py %s --repair-bits --out r.json "
              "--out-patches p2.json" % dst)
        print("   then re-verify with --json r.json")
    ok = o1 and o2 and o3
    print("VERIFY %s" % ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()