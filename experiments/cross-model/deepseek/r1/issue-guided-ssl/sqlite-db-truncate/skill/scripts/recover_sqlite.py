#!/usr/bin/env python3
"""
recover_sqlite.py -- recover logically valid rows from a damaged SQLite file.

Self-validating decoder of the SQLite on-disk format. It never trusts damaged
structural bytes: every record must be *exactly self-consistent* (serial-type
widths must sum to the declared payload length, the record must end inside the
page, text columns must look like text, and -- when the schema is known -- the
column count must match).  Optional single-bit repair proposes candidate fixes
for corrupted record-header bytes; a *layered validator* (record exactness ->
value shape -> schema/semantic invariants) picks the best candidate.

Pipeline (intact behavior first, then carving):
  1. sqlite3 FILE ".recover"   (CLI forensic dump; try it first, often fails
                                when the schema page itself is damaged)
  2. structural decode: file header -> b-tree pages -> cell pointers ->
     table-leaf cells -> records -> sqlite_master schema -> data pages.
  3. --carve: brute-force sweep of every byte offset for self-consistent
     table-leaf records (survives zeroed/destroyed page headers and truncation).

Usage:
  python3 recover_sqlite.py FILE [--out OUT.json]
      [--columns name1,name2]        # fallback column names if schema lost
      [--tables t1,t2]               # restrict to these tables
      [--key-regex col:^pattern$]    # extra validation on a text column
      [--carve]                      # byte-offset carving fallback
      [--repair-bits]                # try single-bit fixes in record headers
      [--page-size N]                # force page size if header damaged
      [--schema-only]                # print recovered schema and exit
"""
import argparse
import base64
import json
import re
import struct
import sys

BE16 = lambda b, o: struct.unpack_from(">H", b, o)[0]
BE32 = lambda b, o: struct.unpack_from(">I", b, o)[0]


def varint(buf, off):
    """SQLite varint: big-endian, 7 payload bits per byte, high bit = more."""
    v = 0
    for i in range(9):
        if off >= len(buf):
            raise ValueError("varint past EOF")
        x = buf[off]
        off += 1
        v = (v << 7) | (x & 0x7F)
        if x < 0x80:
            return v, off
    raise ValueError("varint longer than 9 bytes")


def serial_width(st):
    """Return (width, kind, constant_value_or_None) for a SQLite serial type."""
    if st == 0:
        return 0, "null", None
    if 1 <= st <= 4:
        return st, "int", None
    if st == 5:
        return 6, "int", None
    if st == 6:
        return 8, "int", None
    if st == 7:
        return 8, "float", None
    if st == 8:
        return 0, "int", 0
    if st == 9:
        return 0, "int", 1
    if st >= 12:
        if st % 2 == 0:
            return (st - 12) // 2, "blob", None
        return (st - 13) // 2, "text", None
    raise ValueError("reserved serial type %d" % st)


def decode_value(raw, kind, cst, text_enc):
    if kind == "int":
        return cst if cst is not None else int.from_bytes(raw, "big", signed=True)
    if kind == "float":
        return struct.unpack(">d", raw)[0]
    if kind == "text":
        return raw.decode(text_enc, errors="replace")
    if kind == "blob":
        return raw
    return None


def printable_ratio(b):
    if not b:
        return 1.0
    ok = sum(1 for c in b if 0x20 <= c < 0x7F or c in (0x09, 0x0A, 0x0D) or c >= 0x80)
    return ok / len(b)


TEXT_PLAUSIBLE = 0.85


