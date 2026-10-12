#!/usr/bin/env python3
"""
Recover logically valid rows from a damaged SQLite database file.

Pipeline (family sqlite-db-truncate):
  1. Parse the 100-byte database header (page size, reserved bytes, page count).
  2. Parse page 1's btree page -> sqlite_master (schema) cells.
  3. For every user table rootpage, walk the btree (interior + leaf pages) and
     decode leaf cells in rowid order.
  4. Decode each record: varint(payload len) + varint(rowid) + record header
     (varint header size + per-column serial-type varints) + bodies selected by
     serial type; follow overflow chains when the payload spills off the page.
  5. Validate structural invariants (pointer gaps == decoded cell sizes, cells
     tile the content area exactly, payload len == header size + body sum).
     Repair minimal single-bit damage by enumerating 1- and 2-bit flips over
     failing cells / structural fields and keeping candidates that satisfy
     every invariant; re-verify with the `sqlite3` binary when available.
  6. Emit rows as JSON using the case-specific schema (column names parsed from
     the CREATE TABLE statement), ordered by rowid.

Usage:
  recover_sqlite.py [options] DAMAGED.db
    --table NAME        table to recover (default: first user table)
    --key-regex RE      only emit rows whose first TEXT column matches RE
    --out FILE          output JSON path (default: recover.json next to the
                        database; '-' prints JSON to stdout)
    --repair-file FILE  write the repaired db copy here
    --replica FILE      undamaged reference db for a bit-census diff
    --census            print corruption census (flip rates) and exit
    --max-flips N       enumeration depth for repair search (default 2)
    --window N          repair search window in bytes (default 64)

The reader is strict but forgiving: it decodes everything it can and reports
unresolvable cells instead of aborting, so one bad record never sinks its
neighbors.
"""

import argparse
import json
import os
import re
import struct
import subprocess
import sys

# --------------------------------------------------------------------------
# Low-level readers
# --------------------------------------------------------------------------

def read_varint(data, off):
    """SQLite varint: big-endian 7-bit groups; the 9th byte uses all 8 bits."""
    v = 0
    for i in range(9):
        if off + i >= len(data):
            raise ValueError("varint runs past end of data")
        b = data[off + i]
        if i == 8:
            v = (v << 8) | b
        else:
            v = (v << 7) | (b & 0x7F)
        if b < 0x80:
            return v, off + i + 1
    raise ValueError("varint longer than 9 bytes")


def be_int(data, off, n):
    return int.from_bytes(data[off:off + n], "big", signed=True)


# Serial type -> (kind, body size). Kinds: null / int / float / text / blob.
SERIAL = {
    0: ("null", 0), 1: ("int", 1), 2: ("int", 2), 3: ("int", 3), 4: ("int", 4),
    5: ("int", 6), 6: ("int", 8), 7: ("float", 8), 8: ("int", 0), 9: ("int", 0),
}


def serial_info(st):
    if st in SERIAL:
        return SERIAL[st]
    if st >= 12:
        n = (st - 12) // 2
        return ("blob" if st % 2 == 0 else "text", n)
    raise ValueError("reserved serial type %d" % st)


# --------------------------------------------------------------------------
# Header + pages
# --------------------------------------------------------------------------

def parse_header(data):
    if len(data) < 100:
        raise ValueError("file too short for a sqlite header (%d bytes) — "
                         "truncated?" % len(data))
    if data[:16] != b"SQLite format 3\x00":
        raise ValueError("not a sqlite file (bad magic)")
    page_size = (data[16] << 8) | data[17]
    if page_size == 1:
        page_size = 65536          # 65536 is encoded as 1
    if page_size < 512 or page_size > 65536 or (page_size & (page_size - 1)):
        raise ValueError("implausible page size %d" % page_size)
    return {
        "page_size": page_size,
        "write_version": data[18], "read_version": data[19],
        "reserved_bytes": data[20],
        "change_counter": be_int(data, 24, 4),
        "size_in_pages_legacy": be_int(data, 28, 4) or None,
        "freelist_pages": be_int(data, 36, 4),
        "schema_cookie": be_int(data, 40, 4),
        "schema_format": be_int(data, 44, 4),
        "text_encoding": be_int(data, 56, 4),
        "version_valid_for": be_int(data, 92, 4),
        "sqlite_version": be_int(data, 96, 4),
    }