def _try_parse(buf, off, payload_end, text_enc):
    """Attempt an exact parse; returns (values, kinds, raws, end) or None."""
    try:
        # NOTE: the record-header-length varint counts itself, so the header
        # (length varint + serial types) ends at off + hlen and the packed
        # values begin there too.  An off-by-one here corrupts every parse.
        hlen, _s0 = varint(buf, off)
        hdr_end = off + hlen
        if hlen <= 0 or hdr_end > payload_end:
            return None
        types, p = [], off + 1
        while p < hdr_end:
            st, p = varint(buf, p)
            types.append(st)
        if p != hdr_end:
            return None
        raws, kinds = [], []
        q = hdr_end
        for st in types:
            w, kind, cst = serial_width(st)
            if q + w > payload_end:
                return None
            raws.append(bytes(buf[q:q + w]))
            q += w
            kinds.append(kind)
        if q != payload_end:
            return None
        for raw, k in zip(raws, kinds):
            if k == "text" and printable_ratio(raw) < TEXT_PLAUSIBLE:
                return None
        values = []
        for raw, k, st in zip(raws, kinds, types):
            _, _, cst = serial_width(st)
            values.append(decode_value(raw, k, cst, text_enc))
        return values, kinds, raws, q
    except ValueError:
        return None


def _text_score(values, kinds):
    """Higher = more plausible text (used as an unambiguous tie-breaker)."""
    tot, n = 0.0, 0
    for v, k in zip(values, kinds):
        if k == "text" and isinstance(v, str):
            raw = v.encode("utf-8", "replace")
            tot += printable_ratio(raw)
            n += 1
    return tot / n if n else 0.0


def collect_parses(buf, off, payload_end, text_enc, repair):
    """All exact self-consistent parses of the record at `off`.

    Without repair this is at most one.  With repair, every single-bit flip of
    every byte inside the record-header region is tried as well.  Returns a
    list of (values, kinds, end_off, repairs_dict_or_None).
    """
    out = []
    res = _try_parse(buf, off, payload_end, text_enc)
    if res is not None:
        values, kinds, _, q = res
        out.append((values, kinds, q, None))
    if not repair:
        return out
    win_end = min(payload_end, off + 64)
    for pos in range(off, win_end):
        orig = buf[pos]
        for bit in range(8):
            buf[pos] = orig ^ (1 << bit)
            try:
                res = _try_parse(buf, off, payload_end, text_enc)
                if res is not None:
                    values, kinds, _, q = res
                    out.append((values, kinds, q, {pos: (orig, orig ^ (1 << bit))}))
            finally:
                buf[pos] = orig
    return out


def default_pick(cands):
    """Context-free choice: fewest repairs, then most text-plausible."""
    def key(c):
        values, kinds, _, repairs = c
        return (len(repairs) if repairs else 0, -_text_score(values, kinds))
    cands.sort(key=key)
    return cands[0]


def parse_record(buf, off, payload_end, text_enc, repair=False, pick=None):
    """One SQLite record. Returns (values, kinds, end_off, repairs) or None."""
    cands = collect_parses(buf, off, payload_end, text_enc, repair)
    if not cands:
        return None
    chosen = None
    if pick is not None:
        chosen = pick(cands)
    if chosen is None:
        chosen = default_pick(cands)
    values, kinds, q, rep = chosen
    return values, kinds, q, rep


def local_payload_size(usable, P, kind="table_leaf"):
    """SQLite overflow rule: how many payload bytes stay on the original page.

    X = U-35 (table leaf) / ((U-12)*64//255)-23 (interior, index);
    M = ((U-12)*32//255)-23.  For P <= X the payload is fully local.  For
    P > X the engine computes K = M + (P-M) % (U-4); the local size is K when
    K <= X, otherwise M (the X-cap).  This is btree.c btreeParseCellPayload:
    surplus = minLocal + (nPayload-minLocal) % (usableSize-4);
    nLocal = (surplus <= maxLocal) ? surplus : minLocal;

    Without the X-cap, healthy rows whose (P-M) mod (U-4) exceeds X-M (e.g.
    U=512: P in [986,1054]+508k; U=4096: P in [8154,8672]+4092k) are decoded
    at a pointer position payload_start+K that does not exist and are dropped
    ("failed exact decode" / "overflow payload too short" NOTES).  Verified
    against the engine's own pointer placement for every residue in one full
    (U-4) cycle at U=512 and U=4096 (4626 overflow records, 0 mismatches).
    """
    if kind == "table_leaf":
        X = usable - 35
        M = ((usable - 12) * 32) // 255 - 23
    else:  # interior table and all index pages
        X = ((usable - 12) * 64) // 255 - 23
        M = ((usable - 12) * 32) // 255 - 23
    if P <= X:
        return P
    K = M + (P - M) % (usable - 4)   # Python % is non-negative
    return K if K <= X else M


def read_payload(buf, payload_start, P, usable, page_size):
    """Reassemble the full payload for a table-leaf cell, following overflow
    chains.  Returns (payload_bytes, local_size_or_None).  For P <= usable-35
    everything is local and no overflow pointer exists."""
    L = local_payload_size(usable, P)
    if L == P:
        if payload_start + P > len(buf):
            raise ValueError("record overruns EOF")
        return bytes(buf[payload_start:payload_start + P]), None
    if payload_start + L + 4 > len(buf):
        raise ValueError("overflow pointer past EOF")
    first = bytes(buf[payload_start:payload_start + L])
    nxt = BE32(buf, payload_start + L)
    out = bytearray(first)
    hops = 0
    max_page = len(buf) // page_size
    while nxt != 0:
        hops += 1
        if hops > 10000 or nxt > max_page + 1:
            raise ValueError("overflow chain out of bounds")
        op = (nxt - 1) * page_size
        if op + 4 > len(buf):
            raise ValueError("overflow page past EOF")
        nxt = BE32(buf, op)
        out += bytes(buf[op + 4:op + usable])
    if len(out) < P:
        raise ValueError("overflow payload too short")
    return bytes(out[:P]), L


def decode_leaf_cell(buf, cell_start, usable, page_size, text_enc, repair,
                     page_end=None, pick=None):
    """Decode a table-leaf cell (varint payload, varint rowid, record).

    Returns a dict or None. All structural constraints are validated, never
    assumed.
    """
    if page_end is None:
        page_end = len(buf)
    try:
        plen, roff = varint(buf, cell_start)
        rid, roff2 = varint(buf, roff)
    except ValueError:
        return None
    if plen <= 0 or plen > (1 << 31):
        return None
    if plen <= usable - 35:
        # fully local record
        payload_end = roff2 + plen
        if payload_end > page_end or payload_end > len(buf):
            return None
        rec = parse_record(buf, roff2, payload_end, text_enc, repair=repair, pick=pick)
        if rec is None:
            return None
        values, kinds, rend, rep = rec
        if rend != payload_end:
            return None
        return {"rowid": rid, "values": values, "kinds": kinds,
                "cell_start": cell_start, "cell_end": payload_end,
                "payload_len": plen, "repairs": rep}
    # overflow: local prefix + 4-byte chain pointer; reassemble then parse
    try:
        payload, local = read_payload(buf, roff2, plen, usable, page_size)
    except ValueError:
        return None
    tmp = bytearray(payload)
    rec = parse_record(tmp, 0, plen, text_enc, repair=repair, pick=pick)
    if rec is None:
        return None
    values, kinds, rend, rep = rec
    if rend != plen:
        return None
    if rep:
        rep = {roff2 + a: (x, y) for a, (x, y) in rep.items()}
    return {"rowid": rid, "values": values, "kinds": kinds,
            "cell_start": cell_start, "cell_end": roff2 + local + 4,
            "payload_len": plen, "repairs": rep}