def parse_page(data, page_no, page_size, reserved=0):
    """One btree page. 'offset' is the page start (cell offsets are
    page-relative); 'bhdr' is where the 8/12-byte btree header begins
    (page 1 carries the 100-byte database header before it)."""
    page_start = (page_no - 1) * page_size
    if page_no == 1:
        if len(data) < 100:
            raise ValueError("file too short for page 1 header")
        bhdr = 100
    else:
        bhdr = page_start
    # Truncation guards: pages beyond EOF (or with a cut-off btree header)
    # become note pages instead of raising IndexError; walkers and repair
    # loops already skip note pages, so truncated files degrade to
    # "recover what remains" instead of crashing.
    if page_start >= len(data):
        return {"type": 0, "cell_count": 0, "pointers": [],
                "page_no": page_no, "offset": page_start, "bhdr": bhdr,
                "note": "page %d beyond EOF (truncated)" % page_no}
    if bhdr + 8 > len(data):
        return {"type": 0, "cell_count": 0, "pointers": [],
                "page_no": page_no, "offset": page_start, "bhdr": bhdr,
                "note": "page %d header truncated (%d bytes present)"
                % (page_no, len(data) - page_start)}
    ptype = data[bhdr]
    if ptype in (0x0D, 0x05):       # leaf / interior table page
        freeblock, cells, cstart, frag = struct.unpack(
            ">HHHB", data[bhdr + 1:bhdr + 8])
        if ptype == 0x05:
            right = be_int(data, bhdr + 8, 4)
            ptr_off = bhdr + 12
        else:
            right, ptr_off = None, bhdr + 8
        ptrs = [struct.unpack(">H", data[ptr_off + 2 * i:ptr_off + 2 + 2 * i])[0]
                for i in range(cells)]
        return {"type": ptype, "freeblock": freeblock, "cell_count": cells,
                "content_start": cstart, "fragmented": frag, "pointers": ptrs,
                "right_child": right, "page_no": page_no, "offset": page_start,
                "bhdr": bhdr}
    return {"type": ptype, "cell_count": 0, "pointers": [], "page_no": page_no,
            "offset": page_start, "bhdr": bhdr,
            "note": "index/overflow page type 0x%02x" % ptype}


# --------------------------------------------------------------------------
# Cell / record decoding
# --------------------------------------------------------------------------

def local_payload_len(payload_len, usable, is_leaf_table=True):
    """How much of a payload stays on the page (SQLite spill rule).
    Verified formula from btree.c fillInCell/parseCell."""
    x = usable - 35 if is_leaf_table else usable - 12
    if payload_len <= x:
        return payload_len
    m = ((usable - 12) * 32) // 255 - 23
    k = m + ((payload_len - m) % (usable - 4))
    if k < 0 or k > payload_len or (k > 0 and k < m):
        k = min(payload_len, x)     # corrupted path; keep parsing sane
    return k


def decode_record(payload):
    """Split a record payload into (values, serial_types)."""
    hdr_size, q = read_varint(payload, 0)
    stypes = []
    hdr_bytes = 1
    while hdr_bytes < hdr_size:
        st, q2 = read_varint(payload, q)
        stypes.append(st)
        hdr_bytes += q2 - q
        q = q2
    if hdr_bytes != hdr_size:
        raise ValueError("record header size mismatch %d != %d" % (hdr_bytes, hdr_size))
    values = []
    for st in stypes:
        kind, n = serial_info(st)
        if kind == "int":
            values.append(0 if st == 8 else (1 if st == 9 else be_int(payload, q, n)))
        elif kind == "float":
            values.append(struct.unpack(">d", payload[q:q + 8])[0])
        elif kind == "text":
            values.append(payload[q:q + n].decode("utf-8", "replace"))
        elif kind == "blob":
            values.append(payload[q:q + n].hex())
        else:
            values.append(None)
        q += n
    if q != len(payload):
        raise ValueError("record body size mismatch (%d != %d)" % (q, len(payload)))
    return values, stypes