def walk_btree(buf, page_no, page_size, usable, text_enc, repair, out_rows,
               log, pick=None, patches=None, visited=None):
    """Walk a table b-tree, appending decoded leaf rows to out_rows.

    When `patches` (dict offset -> new byte) is provided, inferred structural
    repairs -- currently: a content_start that is inconsistent with the cell
    offsets -- are recorded in it, and a NOTE is logged.  content_start is a
    hint for decoding, but SQLite itself will not open a page whose
    content_start lies above its cells, so the inference is needed to build an
    engine-openable repair manifest.
    """
    if visited is None:
        visited = set()
    if page_no in visited or page_no < 1:
        return
    visited.add(page_no)
    page_start = (page_no - 1) * page_size
    hdr_off = 100 if page_no == 1 else page_start  # page 1 carries the file header
    if hdr_off + 8 > len(buf):
        log.append("page %d: header past EOF" % page_no)
        return
    ptype = buf[hdr_off]
    if ptype not in (2, 5, 10, 13):
        log.append("page %d: unknown page type %d, skipped" % (page_no, ptype))
        return
    ncell = BE16(buf, hdr_off + 3)
    if ncell == 0:
        return
    is_interior = ptype in (2, 5)
    ptr_off = hdr_off + (12 if is_interior else 8)
    # content_start is a *hint*, not a trust boundary: a damaged content_start
    # must never cause us to reject valid cells, and healthy ones are merely
    # cross-checked below.
    content_start = BE16(buf, hdr_off + 5)
    min_cell = page_start + (100 if page_no == 1 else 8)
    cells = []
    for i in range(ncell):
        if ptr_off + 2 * i + 2 > page_start + page_size:
            log.append("page %d: cell pointer array overruns page" % page_no)
            break
        co = BE16(buf, ptr_off + 2 * i)
        cabs = page_start + co
        if not (min_cell <= cabs < page_start + page_size):
            log.append("page %d: cell %d pointer 0x%04x outside page" % (page_no, i, co))
            continue
        cells.append(cabs)
    # content_start sanity: a healthy page has every cell at offset >= its
    # content_start.  If the smallest cell sits *above* content_start, the
    # field was corrupted upward; the tightest valid repair is the smallest
    # cell offset.  The decode guard only REJECTS pointers into zeroed or
    # unparseable regions (e.g. a pointer landing in empty padding); it does
    # not prove the pointer is genuine -- a flipped pointer landing in stale
    # record bytes (freeblock/fragment debris is not zeroed after deletes)
    # can still pass, so treat the inference as evidence, not proof.  Cells
    # are validated independently, so a false patch never corrupts recovered
    # rows; it only makes the engine-verify attempt fail, which the
    # verify_with_sqlite.py --search oracle resolves.
    if patches is not None and cells:
        min_off = min(cells)
        if content_start > min_off - page_start:
            plausible = False
            if ptype == 13:
                plausible = decode_leaf_cell(buf, min_off, usable, page_size,
                                             text_enc, repair,
                                             page_end=page_start + page_size) is not None
            elif min_off + 4 <= page_start + page_size:
                ch = BE32(buf, min_off)
                plausible = 1 <= ch <= max(1, len(buf) // page_size)
            if plausible:
                repaired = min_off - page_start
                for k in range(2):
                    pos = hdr_off + 5 + k
                    want = (repaired >> (8 * (1 - k))) & 0xFF
                    if buf[pos] != want:
                        patches[pos] = want
                log.append("page %d: content_start 0x%04x inconsistent with cells "
                           "(min cell at 0x%04x); inferred repair 0x%04x"
                           % (page_no, content_start, repaired, repaired))
    if ptype == 13:  # leaf table
        for cabs in cells:
            c = decode_leaf_cell(buf, cabs, usable, page_size, text_enc, repair,
                                 page_end=page_start + page_size, pick=pick)
            if c is None:
                log.append("page %d: cell @0x%04x failed exact decode"
                           % (page_no, cabs - page_start))
                continue
            out_rows.append(c)
    elif ptype == 5:  # interior table
        for cabs in cells:
            if cabs + 4 <= page_start + page_size:
                child = BE32(buf, cabs)
                walk_btree(buf, child, page_size, usable, text_enc, repair,
                           out_rows, log, pick, patches, visited)
        rp = BE32(buf, hdr_off + 8)
        walk_btree(buf, rp, page_size, usable, text_enc, repair,
                   out_rows, log, pick, patches, visited)


def parse_header(buf, forced_ps=None):
    if buf[:16] != b"SQLite format 3\x00":
        raise ValueError("not a SQLite database file (bad magic)")
    if forced_ps is not None:
        ps = forced_ps
    else:
        ps = BE16(buf, 16)
        if ps == 1:
            ps = 65536
    reserved = buf[20]
    pages = BE32(buf, 28)
    enc = BE32(buf, 56)
    return {"page_size": ps, "reserved": reserved, "pages": pages,
            "encoding": {1: "utf-8", 2: "utf-16le", 3: "utf-16be"}.get(enc, "utf-8")}


CREATE_TABLE_RE = re.compile(
    r"(?is)^\s*create\s+table\s+(?:if\s+not\s+exists\s+)?[`\"\[]?([\w$]+)[`\"\]]?\s*\((.*)\)\s*;?\s*$")
SQL_STARTS_CREATE = re.compile(r"(?is)^\s*create\s+\w+")


def split_columns(s):
    cols, depth, cur, quote = [], 0, "", None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'`":
            quote = ch
            cur += ch
        elif ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            cols.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        cols.append(cur.strip())
    return [c for c in cols if c]


def parse_create_table(sql):
    m = CREATE_TABLE_RE.match(sql)
    if not m:
        return None
    name, body = m.group(1), m.group(2)
    cols = []
    for c in split_columns(body):
        c = c.strip()
        if not c or c.lower().startswith(
                ("primary", "unique", "check", "foreign", "constraint", "without")):
            continue
        m2 = re.match(r"[`\"\[]?([\w$]+)[`\"\]]?\s*(.*)", c)
        if m2:
            decl = m2.group(2).strip().upper()
            # rowid alias: a column declared INTEGER PRIMARY KEY (and not a
            # WITHOUT ROWID table) stores NULL in-record; its value is the
            # cell's rowid varint.
            ipk = bool(re.search(r"\bINTEGER\b", decl)
                       and re.search(r"\bPRIMARY\s+KEY\b", decl)
                       and "WITHOUT ROWID" not in sql.upper())
            cols.append((m2.group(1), decl, ipk))
    return {"name": name, "columns": cols}


def schema_row_pick(max_page):
    """Pick the most plausible sqlite_master record among repair candidates.

    sqlite_master rows are invariantly 5 values of shape
    [text, text, text, int, text]; the last (sql) starts with CREATE and, for
    tables, parses as CREATE TABLE; rootpage is a small non-negative integer.
    """
    def pick(cands):
        scored = []
        for values, kinds, q, repairs in cands:
            if len(values) != 5 or kinds != ["text", "text", "text", "int", "text"]:
                continue
            if not isinstance(values[4], str):
                continue
            score = 0
            if SQL_STARTS_CREATE.match(values[4]):
                score += 8
            if parse_create_table(values[4]) is not None:
                score += 8
            if isinstance(values[3], int) and 0 <= values[3] <= max(1, max_page):
                score += 4
            elif isinstance(values[3], int) and 0 <= values[3] < (1 << 31):
                score += 1
            if values[0] in ("table", "index", "view", "trigger"):
                score += 2
            nrep = len(repairs) if repairs else 0
            scored.append((score, -nrep, -_text_score(values, kinds), values, kinds, q, repairs))
        if not scored:
            return None
        scored.sort(key=lambda s: s[:3], reverse=True)
        values, kinds, q, repairs = scored[0][3], scored[0][4], scored[0][5], scored[0][6]
        return values, kinds, q, repairs
    return pick


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dbfile")
    ap.add_argument("--out", default=None)
    ap.add_argument("--out-patches", default=None,
                    help="write repair manifest {""offset"": newbyte, ...} here "
                         "(all record-header repairs plus inferred content_start "
                         "fixes; feed it to verify_with_sqlite.py)")
    ap.add_argument("--columns", default=None, help="fallback column names")
    ap.add_argument("--tables", default=None)
    ap.add_argument("--key-regex", default=None, help="col:regexp validation")
    ap.add_argument("--carve", action="store_true")
    ap.add_argument("--repair-bits", action="store_true")
    ap.add_argument("--page-size", type=int, default=None)
    ap.add_argument("--schema-only", action="store_true")
    args = ap.parse_args()

    buf = bytearray(open(args.dbfile, "rb").read())
    log = []
    try:
        hdr = parse_header(buf, args.page_size)
    except ValueError as e:
        print("WARNING: %s" % e, file=sys.stderr)
        best = None
        for cand in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
            if len(buf) > 108 and buf[100] in (2, 5, 10, 13):
                best = cand
                break
        if best is None:
            sys.exit(2)
        hdr = {"page_size": best, "reserved": 0, "pages": len(buf) // best,
               "encoding": "utf-8"}
        print("WARNING: assuming page size %d" % best, file=sys.stderr)
    ps, reserved, text_enc = hdr["page_size"], hdr["reserved"], hdr["encoding"]
    usable = ps - reserved
    max_page = max(1, len(buf) // ps)
    print("page_size=%d usable=%d declared_pages=%d encoding=%s file_bytes=%d" %
          (ps, usable, hdr["pages"], text_enc, len(buf)), file=sys.stderr)

    repair = args.repair_bits
    patches = {}  # absolute offset -> new byte, for the repair manifest

    # --- 1. recover schema from page 1's sqlite_master b-tree ---------------
    schema_rows = []
    walk_btree(buf, 1, ps, usable, text_enc, repair, schema_rows, log,
               pick=schema_row_pick(max_page), patches=patches)
    for r in schema_rows:
        if r["repairs"]:
            log.append("schema cell @0x%x: repaired byte(s) %s" %
                       (r["cell_start"],
                        {hex(a): (hex(x), hex(y)) for a, (x, y) in r["repairs"].items()}))
            patches.update({a: y for a, (x, y) in r["repairs"].items()})
    tables = []
    for r in schema_rows:
        v = r["values"]
        if len(v) == 5 and isinstance(v[0], str) and v[0] == "table" \
                and isinstance(v[1], str) and not v[1].startswith("sqlite_") \
                and isinstance(v[4], str):
            parsed = parse_create_table(v[4])
            if parsed is None:
                log.append("schema row %r: sql does not parse as CREATE TABLE" % (v[1],))
                continue
            if isinstance(v[3], int):
                tables.append({"name": parsed["name"], "rootpage": v[3], "sql": v[4],
                               "columns": parsed["columns"]})
    if args.tables:
        want = set(args.tables.split(","))
        tables = [t for t in tables if t["name"] in want]
    if not tables and args.columns:
        tables.append({"name": "data", "rootpage": None, "sql": "",
                       "columns": [(c.strip(), "", False)
                                   for c in args.columns.split(",")]})
    if args.schema_only:
        print(json.dumps([{"name": t["name"], "rootpage": t["rootpage"],
                           "sql": t["sql"], "columns": t["columns"]} for t in tables],
                         indent=2))
        return

    key_re = None
    if args.key_regex:
        col, _, pat = args.key_regex.partition(":")
        key_re = (col, re.compile(pat))

    def data_pick(cols):
        def pick(cands):
            scored = []
            for values, kinds, q, repairs in cands:
                if len(values) != len(cols):
                    continue
                nrep = len(repairs) if repairs else 0
                # exact parses (nrep == 0) must always beat repaired ones
                scored.append((nrep, -_text_score(values, kinds),
                               values, kinds, q, repairs))
            if not scored:
                return None
            scored.sort(key=lambda s: (s[0], s[1]))
            values, kinds, q, repairs = scored[0][2], scored[0][3], scored[0][4], scored[0][5]
            return values, kinds, q, repairs
        return pick

    results = {}
    for t in tables:
        cols = [c[0] for c in t["columns"]]
        rows = []
        if t["rootpage"] is not None and 0 < t["rootpage"] <= max_page + 1:
            walk_btree(buf, t["rootpage"], ps, usable, text_enc, repair, rows, log,
                       pick=data_pick(cols), patches=patches)
        seen, out = set(), []
        for r in rows:
            v = r["values"]
            if len(v) != len(cols):
                log.append("table %s: %d-value record does not match %d columns; "
                           "dropped" % (t["name"], len(v), len(cols)))
                continue
            d = dict(zip(cols, v))
            # INTEGER PRIMARY KEY columns store NULL in-record; the true value
            # is the cell's rowid -- repopulate it for faithful output.
            for col, decl, ipk in t["columns"]:
                if ipk and d.get(col) is None:
                    d[col] = r["rowid"]
            if key_re is not None:
                col, re_ = key_re
                if col not in d or not isinstance(d[col], str) or not re_.match(d[col]):
                    continue
            k = tuple(repr(x) for x in d.items())
            if k in seen:
                continue
            seen.add(k)
            if r["repairs"]:
                log.append("table %s: repaired byte(s) %s in cell @0x%x" %
                           (t["name"], {hex(a): (hex(x), hex(y)) for a, (x, y) in r["repairs"].items()},
                            r["cell_start"]))
                patches.update({a: y for a, (x, y) in r["repairs"].items()})
            d["_rowid"] = r["rowid"]
            out.append(d)
        out.sort(key=lambda x: x["_rowid"])
        for d in out:
            d.pop("_rowid", None)
        results[t["name"]] = out

    # --- 2. carving fallback ---------------------------------------------------
    if args.carve:
        carved = []
        for off in range(0, len(buf) - 8):
            c = decode_leaf_cell(buf, off, usable, ps, text_enc, repair)
            if c is None:
                continue
            v = c["values"]
            txts = [x for x, k in zip(v, c["kinds"]) if k == "text"]
            if not txts:
                continue
            if key_re is not None and not key_re[1].match(txts[0]):
                continue
            if c["repairs"]:
                log.append("carve: repaired cell @0x%x" % off)
                patches.update({a: y for a, (x, y) in c["repairs"].items()})
            carved.append((txts[0], v, c["kinds"]))
        for t in tables:
            cols = [c[0] for c in t["columns"]]
            # carved cells have no rowid (INTEGER PRIMARY KEY stays None), so
            # dedup on the non-IPK columns only, or structural+carved copies
            # of the same row would both be emitted.
            dedup_cols = [c[0] for c in t["columns"] if not c[2]] or cols
            known = {tuple(d[c] for c in dedup_cols if c in d)
                     for d in results.get(t["name"], [])}
            for key, v, kinds in carved:
                if len(v) != len(cols):
                    continue
                d = dict(zip(cols, v))
                # rowid is not kept for carved cells; INTEGER PRIMARY KEY
                # columns stay NULL here (carve is the schema-loss fallback)
                if key_re is not None:
                    col, re_ = key_re
                    if col not in d or not isinstance(d[col], str) or not re_.match(d[col]):
                        continue
                if tuple(d[c] for c in dedup_cols) in known:
                    continue
                known.add(tuple(d[c] for c in dedup_cols))
                results.setdefault(t["name"], []).append(d)

    # --- 3. emit ---------------------------------------------------------------
    payload = []
    for t in tables:
        for d in results.get(t["name"], []):
            outd = {}
            for k, val in d.items():
                if isinstance(val, bytes):
                    outd[k] = {"$blob_b64": base64.b64encode(val).decode()}
                else:
                    outd[k] = val
            payload.append(outd)
    payload.sort(key=lambda d: next((v for v in d.values() if isinstance(v, str)), ""))

    for line in log:
        print("NOTE: " + line, file=sys.stderr)
    print("Recovered %d row(s) from %d table(s): %s" %
          (len(payload), len(tables), ", ".join(t["name"] for t in tables)),
          file=sys.stderr)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    if args.out_patches:
        with open(args.out_patches, "w") as f:
            json.dump({str(o): v for o, v in sorted(patches.items())}, f, indent=1)
        print("Repair manifest (%d byte(s)) written to %s" % (len(patches), args.out_patches),
              file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()