def decode_leaf_cell(data, page, cell_off, page_size, reserved):
    """Decode one table-leaf cell (following overflow chains). 'cell_off' is
    page-relative.  Raises ValueError on any structural inconsistency."""
    off = page["offset"] + cell_off
    payload_len, p = read_varint(data, off)
    rowid, p = read_varint(data, p)
    usable = page_size - reserved
    local = local_payload_len(payload_len, usable, True)
    payload = bytearray(data[p:p + local])
    overflow_pages = []
    if local < payload_len:
        if p + local + 4 > len(data):
            raise ValueError("overflow pointer truncated")
        op = be_int(data, p + local, 4)       # first overflow page
        while op:
            overflow_pages.append(op)
            ooff = (op - 1) * page_size
            if ooff + 4 > len(data):
                raise ValueError("overflow page %d out of file" % op)
            nxt = be_int(data, ooff, 4)       # next overflow page (0 = end)
            take = min(usable - 4, payload_len - len(payload))
            payload += data[ooff + 4:ooff + 4 + take]
            op = nxt
    if len(payload) < payload_len:
        raise ValueError("payload truncated (%d < %d)" % (len(payload), payload_len))
    payload = bytes(payload[:payload_len])
    values, stypes = decode_record(payload)
    cell_len = (p - off) + local + (4 if local < payload_len else 0)
    return {"rowid": rowid, "values": values, "serial_types": stypes,
            "payload_len": payload_len, "cell_len": cell_len,
            "offset": cell_off, "overflow": overflow_pages}


# --------------------------------------------------------------------------
# Btree walking + schema
# --------------------------------------------------------------------------

def walk_btree(data, page_no, page_size, reserved, out):
    """Collect (page_no, cell_pointer) for every leaf cell of a table btree."""
    page = parse_page(data, page_no, page_size, reserved)
    if page.get("note"):
        return out
    if page["type"] == 0x05:                  # interior: children then right
        for ptr in page["pointers"]:
            child = be_int(data, page["offset"] + ptr, 4)
            walk_btree(data, child, page_size, reserved, out)
        walk_btree(data, page["right_child"], page_size, reserved, out)
    else:
        out.extend((page_no, ptr) for ptr in page["pointers"])
    return out


def decode_schema_cell(data, page, ptr, page_size, reserved):
    cell = decode_leaf_cell(data, page, ptr, page_size, reserved)
    vals, st = cell["values"], cell["serial_types"]
    if len(vals) >= 5 and vals[0] in ("table", "index", "view", "trigger"):
        return {"type": vals[0], "name": vals[1], "tbl_name": vals[2],
                "rootpage": vals[3], "sql": vals[4], "serial_types": st}
    return None


def table_columns(sql):
    """Parse column names out of a CREATE TABLE statement."""
    m = re.match(r"CREATE\s+TABLE\s+(?:[\w\"]+\.)?[\"`]?(\w+)[\"`]?\s*\((.*)\)\s*$",
                 sql or "", re.S | re.I)
    if not m:
        return None
    names = []
    for c in m.group(2).split(","):
        cm = re.match(r"\s*[\"`]?([A-Za-z_]\w*)[\"`]?\s", c)
        if cm:
            names.append(cm.group(1))
    return names or None


def int_pk_column(sql):
    """Column that is a rowid alias (exactly INTEGER PRIMARY KEY, alone,
    optional ASC/AUTOINCREMENT, no DESC) in a rowid table, or None.
    IMPORTANT: the alias column OCCUPIES a payload slot holding serial type 0
    (NULL); the real value rides in the cell's rowid varint and must be taken
    from there regardless of what the slot holds (a paranoid external writer
    might even omit the slot). Composite keys, DESC, and WITHOUT ROWID tables
    are NOT aliases."""
    if not sql or "WITHOUT ROWID" in sql.upper():
        return None
    m = re.match(r"CREATE\s+TABLE\s+(?:[\w\"]+\.)?[\"`]?(\w+)[\"`]?\s*\((.*)\)\s*$",
                 sql, re.S | re.I)
    if not m:
        return None
    depth, parts, cur = 0, [], []
    for ch in m.group(2):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    for c in parts:
        cm = re.match(r"\s*[\"`]?([A-Za-z_]\w*)[\"`]?\s+INTEGER\s+PRIMARY\s+KEY"
                      r"(?:\s+(?:ASC|AUTOINCREMENT))?"
                      r"(?:\s+ON\s+CONFLICT\s+\w+)?$", c, re.I)
        if cm and "DESC" not in c.upper():
            return cm.group(1)
    return None


# --------------------------------------------------------------------------
# Structural validation
# --------------------------------------------------------------------------

def cell_fits_page(page, cell, page_size, reserved):
    """Does this cell occupy exactly its slot in the page's cell order?
    Cells are packed contiguously from content_start upward; cell 0 (first in
    the pointer array) sits at the highest address and must end at the usable
    end of the page; every later cell i spans [ptrs[i], ptrs[i-1])."""
    if page["freeblock"] != 0 or page["fragmented"] != 0:
        return True            # free space makes gaps legitimate
    ptrs = page["pointers"]
    try:
        i = ptrs.index(cell["offset"])
    except ValueError:
        return False
    usable = page_size - reserved
    if i == 0:
        return cell["cell_len"] == usable - ptrs[0]
    return cell["cell_len"] == ptrs[i - 1] - ptrs[i]


def page_tiling_ok(page, cells, page_size, reserved):
    """Compact-page invariants (no freeblocks, no fragmentation):
      * cell count == number of pointers == number of decoded cells
      * every cell fits its slot (see cell_fits_page)
      * the lowest cell starts exactly at content_start.
    A page with zero cells is never 'ok' (a hypothesis that erases evidence
    is not a repair)."""
    if page["freeblock"] != 0 or page["fragmented"] != 0:
        return True
    if page["cell_count"] == 0 or len(cells) != page["cell_count"]:
        return False
    by_off = {c["offset"]: c for c in cells}
    ptrs = page["pointers"]
    if not ptrs:
        return False
    for p in ptrs:
        if p not in by_off or not cell_fits_page(page, by_off[p], page_size,
                                                 reserved):
            return False
    return ptrs[-1] == page["content_start"]


# --------------------------------------------------------------------------
# Repair by bit-flip enumeration
# --------------------------------------------------------------------------

def try_repair_cell(data, page, cell_off, page_size, reserved, max_flips,
                    window=30, plausible=None):
    """Try 1..max_flips bit flips in the structural prefix of a failing cell
    (payload-length/rowid varints + record header).  Keep repairs whose decode
    succeeds, whose cell length fits the page layout, and (when a predicate is
    given) whose values are plausible.  Returns min-flip candidates."""
    off = page["offset"] + cell_off
    lo = off                                  # structural prefix only
    hi = min(len(data), off + window)
    cands = []
    for nf in range(1, max_flips + 1):
        _enumerate_flips(data, lo, hi, nf, page, cell_off, page_size, reserved,
                         cands, [], plausible)
        if cands:
            break
    return cands


def _enumerate_flips(data, lo, hi, n, page, cell_off, page_size, reserved,
                     cands, flips, plausible=None):
    """Recursive enumeration of n bit flips in data[lo:hi] (mutates + reverts
    the bytearray in place)."""
    if n == 0:
        work = bytes(data)
        try:
            p2 = parse_page(work, page["page_no"], page_size, reserved)
            cell = decode_leaf_cell(work, p2, cell_off, page_size, reserved)
            if cell_fits_page(p2, cell, page_size, reserved) and \
               (plausible is None or plausible(cell)):
                cands.append((list(flips), cell))
        except Exception:
            pass
        return
    for pos in range(lo, hi):
        for bit in range(8):
            data[pos] ^= (1 << bit)
            flips.append((pos, bit))
            _enumerate_flips(data, pos, hi, n - 1, page, cell_off, page_size,
                             reserved, cands, flips, plausible)
            flips.pop()
            data[pos] ^= (1 << bit)


def repair_page_fields(data, page, cells, page_size, reserved, max_flips):
    """Fix content-start / cell pointers when the page does not tile.
    Only the content-start field, the pointer array, and an interior page's
    right-child pointer may be flipped: type / freeblock / cell-count /
    fragmentation bytes are structural anchors and are never inferred.
    Returns (modified bytearray, flips)."""
    work = bytearray(data)
    if page_tiling_ok(page, cells, page_size, reserved):
        return work, []
    bh = page["bhdr"]
    allowed = list(range(bh + 5, bh + 7))                # content-start
    if page["type"] == 0x05:
        allowed += list(range(bh + 8, bh + 12))          # right child
    po = bh + (12 if page["type"] == 0x05 else 8)
    allowed += list(range(po, po + 2 * page["cell_count"]))  # pointers
    cands = []
    for nf in range(1, max_flips + 1):
        _enumerate_field_flips(work, allowed, nf, page, page_size, reserved,
                               cands, [])
        if cands:
            break
    if not cands:
        return work, []
    flips, p2, new_cells = min(cands, key=lambda c: len(c[0]))
    for pos, bit in flips:
        work[pos] ^= (1 << bit)
    return work, flips


def _enumerate_field_flips(data, allowed, n, page, page_size, reserved, cands,
                           flips):
    """Recursive enumeration of n bit flips over the allowed positions."""
    if n == 0:
        work = bytes(data)
        try:
            p2 = parse_page(work, page["page_no"], page_size, reserved)
            new_cells = []
            for ptr in p2["pointers"]:
                new_cells.append(decode_leaf_cell(work, p2, ptr, page_size,
                                                  reserved))
            if page_tiling_ok(p2, new_cells, page_size, reserved):
                cands.append((list(flips), p2, new_cells))
        except Exception:
            pass
        return
    for pos in allowed:
        for bit in range(8):
            data[pos] ^= (1 << bit)
            flips.append((pos, bit))
            _enumerate_field_flips(data, allowed, n - 1, page, page_size,
                                   reserved, cands, flips)
            flips.pop()
            data[pos] ^= (1 << bit)


# --------------------------------------------------------------------------
# Oracle + census
# --------------------------------------------------------------------------

def which(cmd):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d or ".", cmd)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def sqlite3_check(db_path, table=None, cols=None):
    """Ask the sqlite3 CLI (if present) to read the db. Returns (ok, detail)."""
    if not which("sqlite3"):
        return None, "sqlite3 binary not found"
    r = subprocess.run(["sqlite3", db_path, "PRAGMA integrity_check;"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, (r.stdout + r.stderr).strip()
    if "ok" not in r.stdout.strip().lower():
        return False, r.stdout.strip().splitlines()[:3]
    if table:
        colq = ", ".join('quote("%s")' % c for c in cols) if cols else "*"
        r2 = subprocess.run(["sqlite3", db_path,
                             'SELECT rowid, %s FROM "%s";' % (colq, table)],
                            capture_output=True, text=True)
        if r2.returncode != 0:
            return False, r2.stderr.strip()
        return True, r2.stdout.strip()
    return True, "integrity ok"


def census(data, replica_bytes):
    n = min(len(data), len(replica_bytes))
    zeros = ones = set_01 = clear_10 = 0
    for i in range(n):
        t, r = data[i], replica_bytes[i]
        for b in range(8):
            tb, rb = (t >> b) & 1, (r >> b) & 1
            zeros += (rb == 0)
            ones += (rb == 1)
            set_01 += (tb and not rb)
            clear_10 += (rb and not tb)
    p01 = set_01 / zeros if zeros else 0.0
    return {"zeros": zeros, "ones": ones, "set_bits_0to1": set_01,
            "cleared_bits_1to0": clear_10, "p01": p01,
            "p10": clear_10 / ones if ones else 0.0,
            "predicted_cleared_if_symmetric": round(ones * p01, 2)}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("db")
    ap.add_argument("--table", default=None)
    ap.add_argument("--key-regex", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--repair-file", default=None)
    ap.add_argument("--replica", default=None)
    ap.add_argument("--census", action="store_true")
    ap.add_argument("--max-flips", type=int, default=2)
    ap.add_argument("--window", type=int, default=64)
    args = ap.parse_args()

    # Interface contract: no --out writes recover.json next to the database
    # (so `python3 recover_sqlite.py /app/trunc.db` from any cwd still
    # produces /app/recover.json); --out - prints JSON to stdout.
    if args.out is None:
        db_dir = os.path.dirname(os.path.abspath(args.db)) or "."
        args.out = os.path.join(db_dir, "recover.json")

    try:
        data = open(args.db, "rb").read()
        hdr = parse_header(data)
    except (OSError, ValueError) as e:
        sys.stderr.write("cannot read %s: %s\n" % (args.db, e))
        return 1
    page_size, reserved = hdr["page_size"], hdr["reserved_bytes"]
    declared = hdr["size_in_pages_legacy"]
    actual = len(data) // page_size
    sys.stderr.write("pagesize=%d reserved=%d declared_pages=%s actual_pages=%d\n"
                     % (page_size, reserved, declared, actual))
    if declared and actual < declared:
        sys.stderr.write("WARNING: file shorter than declared page count "
                         "(truncated?); trailing pages/rows unavailable\n")

    if args.census:
        if not args.replica:
            sys.stderr.write("--census requires --replica REFERENCE.db\n")
            return 2
        print(json.dumps(census(data, open(args.replica, "rb").read()), indent=1))
        return 0

    work = bytearray(data)
    repairs = []

    def record_repair(where, flips, extra=None):
        repairs.append({"where": where, "flips": flips, **({} if extra is None
                                                          else extra)})
        sys.stderr.write("repair %s: %s\n" % (where, ", ".join(
            "%04x bit%d" % f for f in flips)))

    # ---- schema recovery (page 1) -------------------------------------
    def schema_plausible(cell):
        vals = cell["values"]
        return (len(vals) >= 5
                and isinstance(vals[0], str)
                and vals[0] in ("table", "index", "view", "trigger")
                and isinstance(vals[1], str) and vals[1].isprintable()
                and isinstance(vals[2], str) and vals[2].isprintable()
                and isinstance(vals[3], int) and 1 <= vals[3] < 65536
                and isinstance(vals[4], str) and vals[4].isprintable())

    schema = []
    for attempt in range(4):
        new = 0
        page = parse_page(bytes(work), 1, page_size, reserved)
        if page.get("note"):
            break
        rows_now = []
        for ptr in page["pointers"]:
            try:
                cell = decode_leaf_cell(bytes(work), page, ptr, page_size,
                                        reserved)
                row = decode_schema_cell(bytes(work), page, ptr, page_size,
                                         reserved)
                if row is None or not schema_plausible(cell):
                    raise ValueError("schema cell implausible values")
                rows_now.append((ptr, row))
            except Exception as e:
                cands = try_repair_cell(work, page, ptr, page_size, reserved,
                                        args.max_flips, args.window,
                                        plausible=schema_plausible)
                if not cands:
                    sys.stderr.write("schema cell %04x UNRESOLVED: %s\n"
                                     % (ptr, e))
                    continue
                flips, cell = min(cands, key=lambda c: len(c[0]))
                for pos, bit in flips:
                    work[pos] ^= (1 << bit)
                record_repair("schema cell at %04x (record header)" % ptr,
                              flips)
                new += 1
                page = parse_page(bytes(work), 1, page_size, reserved)
                try:
                    row = decode_schema_cell(bytes(work), page, ptr, page_size,
                                             reserved)
                    if row is None:
                        continue
                except Exception as e2:
                    sys.stderr.write("schema cell %04x STILL FAILS: %s\n"
                                     % (ptr, e2))
                    continue
                rows_now.append((ptr, row))
        # page-1 field tiling (only when every pointer decoded cleanly)
        page = parse_page(bytes(work), 1, page_size, reserved)
        cells = []
        ok_cells = True
        for ptr, _ in rows_now:
            try:
                cells.append(decode_leaf_cell(bytes(work), page, ptr,
                                              page_size, reserved))
            except Exception:
                ok_cells = False
                break
        if ok_cells and not page_tiling_ok(page, cells, page_size, reserved):
            new_work, flips = repair_page_fields(work, page, cells, page_size,
                                                 reserved, args.max_flips)
            if flips:
                work = new_work
                record_repair("page 1 fields (content-start/pointers)",
                              flips)
                new += 1
            else:
                sys.stderr.write("page 1 tiling UNRESOLVED\n")
        schema = [r for _, r in rows_now if r]
        if new == 0:
            break
    sys.stderr.write("schema rows: %d\n" % len(schema))

    tables = [s for s in schema if s["type"] == "table"
              and isinstance(s["name"], str)
              and not s["name"].startswith("sqlite_")]
    if args.table:
        tables = [t for t in tables if t["name"] == args.table]
    if not tables:
        available = ", ".join(s["name"] for s in schema
                              if s["type"] == "table"
                              and isinstance(s["name"], str))
        sys.stderr.write("no user table found%s\n" % (
            (" (available: %s)" % available) if available
            else " (schema decode failed?)"))
        return 1
    if len(tables) > 1 and not args.table:
        sys.stderr.write(
            "WARNING: %d user tables; recovering only '%s' (pass --table NAME "
            "to choose another, or run once per table and merge per the case "
            "schema): %s\n"
            % (len(tables), tables[0]["name"],
               ", ".join(t["name"] for t in tables)))
    table = tables[0]
    cols = table_columns(table["sql"])
    if cols is None:
        cols = ["col%d" % i for i in range(64)]
    sys.stderr.write("recovering table '%s' rootpage=%d columns=%s\n"
                     % (table["name"], table["rootpage"], cols))

    key_rx = re.compile(args.key_regex) if args.key_regex else None

    def row_plausible(cell):
        vals = cell["values"]
        for v in vals:
            if isinstance(v, str) and not v.isprintable():
                return False
        if key_rx is not None:
            return isinstance(vals[0], str) and bool(key_rx.match(vals[0]))
        return True

    # ---- table recovery with repair iterations ------------------------
    rows, failed = [], 0
    for attempt in range(4):
        leaf_cells = []
        walk_btree(bytes(work), table["rootpage"], page_size, reserved,
                   leaf_cells)
        rows, failed = [], 0
        cells_by_page = {}
        new = 0
        for pageno, ptr in leaf_cells:
            page = parse_page(bytes(work), pageno, page_size, reserved)
            try:
                cell = decode_leaf_cell(bytes(work), page, ptr, page_size,
                                        reserved)
            except Exception as e:
                cands = try_repair_cell(work, page, ptr, page_size, reserved,
                                        args.max_flips, args.window,
                                        plausible=row_plausible)
                if not cands:
                    sys.stderr.write("cell page=%d off=%04x UNRESOLVED: %s\n"
                                     % (pageno, ptr, e))
                    failed += 1
                    continue
                flips, cell = min(cands, key=lambda c: len(c[0]))
                for pos, bit in flips:
                    work[pos] ^= (1 << bit)
                record_repair("cell page=%d off=%04x (record header)"
                              % (pageno, ptr), flips,
                              {"rowid": cell["rowid"],
                               "serial_types": cell["serial_types"]})
                page = parse_page(bytes(work), pageno, page_size, reserved)
                cell = decode_leaf_cell(bytes(work), page, ptr, page_size,
                                        reserved)
                new += 1
            cells_by_page.setdefault(pageno, []).append(cell)
            rows.append((cell["rowid"], cell["values"]))
        for pageno, cells in cells_by_page.items():
            page = parse_page(bytes(work), pageno, page_size, reserved)
            if page.get("note"):
                continue
            if not page_tiling_ok(page, cells, page_size, reserved):
                new_work, flips = repair_page_fields(work, page, cells,
                                                     page_size, reserved,
                                                     args.max_flips)
                if flips:
                    work = new_work
                    record_repair("page %d fields (content-start/pointers)"
                                   % pageno, flips)
                    new += 1
                else:
                    sys.stderr.write("page %d tiling UNRESOLVED\n" % pageno)
        if new == 0:
            break
    rows = sorted({r[0]: r for r in rows}.values(), key=lambda r: r[0])
    sys.stderr.write("decoded %d rows, %d unresolved cells, %d repair(s)\n"
                     % (len(rows), failed, len(repairs)))

    if args.repair_file:
        open(args.repair_file, "wb").write(bytes(work))
        sys.stderr.write("repaired copy -> %s\n" % args.repair_file)

    if args.key_regex:
        rx = re.compile(args.key_regex)
        rows = [r for r in rows if r[1] and isinstance(r[1][0], str)
                and rx.match(r[1][0])]
        sys.stderr.write("after key filter: %d rows\n" % len(rows))

    out_rows = []
    pk_col = int_pk_column(table["sql"])
    for rowid, vals in rows:
        rec = {}
        vi = 0
        # The rowid-alias column occupies a payload slot (NULL) when present;
        # the real value always comes from the cell rowid.
        slot_present = bool(pk_col and len(vals) == len(cols))
        for name in cols:
            if name == pk_col:
                rec[name] = rowid
                if slot_present:
                    vi += 1               # consume the NULL slot
            else:
                rec[name] = vals[vi] if vi < len(vals) else None
                vi += 1
        out_rows.append(rec)
    if args.out == "-":
        print(json.dumps(out_rows, indent=1, ensure_ascii=False))
    else:
        with open(args.out, "w") as f:
            json.dump(out_rows, f, indent=1, ensure_ascii=False)
        sys.stderr.write("wrote %s (%d rows)\n" % (args.out, len(out_rows)))

    if args.repair_file and which("sqlite3"):
        ok, detail = sqlite3_check(args.repair_file, table["name"], cols)
        sys.stderr.write("sqlite3 oracle on repaired copy: %s\n"
                         % ("OK" if ok else "FAIL"))
        if ok and isinstance(detail, str):
            sys.stderr.write("sqlite3 rows:\n%s\n" % detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())