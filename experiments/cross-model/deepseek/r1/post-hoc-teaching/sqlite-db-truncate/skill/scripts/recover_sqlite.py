#!/usr/bin/env python3
"""
Tolerant recovery of logically valid rows from damaged SQLite storage.

Pure-Python (stdlib only) parser that:
  * parses the SQLite file header (page size, reserved space, page count,
    freelist, text encoding)
  * walks b-tree pages (leaf/interior, table/index) via cell pointers
  * decodes record payloads: varints, serial types, NULL/int/float/text/blob
  * follows overflow page chains for records that cross page boundaries
  * supports BOTH rowid tables (leaf-table cells carry a rowid varint) and
    WITHOUT ROWID tables (index b-trees, cells carry no rowid)
  * decodes TEXT per the header's text encoding (UTF-8 / UTF-16le / BE) with
    a byte-order fallback when the declared order yields garbage
  * tolerates corruption:
      - single-bit (and some two-bit) flips in serial-type bytes are repaired
        by re-checking declared vs consumed payload length
      - malformed cells are skipped; a byte-level record scan (both cell
        layouts) rescues rows whose cell pointers / page headers were
        destroyed
      - truncated files: only pages physically present are parsed
  * maps recovered columns to names parsed from CREATE TABLE (sqlite_master)
  * restores INTEGER PRIMARY KEY values from rowids (SQLite stores NULL in
    the record for a rowid-alias column)
  * serializes rows as a JSON list of objects (case-specific public schema)

Usage:
  python3 recover_sqlite.py DB [RECOVER.json] [--columns a,b,c] [--lenient]
  python3 recover_sqlite.py DB --inspect         # page/cell diagnostics only
  python3 recover_sqlite.py DB --probe           # header diagnostics only

The output schema mirrors the table's column order.  Integers come out as
JSON numbers, floats as JSON numbers, NULL as null, TEXT as string.
BLOBs are emitted as hex strings prefixed with "0x".

Tuning flags:
  --columns a,b,c   column names to use when sqlite_master is unreadable
                    (or to override parsed names)
  --lenient         accept records whose text/blob fields are truncated by
                    damage and end exactly at the available payload
  --min-text n      minimum visible-character ratio (0..1) required to
                    accept a scanned record's text column (default 0.7)
"""
import argparse
import json
import re
import struct
import sys

MAGIC = b"SQLite format 3\x00"
PAGE_HEADER_TYPES = {2: "interior-index", 5: "interior-table", 10: "leaf-index", 13: "leaf-table"}
ENCODINGS = {1: "utf-8", 2: "utf-16-le", 3: "utf-16-be"}


def read_varint(buf, off):
    """SQLite varint: 1..9 bytes, big-endian 7-bit groups."""
    v = 0
    for i in range(9):
        if off + i >= len(buf):
            return None, off + i
        b = buf[off + i]
        if i == 8:
            v = (v << 8) | b
        else:
            v = (v << 7) | (b & 0x7F)
        if not (b & 0x80):
            return v, off + i + 1
    return None, off + 9


def serial_type_size(t):
    """Byte size of the value implied by a record serial type.
    Types: 1=int8(1), 2=int16(2), 3=int24(3), 4=int32(4), 5=int48(6),
    6=int64(8), 7=float64(8), 8=zero(0), 9=one(0), >=12 blob/text.
    Lengths count BYTES, which is encoding-independent."""
    if t <= 0:
        return 0
    if t in (1, 2, 3, 4):
        return t
    if t == 5:
        return 6
    if t == 6:
        return 8
    if t == 7:
        return 8
    if t in (8, 9):       # zero / one: zero bytes of content
        return 0
    if t in (10, 11):     # reserved
        return 0
    return (t - 12) // 2  # blob (even) / text (odd)


def decode_text(raw, codec):
    """Decode text bytes with the given codec; strip a leading BOM."""
    try:
        s = raw.decode(codec)
    except (UnicodeDecodeError, LookupError):
        return None
    if s.startswith("\ufeff"):
        s = s[1:]
    return s


def decode_value(serial, data, off, lenient, codec="utf-8"):
    """
    Decode one value from data[off:].  Returns (value, next_off) or
    (None, off) on failure.  NOTE: serial 0 (NULL) is handled by the
    caller; a failed decode also returns None.
    """
    t = serial
    n = serial_type_size(t)
    if off + n > len(data):
        if lenient and t >= 12:
            n = len(data) - off
            if n < 0:
                return None, off
        else:
            return None, off
    if t == 1:
        return struct.unpack(">b", data[off:off + 1])[0], off + 1
    if t == 2:
        return struct.unpack(">h", data[off:off + 2])[0], off + 2
    if t == 3:
        b = data[off:off + 3]
        v = int.from_bytes(b, "big")
        if v & 0x800000:
            v -= 1 << 24
        return v, off + 3
    if t == 4:
        return struct.unpack(">i", data[off:off + 4])[0], off + 4
    if t == 5:
        b = data[off:off + 6]
        v = int.from_bytes(b, "big")
        if v & (1 << 47):
            v -= 1 << 48
        return v, off + 6
    if t == 6:
        return struct.unpack(">q", data[off:off + 8])[0], off + 8
    if t == 7:
        return struct.unpack(">d", data[off:off + 8])[0], off + 8
    if t == 8:
        return 0, off
    if t == 9:
        return 1, off
    if t >= 12:
        n = (t - 12) // 2
        raw = data[off:off + n]
        if t % 2 == 0:  # blob
            return "0x" + raw.hex(), off + n
        s = decode_text(raw, codec)
        if s is None:
            return None, off
        return s, off + n
    return None, off


def printable_ratio(s):
    """Fraction of characters that are visible text (ASCII printable or
    non-ASCII); control bytes and replacement chars count as bad."""
    if not s:
        return 1.0
    good = 0
    for c in s:
        o = ord(c)
        if 32 <= o < 127:
            good += 1
        elif o >= 128 and c != "\ufffd":
            good += 1
        elif o in (9, 10, 13):
            good += 1
    return good / len(s)


def parse_record(payload, min_text_ratio=0.7, allow_clamp=False, codec="utf-8"):
    """
    Parse a record payload (header varint + serial types + values).
    Returns dict(ok, values, serials, fixed) or None on hard failure.
    Tolerates one-bit (and some two-bit) flips in serial-type bytes by
    requiring exact payload-length consumption.
    """
    if not payload:
        return None
    hsz, _ = read_varint(payload, 0)
    if hsz is None or hsz < 1 or hsz > len(payload):
        return None
    types = []
    pos = 1
    while pos < hsz:
        t, npos = read_varint(payload, pos)
        if t is None or npos > hsz:
            return None
        types.append(t)
        pos = npos
    if pos != hsz:
        return None
    # cap: real task records never have hundreds of columns; this also
    # bounds the O(n^2) repair passes when scanning garbage offsets
    if len(types) > 64:
        return None
    expected = len(payload) - hsz
    total = sum(serial_type_size(t) for t in types)
    fixed = None
    if total != expected:
        # ---- tolerant repair: single-bit flips in one serial-type byte ----
        for i in range(len(types)):
            if not 12 <= types[i] <= 250:
                continue
            orig = types[i]
            for delta in (1, 2, 4, 8, 16, 32, 64, 128, 1, -1, 2, -2):
                cand = (orig ^ delta) if delta in (1, 2, 4, 8, 16, 32, 64, 128) else orig + delta
                if cand < 13:
                    continue
                ntotal = total - serial_type_size(orig) + serial_type_size(cand)
                if ntotal == expected:
                    types[i] = cand
                    fixed = (i, orig, cand)
                    total = ntotal
                    break
            if fixed:
                break
        # ---- two-bit fix pass (two flipped serial bytes); only for
        #      small records to keep the O(n^2) cost under control ----
        if total != expected and len(types) <= 16:
            for i in range(len(types)):
                for j in range(i + 1, len(types)):
                    if not (12 <= types[i] <= 250 and 12 <= types[j] <= 250):
                        continue
                    oi, oj = types[i], types[j]
                    for bi in (1, 2, 4, 8, 16, 32, 64, 128):
                        for bj in (1, 2, 4, 8, 16, 32, 64, 128):
                            ci, cj = oi ^ bi, oj ^ bj
                            if ci < 13 or cj < 13:
                                continue
                            ntotal = (total - serial_type_size(oi) - serial_type_size(oj)
                                      + serial_type_size(ci) + serial_type_size(cj))
                            if ntotal == expected:
                                types[i], types[j] = ci, cj
                                fixed = (i, oi, ci)
                                total = ntotal
                                break
                        if total == expected:
                            break
                    if total == expected:
                        break
                if total == expected:
                    break
        if total != expected:
            return None
    values = []
    o = hsz
    ok = True
    for t in types:
        if t == 0:
            values.append(None)
            continue
        v, o = decode_value(t, payload, o, allow_clamp, codec)
        if v is None:
            ok = False
            break
        values.append(v)
    if not ok or o != len(payload):
        return None
    # sanity: at least one TEXT-typed value should look like text
    # (blob values are hex strings and must NOT count as text)
    txts = [v for v, t in zip(values, types) if t % 2 == 1 and t >= 13 and isinstance(v, str)]
    if txts and not any(printable_ratio(v) >= min_text_ratio for v in txts):
        return None
    return {"ok": True, "values": values, "serials": types, "fixed": fixed}


def ascii_ratio(s):
    """Fraction of chars that are ASCII-printable (32..126) or whitespace.
    Real SQLite UTF-16 text (keys, SQL DDL) is ASCII-dominant; UTF-16
    mis-decodes of arbitrary bytes produce high-Unicode garbage."""
    if not s:
        return 1.0
    good = sum(1 for c in s if 32 <= ord(c) < 127 or ord(c) in (9, 10, 13))
    return good / len(s)


def text_values(values, serials):
    """Values whose serial type is TEXT (odd, >= 13)."""
    return [v for v, t in zip(values, serials)
            if t % 2 == 1 and t >= 13 and isinstance(v, str)]


# ================= fragment reassembly ("split fragments") =================
# A fragment artifact arrives as several byte-range pieces: page-shuffled,
# page-dropped, or cut mid-page.  Reassembly applies the same validation
# discipline used for overflow chains over a SPACE OF ASSEMBLIES: a
# candidate assembly is trusted only when its pointer graph resolves to
# physically present pages with sane b-tree headers and parseable cells.

PAGE_SIZE_HINTS = (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)


def sane_page_header(pg, page_size):
    """(ok, type): a plausible b-tree page header (type in {2,5,10,13},
    sane cell count / content start / fragment byte)."""
    if len(pg) < 12:
        return False, 0
    typ = pg[0]
    if typ not in (2, 5, 10, 13):
        return False, typ
    ncell = int.from_bytes(pg[3:5], "big")
    if ncell * 2 + 12 > page_size:
        return False, typ
    cstart = int.from_bytes(pg[5:7], "big")
    if not 0 < cstart <= page_size:
        return False, typ
    return True, typ


def walk_score(data, page_size=None):
    """How 'walkable' an assembled buffer is: rows recovered by the plain
    tree walk (no scan), reachable pages with sane headers.  Returns
    (score, rows, reachable, headers_ok)."""
    try:
        r = SQLiteReader(data)
        if page_size is not None and r.page_size != page_size:
            return -1, 0, 0, 0
        tables = r.recover_tables()
        rows = 0
        reachable = set()
        for t in tables:
            rows += len(t["rows"])
            reachable |= t.get("pages") or set()
        headers_ok = 0
        for n in range(2, r.file_pages + 1):
            h = r.page_header(n)
            if h is not None and h["type"] in (2, 5, 10, 13):
                headers_ok += 1
        return (rows * 10000 + len(reachable) * 100 + headers_ok, rows,
                len(reachable), headers_ok)
    except Exception:
        return -1, 0, 0, 0


def find_magic_piece(pieces):
    """Index of the piece whose bytes START with the SQLite magic, or
    (None, None) if none does."""
    for i, b in enumerate(pieces):
        if b.startswith(MAGIC) and len(b) >= 100:
            return i, int.from_bytes(b[16:18], "big")
    # also allow a piece that begins mid-page but contains the magic inside:
    return None, None


def missing_pages(data):
    """Page numbers referenced by the pointer graph but absent from the
    file (used in reassembly reports; absent => truncation semantics)."""
    try:
        r = SQLiteReader(data)
        refs = set()
        for n in range(2, r.file_pages + 1):
            h = r.page_header(n)
            if h is None or h["type"] not in (2, 5):
                continue
            pg = h["bytes"]
            for p in h["ptrs"]:
                ch = int.from_bytes(pg[p:p + 4], "big")
                if ch:
                    refs.add(ch)
            if h["right_child"]:
                refs.add(h["right_child"])
        return sorted(p for p in refs if p > r.file_pages)
    except Exception:
        return []


def reassemble_pieces(pieces):
    """
    Given the bytes of each artifact piece (in any order), rebuild the best
    candidate database buffer.

    Strategy: concatenations/orderings are the candidate space; the piece
    holding the magic anchors page 1 and fixes page_size; every candidate is
    scored by its pointer-graph walkability (sane headers + parsed cells),
    and the best wins.  A missing chunk simply leaves pages absent
    (truncation semantics, reported).  Returns (data|None, report).
    """
    report = {"pieces": len(pieces),
              "lens": [len(p) for p in pieces],
              "orders_tried": 0, "best_score": -1, "missing": set()}
    mp, ps = find_magic_piece(pieces)
    if mp is None:
        report["error"] = "no piece starts with the SQLite header magic; " \
                          "cannot anchor page 1"
        return None, report
    if ps == 1:
        ps = 65536
    report["page_size"] = ps
    rest = [b for i, b in enumerate(pieces) if i != mp]
    first = pieces[mp]
    candidates = []
    # candidate 1..k: piece permutations (page-aligned assumption).  For
    # mid-page-cut pieces (lengths not multiples of ps) permutations are
    # meaningless except the given order, but scoring decides.
    import itertools
    for order in itertools.permutations(range(len(rest))):
        data = first + b"".join(rest[i] for i in order)
        candidates.append(data)
    # also the as-given concatenation (covers in-order mid-page cuts)
    candidates.append(b"".join(pieces))
    best = None
    seen = set()
    for data in candidates:
        if data in seen:
            continue
        seen.add(data)
        report["orders_tried"] += 1
        score, rows, reach, hok = walk_score(data, ps)
        if score > report["best_score"]:
            report["best_score"] = score
            report["rows"] = rows
            report["reachable_pages"] = reach
            report["headers_ok"] = hok
            best = data
    if best is None or report["best_score"] < 0:
        report["error"] = "no ordering produced a walkable database"
        return None, report
    report["missing"] = missing_pages(best)
    return best, report


def reassemble_single(data):
    """
    Single buffer whose page-sized chunks were shuffled (whole pages,
    page-aligned chunk boundaries, magic at some grid offset).  Every
    page-size window of the buffer is a real physical page; rebuild via
    page-bag backtracking: slot 1 <- the magic page; every slot referenced
    by an assigned interior page is filled from the remaining physical
    pages, constrained by header sanity and sqlite_master root types;
    referenced slots that cannot be filled stay empty (missing pages,
    truncation semantics, reported).  Returns (data|None, report).
    """
    import sys as _sys
    report = {"orders_tried": 0, "best_score": -1}
    magic_offsets = [0, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]
    for m in magic_offsets:
        if m + 100 > len(data) or data[m:m + 16] != MAGIC:
            continue
        ps = int.from_bytes(data[m + 16:m + 18], "big")
        if ps == 1:
            ps = 65536
        if m % ps != 0:
            continue
        if len(data) % ps != 0:
            continue
        blocks = [data[i * ps:(i + 1) * ps] for i in range(len(data) // ps)]
        if len(blocks) < 2:
            continue
        if len(blocks) > 16:
            continue
        report["page_size"] = ps
        _sys.setrecursionlimit(20000)
        impl = _page_bag_dfs(blocks, ps, m // ps)
        if impl:
            score, rows, reach, hok = walk_score(impl, ps)
            report["orders_tried"] = 1
            report["best_score"] = score
            report["rows"] = rows
            report["reachable_pages"] = reach
            report["headers_ok"] = hok
            report["missing"] = missing_pages(impl)
            return impl, report
    report["error"] = "no grid-aligned magic / no resolvable page-bag " \
                      "ordering"
    return None, report


def _page_bag_dfs(blocks, ps, magic_bi):
    """
    Backtracking assignment of physical page blocks to slots 1..S.
    S starts at len(blocks) and grows whenever a reference exceeds it
    (dropped pages become empty slots => missing-page semantics).
    Returns the best assembled buffer or None.
    """
    n = len(blocks)
    slot = [None] * (n + 2)      # slot -> block index (grows on demand)
    used = [False] * n
    best = [None]
    best_score = [-1]
    nodes = [0]
    MAX_NODES = 200000

    def block_sane(i):
        return sane_page_header(blocks[i], ps)[0]

    def refs_of(slot_idx):
        pg = blocks[slot[slot_idx]]
        typ = pg[0]
        if typ not in (2, 5):
            return []
        ncell = int.from_bytes(pg[3:5], "big")
        ncell = min(ncell, (len(pg) - 12) // 2)
        out = []
        for i in range(ncell):
            p = int.from_bytes(pg[12 + 2 * i:14 + 2 * i], "big")
            ch = int.from_bytes(pg[p:p + 4], "big")
            if ch:
                out.append(ch)
        rc = int.from_bytes(pg[8:12], "big")
        if rc:
            out.append(rc)
        return out

    def assemble():
        S = max(len([s for s in slot if s is not None]),
                max((s for s in range(len(slot)) if slot[s] is not None), default=1))
        buf = bytearray(ps * S)
        for s in range(1, S + 1):
            if slot[s] is not None:
                buf[(s - 1) * ps:s * ps] = blocks[slot[s]]
        return bytes(buf)

    def dfs(assigned_refs):
        nodes[0] += 1
        if nodes[0] > MAX_NODES:
            return
        todo = sorted(s for s in assigned_refs if slot[s] is None)
        if todo:
            s = todo[0]
            if s >= len(slot):
                slot.extend([None] * (s - len(slot) + 1))
            for bi in range(n):
                if used[bi] or not block_sane(bi):
                    continue
                if s == 1 and bi != magic_bi:
                    continue   # slot 1 is the magic page
                used[bi] = True
                slot[s] = bi
                new_refs = set(assigned_refs)
                new_refs.add(s)
                if blocks[bi][0] in (2, 5):
                    new_refs |= {r for r in refs_of(s) if r >= 1}
                dfs(new_refs)
                slot[s] = None
                used[bi] = False
            return
        # all referenced slots resolved: fill empty low slots with the
        # remaining sane blocks (unreferenced tails), then score
        filled = []
        empty = [s for s in range(1, len(slot)) if slot[s] is None]
        free = [bi for bi in range(n) if not used[bi] and block_sane(bi)]
        for s in empty:
            if not free:
                break
            bi = free.pop(0)
            used[bi] = True
            slot[s] = bi
            filled.append(s)
        buf = assemble()
        score, rows, reach, hok = walk_score(buf, ps)
        if score > best_score[0]:
            best_score[0] = score
            best[0] = buf
        for s in filled:
            used[slot[s]] = False
            slot[s] = None

    slot[1] = magic_bi
    used[magic_bi] = True
    refs = set()
    try:
        r0 = SQLiteReader(blocks[magic_bi], source_name="<page1>")
        for stype, name, tbl, root, sql in r0.read_schema():
            if stype == "table" and isinstance(root, int) and root >= 2:
                refs.add(root)
    except Exception:
        pass
    dfs(refs)
    return best[0]


class SQLiteReader:
    def __init__(self, source, min_text_ratio=0.7, lenient=False, source_name=None):
        """source: file path (str) or already-read bytes (e.g. a
        reassembled fragment set)."""
        if isinstance(source, (bytes, bytearray)):
            self.data = bytes(source)
            self.path = source_name or "<reassembled>"
        else:
            self.path = source
            self.data = open(source, "rb").read()
        self.lenient = lenient
        self.min_text_ratio = min_text_ratio
        if not self.data.startswith(MAGIC):
            raise ValueError("not a SQLite database (bad magic) — "
                             "if this artifact is a fragment set, run with "
                             "--pieces FILE1 FILE2 ... or feed a reassembled "
                             "buffer; see SKILL.md 'Split fragments'")
        self.page_size = int.from_bytes(self.data[16:18], "big")
        if self.page_size == 1:
            self.page_size = 65536
        self.reserved = self.data[20] if len(self.data) > 20 else 0
        self.usable = max(self.page_size - self.reserved, 0)
        self.page_count_hdr = int.from_bytes(self.data[28:32], "big")
        self.freelist_trunk = int.from_bytes(self.data[32:36], "big")
        self.freelist_count = int.from_bytes(self.data[36:40], "big")
        self.encoding = int.from_bytes(self.data[56:60], "big")
        self.codec = ENCODINGS.get(self.encoding, "utf-8")
        # byte-order fallbacks: declared first, then the swapped flavor,
        # then utf-8 (covers a bit-flipped header encoding field)
        if self.codec == "utf-8":
            self.codec_candidates = ["utf-8", "utf-16-le", "utf-16-be"]
        elif self.codec == "utf-16-le":
            self.codec_candidates = ["utf-16-le", "utf-16-be", "utf-8"]
        else:
            self.codec_candidates = ["utf-16-be", "utf-16-le", "utf-8"]
        self.file_pages = (len(self.data) + self.page_size - 1) // self.page_size
        # NOTE: ceil, not floor — a file truncated MID-page still carries a
        # partial last page whose records (cells stored low in the page) are
        # recoverable; flooring would silently drop that page entirely.

    # ---------------- text decoding ----------------
    def parse_record_tolerant(self, payload):
        """parse_record with encoding fallback; returns (record, codec) or
        (None, None).  A fallback codec is only trusted when every TEXT
        value is ASCII-dominant (UTF-16 mis-decodes of arbitrary bytes
        yield high-Unicode garbage and are rejected)."""
        for idx, codec in enumerate(self.codec_candidates):
            r = parse_record(payload, self.min_text_ratio, self.lenient, codec)
            if r is None:
                continue
            if idx > 0:  # fallback codec: demand ASCII-dominant text
                tv = text_values(r["values"], r["serials"])
                if tv and not all(ascii_ratio(v) >= 0.8 for v in tv):
                    continue
            return r, codec
        return None, None

    # ---------------- page access ----------------
    def page(self, n):
        """n is 1-based. Returns page bytes or None when truncated/absent."""
        off = (n - 1) * self.page_size
        if off < 0 or off >= len(self.data):
            return None
        return self.data[off:off + self.page_size]

    def page_header(self, n):
        pg = self.page(n)
        if pg is None:
            return None
        hdr = 100 if n == 1 else 0
        if hdr + 8 > len(pg):
            return None
        typ = pg[hdr]
        ncell = int.from_bytes(pg[hdr + 3:hdr + 5], "big")
        # cap: a damaged ncell field must not cause oversized pointer reads
        ncell = min(ncell, max((len(pg) - hdr - 12) // 2, 0))
        cstart = int.from_bytes(pg[hdr + 5:hdr + 7], "big")
        frag = pg[hdr + 7]
        if typ in (5, 2):          # interior pages: 4-byte right-most child at hdr+8,
            pstart = hdr + 12      # cell pointer array starts at hdr+12
        else:
            pstart = hdr + 8       # leaf pages: pointer array starts at hdr+8
        ptrs = []
        for i in range(ncell):
            p = int.from_bytes(pg[pstart + 2 * i:pstart + 2 + 2 * i], "big")
            ptrs.append(p)
        right_child = int.from_bytes(pg[hdr + 8:hdr + 12], "big") if typ in (5, 2) else None
        return {"type": typ, "typename": PAGE_HEADER_TYPES.get(typ, "?"),
                "ncell": ncell, "cstart": cstart, "frag": frag,
                "ptrs": ptrs, "right_child": right_child, "hdr": hdr, "bytes": pg}

    # ---------------- overflow ----------------
    def min_local(self):
        """m = ((usable-12)*32/255)-23 (classic minimum local payload)."""
        return max(0, ((self.usable - 12) * 32 // 255) - 23)

    def local_payload_guess(self, page_type, payload_len):
        """
        Best-guess local payload size.  Table-leaf threshold M = usable-35;
        index threshold M = ((usable-12)*32/255)-23 (index min is 0).
        Verified rule at usable 4096: x = R mod (usable-4); local = x when
        m <= x <= M else m.  The caller always verifies against the
        overflow chain, so a wrong guess is repaired by pointer scanning.
        """
        U = self.usable
        if page_type == 10:  # leaf index / WITHOUT ROWID leaf
            M = max(((U - 12) * 32 // 255) - 23, 0)
            m = 0
        else:                # leaf table
            M = U - 35
            m = self.min_local()
        if payload_len <= M:
            return payload_len, False
        x = payload_len % max(U - 4, 1)
        if m <= x <= M:
            return x, True
        return m, True

    def overflow_bytes(self, pgno, needed):
        """Fetch bytes from an overflow chain (each page's first 4 bytes =
        next page number, rest is payload).  Returns None if the chain is
        too short or invalid."""
        out = bytearray()
        seen = set()
        hops = 0
        while pgno and needed > 0 and hops < 200:
            if pgno in seen or pgno < 1:
                return None
            seen.add(pgno)
            hops += 1
            pg = self.page(pgno)
            if pg is None:
                return None
            nxt = int.from_bytes(pg[0:4], "big")
            body = pg[4:self.usable]
            take = min(len(body), needed)
            out += body[:take]
            needed -= take
            pgno = nxt
        if needed > 0:
            return None
        return bytes(out)

    def cell_payload(self, pg, payload_start, payload_len, page_type):
        """
        Extract the full record payload of a cell.  Starts from the
        local-payload guess, then VERIFIES the overflow chain supplies
        exactly the remaining bytes; if the guess is wrong, scans the page
        for candidate 4-byte overflow pointers and validates each chain.
        Returns (payload, local) or (None, None).
        """
        local, has_ov = self.local_payload_guess(page_type, payload_len)
        payload = pg[payload_start:payload_start + local]
        if not has_ov:
            if len(payload) < payload_len:
                return None, None
            return payload, None
        probe_starts = [payload_start + local]
        for p in range(payload_start + 4, min(payload_start + payload_len + 8, len(pg) - 3)):
            v = int.from_bytes(pg[p:p + 4], "big")
            if 1 <= v <= max(self.file_pages, 1):
                probe_starts.append(p)
        for p in probe_starts[:1024]:
            if p + 4 > len(pg):
                continue
            ov = int.from_bytes(pg[p:p + 4], "big")
            if not 1 <= ov <= max(self.file_pages, 1):
                continue
            need = payload_len - (p - payload_start)
            if need <= 0:
                continue
            tail = self.overflow_bytes(ov, need)
            if tail is not None:
                payload = pg[payload_start:p] + tail
                if len(payload) == payload_len:
                    return payload, p - payload_start
        return None, None

    # ---------------- cells ----------------
    def parse_cell(self, n, cell_off):
        """
        Parse one cell of page n at cell_off (page-relative).
        Returns (is_table, rowid, record) or None.
        is_table True for leaf-table cells (they carry a rowid varint),
        False for leaf-index / WITHOUT ROWID cells (no rowid).
        """
        h = self.page_header(n)
        if h is None:
            return None
        pg = h["bytes"]
        typ = h["type"]
        if typ == 13:  # leaf table: [payload-len varint][rowid varint][payload]
            payload_len, o1 = read_varint(pg, cell_off)
            if payload_len is None:
                return None
            rowid, o2 = read_varint(pg, o1)
            if rowid is None or rowid < 1 or o2 > len(pg):
                return None
            payload, _ = self.cell_payload(pg, o2, payload_len, 13)
            if payload is None:
                return None
            r, _ = self.parse_record_tolerant(payload)
            if r is None:
                return None
            return (True, rowid, r)
        if typ == 10:  # leaf index / WITHOUT ROWID: [payload-len varint][payload]
            payload_len, o1 = read_varint(pg, cell_off)
            if payload_len is None or o1 > len(pg):
                return None
            payload, _ = self.cell_payload(pg, o1, payload_len, 10)
            if payload is None:
                return None
            r, _ = self.parse_record_tolerant(payload)
            if r is None:
                return None
            return (False, None, r)
        return None

    # ---------------- tree walking ----------------
    def walk_tree(self, root):
        """Yield (page_no, cell_off, is_table, rowid, record) for every leaf
        cell in the tree rooted at `root` (1-based page number)."""
        stack = [root]
        seen_pages = set()
        while stack:
            n = stack.pop()
            if n in seen_pages or n < 1:
                continue
            seen_pages.add(n)
            h = self.page_header(n)
            if h is None:
                continue
            typ = h["type"]
            if typ in (13, 10):
                for p in h["ptrs"]:
                    r = self.parse_cell(n, p)
                    if r is not None:
                        is_table, rowid, rec = r
                        yield (n, p, is_table, rowid, rec)
            elif typ in (5, 2):
                # interior table: cell = [4-byte child][key varint]
                # interior index: cell = [4-byte child][key record]
                # (both: we only need the child page number)
                for p in h["ptrs"]:
                    pg = h["bytes"]
                    child = int.from_bytes(pg[p:p + 4], "big")
                    if child:
                        stack.append(child)
                if h["right_child"]:
                    stack.append(h["right_child"])
            # unknown page type -> nothing (damaged header)

    def tree_pages(self, root):
        """All pages reachable from root, regardless of whether their
        cells parse (page ownership must not depend on parse success;
        a reachable page with destroyed cell pointers is still owned by
        the same table)."""
        pages = set()
        stack = [root]
        while stack:
            n = stack.pop()
            if n in pages or n < 1:
                continue
            pages.add(n)
            h = self.page_header(n)
            if h is None:
                continue
            if h["type"] in (5, 2):
                for p in h["ptrs"]:
                    child = int.from_bytes(h["bytes"][p:p + 4], "big")
                    if child:
                        stack.append(child)
                if h["right_child"]:
                    stack.append(h["right_child"])
        return pages

    # ---------------- sqlite_master ----------------
    def read_schema(self):
        """Return list of (type, name, tbl_name, rootpage, sql) from the
        page-1 tree (root of sqlite_master), which may itself be interior."""
        out = []
        for n, p, is_table, rowid, rec in self.walk_tree(1):
            v = rec["values"]
            if len(v) >= 5 and isinstance(v[0], str):
                root = v[3] if isinstance(v[3], int) else 0
                out.append((v[0], v[1], v[2], root, v[4] if len(v) > 4 else ""))
        return out

    # ---------------- column names / ipk / without-rowid ----------------
    @staticmethod
    def columns_from_sql(sql):
        if not isinstance(sql, str):
            return None
        sql = re.sub(r"(STRICT|WITHOUT\s+ROWID)\s*$", "", sql, flags=re.I)
        m = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`']?[\w$]+[\"`']?\s*\((.*)\)\s*$",
                      sql, re.S | re.I)
        if not m:
            return None
        body = m.group(1)
        cols, depth, cur = [], 0, []
        for ch in body:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                cols.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        if cur:
            cols.append("".join(cur).strip())
        names = []
        for c in cols:
            m2 = re.match(r"[\"`']?([\w$]+)[\"`']?", c)
            if m2:
                names.append(m2.group(1))
        return names or None

    @staticmethod
    def ipk_index(sql):
        """
        Index of the column that is the rowid alias (INTEGER PRIMARY KEY),
        or None.  SQLite stores NULL in the record for that column; the
        real value is the rowid.  Only applies to rowid tables.
        """
        if not isinstance(sql, str):
            return None
        sql = re.sub(r"(STRICT|WITHOUT\s+ROWID)\s*$", "", sql, flags=re.I)
        m = re.search(r"CREATE\s+TABLE\s+.*?\((.*)\)\s*$", sql, re.S | re.I)
        if not m:
            return None
        body = m.group(1)
        depth = 0
        for i, ch in enumerate(body):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                body = body[:i] + "\n" + body[i + 1:]
        cols = [c.strip() for c in body.split("\n")]
        for i, c in enumerate(cols):
            m2 = re.match(r"[\"`']?([\w$]+)[\"`']?\s+INTEGER\s+PRIMARY\s+KEY", c, re.I)
            if m2:
                return i
            m3 = re.search(r"PRIMARY\s+KEY\s*\(\s*[\"`']?([\w$]+)[\"`']?\s*\)", c, re.I)
            if m3:
                name = m3.group(1)
                for j, cc in enumerate(cols):
                    if re.match(r"[\"`']?" + re.escape(name) + r"[\"`']?\s+INTEGER\b", cc, re.I):
                        return j
        return None

    @staticmethod
    def is_without_rowid(sql):
        return bool(re.search(r"without\s+rowid", sql or "", re.I))

    # ---------------- column type signatures (orphan attribution) --------
    @staticmethod
    def parse_column_types(sql):
        """Return (names, types) aligned with the CREATE TABLE column
        order; types are raw type tokens ('' when absent or a non-type
        keyword follows the name)."""
        sql = re.sub(r"(STRICT|WITHOUT\s+ROWID)\s*$", "", sql or "", flags=re.I)
        m = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`']?[\w$]+[\"`']?\s*\((.*)\)\s*$",
                      sql, re.S | re.I)
        if not m:
            return None, None
        body = m.group(1)
        cols, depth, cur = [], 0, []
        for ch in body:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                cols.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        if cur:
            cols.append("".join(cur).strip())
        names, types = [], []
        for c in cols:
            m2 = re.match(r"[\"`']?([\w$]+)[\"`']?\s+([\w$]+)?", c)
            names.append(m2.group(1) if m2 else "col")
            tok = (m2.group(2) or "").upper() if m2 else ""
            if tok in ("", "PRIMARY", "NOT", "UNIQUE", "CHECK", "DEFAULT",
                       "REFERENCES", "COLLATE", "GENERATED", "AS", "CONSTRAINT"):
                tok = ""
            types.append(tok)
        return names or None, types or None

    @staticmethod
    def type_families(tok):
        """Declared type token -> set of serial families the column
        accepts.  None means 'any' (BLOB / untyped column)."""
        t = (tok or "").upper()
        if "INT" in t:
            return {"int"}
        if any(x in t for x in ("CHAR", "CLOB", "TEXT")):
            return {"text"}
        if any(x in t for x in ("REAL", "FLOA", "DOUB")):
            return {"float", "int"}
        return None

    @staticmethod
    def serial_family(t):
        """Serial type -> value-shape family."""
        if t == 0:
            return "null"
        if 1 <= t <= 6:
            return "int"
        if t == 7:
            return "float"
        if t in (8, 9):
            return "int"      # zero/one are integer values
        if t >= 12:
            return "text" if t % 2 else "blob"
        return "?"

    @staticmethod
    def compatible(fams, typetok):
        """Observed serial families `fams` fit a declared type token
        (NULLs fit everywhere)."""
        allowed = SQLiteReader.type_families(typetok)
        if allowed is None:
            return True
        return fams <= (allowed | {"null"})

    # ---------------- brute-force record scan (lost pointers) ----------------
    def scan_page(self, n, require_signal=True, dedupe=True):
        """
        Scan every byte offset of a page for plausible standalone records
        in BOTH cell layouts:
          * rowid-style (leaf table): [pl varint][rowid varint][payload]
          * index-style (WITHOUT ROWID / index): [pl varint][payload]
        Returns a list of dicts {kind, key, values, serials, off}, deduped
        by key.  The serial types are carried through so callers can build
        per-column value-shape signatures.
        When require_signal is True, candidates must contain a visible text
        column or a float (anti-noise gate for unknown-schema mode).
        """
        pg = self.page(n)
        found = []
        if pg is None:
            return found
        lo = 100 if n == 1 else 0   # page 1: skip the 100-byte file header
        for off in range(lo, len(pg)):
            if not 2 <= pg[off] <= 255:
                continue
            pl, o1 = read_varint(pg, off)
            if pl is None or not 2 <= pl <= 300 or o1 - off > 2:
                continue
            # ---- rowid-style ----
            rowid, o2 = read_varint(pg, o1)
            if (rowid is not None and rowid >= 1 and o2 - o1 <= 5
                    and o2 + pl <= len(pg)):
                r, _ = self.parse_record_tolerant(pg[o2:o2 + pl])
                if r is not None and self._scan_ok(r["values"], r["serials"], require_signal):
                    found.append({"kind": "rowid", "key": rowid,
                                  "values": r["values"], "serials": r["serials"],
                                  "off": off})
            # ---- index-style (no rowid varint) ----
            if o1 + pl <= len(pg):
                r, _ = self.parse_record_tolerant(pg[o1:o1 + pl])
                if r is not None and self._scan_ok(r["values"], r["serials"], require_signal):
                    found.append({"kind": "index", "key": tuple(r["values"]),
                                  "values": r["values"], "serials": r["serials"],
                                  "off": off})
        # dedupe: rowid-kind by rowid, index-kind by value tuple.
        # Prefer the HIGHER offset candidate: real cells live in the page's
        # content region; shifted over-parses claiming the same key usually
        # come from header/free-space bytes at lower offsets.  (Owned-page
        # attribution re-selects by declared-type compatibility, so it calls
        # this with dedupe=False.)
        if dedupe:
            uniq = {}
            for c in found:
                k = (c["kind"], c["key"])
                prev = uniq.get(k)
                if prev is None or c["off"] > prev["off"]:
                    uniq[k] = c
            found = list(uniq.values())
        return sorted(found, key=lambda c: c["off"])

    def _scan_ok(self, values, serials, require_signal):
        if not require_signal:
            return True
        has_txt = any(printable_ratio(v) >= self.min_text_ratio
                      for v in text_values(values, serials))
        has_float = any(isinstance(v, float) for v in values)
        return has_txt or has_float

    # ---------------- high level ----------------
    def recover_tables(self):
        schema = self.read_schema()
        tables = []
        for stype, name, tbl, root, sql in schema:
            if stype != "table":
                continue
            if not isinstance(root, int) or root < 2:
                continue
            h = self.page_header(root)
            root_is_index = h is not None and h["type"] in (2, 10)
            no_rowid = self.is_without_rowid(sql) or root_is_index
            cols, col_types = self.parse_column_types(sql)
            ipk = None if no_rowid else self.ipk_index(sql)
            pages = self.tree_pages(root)
            if no_rowid:
                rows = []          # WITHOUT ROWID: no rowids; key by values
                seen = set()
                for n, p, is_table, rowid, rec in self.walk_tree(root):
                    pages.add(n)
                    vals = tuple(rec["values"])
                    if vals not in seen:
                        seen.add(vals)
                        rows.append(list(vals))
            else:
                rows = {}          # rowid table: key by rowid
                seen = set()
                for n, p, is_table, rowid, rec in self.walk_tree(root):
                    pages.add(n)
                    if not is_table or rowid is None:
                        continue
                    values = list(rec["values"])
                    if ipk is not None and ipk < len(values):
                        values[ipk] = rowid
                    if rowid not in rows:
                        rows[rowid] = values
                        seen.add(rowid)
            tables.append({"name": name, "root": root, "sql": sql,
                           "columns": cols or None, "col_types": col_types or [],
                           "ipk": ipk,
                           "no_rowid": no_rowid, "rows": rows, "notes": {},
                           "pages": pages, "_seen": seen,
                           "origin": "schema"})
        return tables

    # ---------------- attribution helpers ----------------
    @staticmethod
    def _table_arity(t):
        if t.get("columns"):
            return len(t["columns"])
        sample = list(t["rows"].values() if isinstance(t["rows"], dict) else t["rows"])
        return len(sample[0]) if sample else None

    def _add_candidate(self, t, c):
        """Add a scanned candidate to table t, deduped by rowid (rowid
        tables) or value tuple (WITHOUT ROWID tables)."""
        if t.get("no_rowid"):
            key = tuple(c["values"])
            if key in t["_seen"]:
                return
            t["_seen"].add(key)
            t["rows"].append(list(c["values"]))
        else:
            key = c["key"]
            if key in t["_seen"]:
                return
            t["_seen"].add(key)
            values = list(c["values"])
            if t.get("ipk") is not None and t["ipk"] < len(values):
                values[t["ipk"]] = key
            t["rows"][key] = values

    def _compat_score(self, c, t):
        """How many of the candidate's columns fit the table's declared
        column types (0..arity).  Used to pick the best parse among
        candidates that share a key."""
        types = t.get("col_types") or []
        return sum(1 for j in range(len(c["values"]))
                   if j >= len(c["serials"]) or
                   self.compatible(frozenset([self.serial_family(c["serials"][j])]),
                                   types[j] if j < len(types) else ""))

    def _offset_threshold(self, n):
        """Lower bound of the plausible cell region of page n
        (min of content start and surviving cell pointers), or None when
        the page header is unusable.  Suppresses shifted-offset parses of
        headers/free space when scans report novel rowids."""
        h = self.page_header(n)
        if h is None:
            return None
        cands = [h["cstart"]] + [p for p in h["ptrs"] if 0 < p < self.page_size]
        if not cands:
            return None
        t = min(cands)
        return t if 0 < t < self.page_size else None

    def recover_scan(self, tables):
        """
        Complement tree-walk rows with scanned cells.  ATTRIBUTION FIRST:
        a page reachable from exactly one table's root belongs to that
        table — its scanned candidates are offered to that table only
        (same cell layout, same arity, plausible offset, key-deduped).
        Arity may admit a row; it never decides which table owns it.
        Unreachable ('orphan') pages are attributed per page by
        column-type signature against the declared schema; unresolvable
        orphans go to a warned orphan-N-col group instead of being merged
        into any table.  Page 1 (sqlite_master) is not data and is never
        scanned here.
        """
        by_name = {t["name"]: t for t in tables}
        owner_pages = {}
        for t in tables:
            for pg in t.get("pages") or ():
                owner_pages.setdefault(pg, []).append(t["name"])
        single_owner = {pg: names[0] for pg, names in owner_pages.items()
                        if len(names) == 1}
        ambiguous = sorted(pg for pg, names in owner_pages.items() if len(names) > 1)
        if ambiguous:
            print(f"# WARNING: page(s) reachable from multiple table roots: "
                  f"{ambiguous}; their scanned cells are kept as orphans, "
                  f"not merged", file=sys.stderr)

        orphan_cands = []
        for n in range(2, self.file_pages + 1):
            cands = self.scan_page(n, require_signal=False, dedupe=False)
            if not cands:
                continue
            owner = single_owner.get(n)
            if owner:
                t = by_name[owner]
                ar = self._table_arity(t)
                if ar is None:
                    orphan_cands.extend(self._dedupe_candidates(cands))
                    continue
                thr = self._offset_threshold(n)
                # per-key selection: highest declared-type compatibility,
                # tie-break by offset (real cells cluster at higher offsets)
                best = {}
                for c in cands:
                    if c["kind"] != ("index" if t.get("no_rowid") else "rowid"):
                        continue
                    if len(c["values"]) != ar:
                        continue
                    if thr is not None and c["off"] < thr:
                        continue
                    key = c["key"]
                    score = self._compat_score(c, t)
                    prev = best.get(key)
                    if prev is None or (score, c["off"]) > (prev[0], prev[1]):
                        best[key] = (score, c["off"], c)
                for _, _, c in best.values():
                    self._add_candidate(t, c)
            else:
                cands = self._dedupe_candidates(cands)
                # orphan page: keep only its DOMINANT (kind, arity) group —
                # shifted over-parses of other arities are noise, not data
                counts = {}
                for c in cands:
                    counts[(c["kind"], len(c["values"]))] = \
                        counts.get((c["kind"], len(c["values"])), 0) + 1
                if not counts:
                    continue
                dom = max(counts.items(), key=lambda kv: (kv[1], kv[0][0] == "rowid"))[0]
                if counts[dom] < 2:
                    print(f"# WARNING: page {n} unreachable from any table root "
                          f"and too noisy to interpret; {len(cands)} cells "
                          f"discarded", file=sys.stderr)
                    continue
                thr = self._offset_threshold(n)
                for c in cands:
                    if (c["kind"], len(c["values"])) != dom:
                        continue
                    if thr is not None and c["off"] < thr:
                        continue
                    orphan_cands.append((n, c))

        if orphan_cands:
            self._attribute_orphans(tables, orphan_cands, by_name)

    @staticmethod
    def _dedupe_candidates(cands):
        """Per (kind, key) keep the highest-offset candidate."""
        uniq = {}
        for c in cands:
            k = (c["kind"], c["key"])
            prev = uniq.get(k)
            if prev is None or c["off"] > prev["off"]:
                uniq[k] = c
        return sorted(uniq.values(), key=lambda c: c["off"])

    def _attribute_orphans(self, tables, orphan_cands, by_name):
        """Best-effort attribution of unreachable pages by column-type
        signature; unresolved pages become a warned orphan group."""
        groups = {}
        for n, c in orphan_cands:
            groups.setdefault((n, c["kind"], len(c["values"])), []).append(c)
        for (n, kind, arity), cands in sorted(groups.items()):
            sig = self._signature(cands, arity)
            best, best_score, tied = None, -1, False
            for t in tables:
                if t.get("no_rowid") != (kind == "index"):
                    continue
                if self._table_arity(t) != arity:
                    continue
                types = t.get("col_types") or []
                score = sum(1 for j in range(arity)
                            if self.compatible(sig[j],
                                               types[j] if j < len(types) else ""))
                if score > best_score:
                    best, best_score, tied = t, score, False
                elif score == best_score:
                    tied = True
            if best is not None and best_score == arity and not tied:
                for c in cands:
                    self._add_candidate(best, c)
                print(f"# orphan page {n}: {len(cands)} cells attributed to "
                      f"table '{best['name']}' by column-type signature",
                      file=sys.stderr)
            else:
                gname = f"orphan-{arity}col-{kind}"
                g = by_name.get(gname)
                if g is None:
                    g = {"name": gname, "root": None, "sql": None,
                         "columns": [f"col{i}" for i in range(arity)],
                         "col_types": [""] * arity, "ipk": None,
                         "no_rowid": kind == "index",
                         "rows": {} if kind == "rowid" else [], "_seen": set(),
                         "pages": set(), "notes": {}, "origin": "orphan"}
                    tables.append(g)
                    by_name[gname] = g
                for c in cands:
                    self._add_candidate(g, c)
                print(f"# WARNING: page {n} unreachable from any table root and "
                      f"indistinguishable by column types; {len(cands)} cells "
                      f"kept in group '{gname}'", file=sys.stderr)

    def _signature(self, cands, arity):
        """Per-column frozenset of serial families across candidates."""
        fams = []
        for j in range(arity):
            fams.append(frozenset(
                self.serial_family(c["serials"][j])
                for c in cands if len(c["serials"]) > j))
        return fams

    def fallback_scan_tables(self, columns_hint=None):
        """No-readable-schema mode: scan pages 2+, keep each page's
        dominant (kind, arity) group, cluster PAGES by (kind, arity,
        page-level column signature), and key rows by (page, key) so
        cross-table rowid collisions never drop rows.  Same-arity tables
        with different value shapes therefore stay in separate groups;
        indistinguishable tables share a group (the honest limit)."""
        per_page = {}   # page -> dominant-group candidates
        for n in range(2, self.file_pages + 1):
            cands = self.scan_page(n, require_signal=True)
            if not cands:
                continue
            counts = {}
            for c in cands:
                counts[(c["kind"], len(c["values"]))] = \
                    counts.get((c["kind"], len(c["values"])), 0) + 1
            dom = max(counts.items(), key=lambda kv: (kv[1], kv[0][0] == "rowid"))[0]
            if counts[dom] < 2:
                continue
            per_page[n] = [c for c in cands
                           if (c["kind"], len(c["values"])) == dom]
        # cluster pages with the same (kind, arity, per-column family union)
        clusters = {}   # (kind, arity, sig) -> {key: (page, values)}
        page_sig = {}
        for n, cands in per_page.items():
            kind, arity = (cands[0]["kind"], len(cands[0]["values"]))
            sig = tuple(frozenset(self.serial_family(c["serials"][j])
                                  for c in cands if len(c["serials"]) > j)
                        for j in range(arity))
            page_sig[n] = (kind, arity, sig)
            clusters.setdefault((kind, arity, sig), {})[n] = None
        names_hint = columns_hint.split(",") if columns_hint else None
        tables = []
        for (kind, cnt, sig), pages in sorted(clusters.items()):
            rows = {}
            for n in pages:
                for c in per_page[n]:
                    rows.setdefault((n, c["key"]), c["values"])
            tag = "".join("".join(sorted(
                {"text": "T", "int": "I", "float": "F", "blob": "B",
                 "null": "N"}.get(f, "?")
                for f in fam)) for fam in sig)
            prefix = "index_" if kind == "index" else ""
            name = f"{prefix}table_{cnt}col_{tag}"
            cols = names_hint or [f"col{i}" for i in range(cnt)]
            tables.append({"name": name, "root": None, "sql": None,
                           "columns": cols, "col_types": [""] * cnt,
                           "ipk": None, "no_rowid": kind == "index",
                           "rows": list(rows.values()), "_seen": set(),
                           "pages": set(), "notes": {},
                           "origin": "scan"})
        return tables


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("out", nargs="?", default=None)
    ap.add_argument("--pieces", nargs="+", default=None,
                    help="additional fragment files (byte-range pieces of a "
                         "split DB) to reassemble with DB")
    ap.add_argument("--columns", default=None, help="comma-separated column names fallback")
    ap.add_argument("--lenient", action="store_true")
    ap.add_argument("--min-text", type=float, default=0.7)
    ap.add_argument("--probe", action="store_true", help="header diagnostics only")
    ap.add_argument("--inspect", action="store_true", help="per-page diagnostics")
    args = ap.parse_args()

    # ---- fragment inventory: never die with a bare traceback ---------
    piece_files = [args.db] + (args.pieces or [])
    pieces = []
    for f in piece_files:
        b = open(f, "rb").read()
        pieces.append(b)
        print(f"# piece {f}: {len(b)} bytes, magic={'yes' if b.startswith(MAGIC) else 'no'}",
              file=sys.stderr)
    need_reassembly = bool(args.pieces) or not pieces[0].startswith(MAGIC)
    r = None
    if need_reassembly:
        if len(pieces) > 1:
            data, rep = reassemble_pieces(pieces)
        else:
            data, rep = reassemble_single(pieces[0])
        if data is not None:
            r = SQLiteReader(data, args.min_text, args.lenient, source_name=args.db)
            print(f"# fragment reassembly: page_size={rep.get('page_size')} "
                  f"orders_tried={rep.get('orders_tried')} rows={rep.get('rows')} "
                  f"reachable_pages={rep.get('reachable_pages')} "
                  f"missing={{ {rep.get('missing')} }}", file=sys.stderr)
        else:
            # fall back to reading the first piece alone (it may be a valid
            # standalone db with extra unrelated files)
            try:
                r = SQLiteReader(pieces[0], args.min_text, args.lenient,
                                 source_name=args.db)
            except ValueError:
                print(f"# ERROR: cannot reassemble fragments: {rep.get('error', '?')}",
                      file=sys.stderr)
                print("# inventory: pieces=%d lengths=%s" % (len(pieces), rep.get("lens")),
                      file=sys.stderr)
                print("# pass every byte-range piece as a separate file "
                      "(DB + --pieces f1 f2 ...); whole-page chunks in one "
                      "shuffled file are handled automatically.",
                      file=sys.stderr)
                return 1
    if r is None:
        r = SQLiteReader(pieces[0], args.min_text, args.lenient, source_name=args.db)

    trunc_note = "  <-- TRUNCATED: header claims more pages than file holds" \
        if r.page_count_hdr > r.file_pages else ""
    print(f"# {args.db}: page_size={r.page_size} usable={r.usable} "
          f"encoding={r.encoding}({r.codec}) header_pages={r.page_count_hdr} "
          f"file_pages={r.file_pages}{trunc_note} freelist_trunk={r.freelist_trunk} "
          f"freelist_count={r.freelist_count}", file=sys.stderr)

    if args.probe:
        return 0
    if args.inspect:
        for n in range(1, r.file_pages + 1):
            h = r.page_header(n)
            if h is None:
                print(f"page {n}: <missing/truncated>", file=sys.stderr)
                continue
            print(f"page {n}: {h['typename']} ncell={h['ncell']} "
                  f"content_start={h['cstart']} frag={h['frag']} "
                  f"right_child={h['right_child']} ptrs={h['ptrs']}", file=sys.stderr)
        return 0

    tables = r.recover_tables()
    if tables:
        r.recover_scan(tables)
    else:
        print(f"# WARNING: sqlite_master unreadable (encoding={r.encoding}, "
              f"page1 ncell={r.page_header(1)['ncell'] if r.page_header(1) else '?'}); "
              f"falling back to byte-scan with positional columns", file=sys.stderr)
        tables = r.fallback_scan_tables(args.columns)

    out_rows = []
    for t in sorted(tables, key=lambda x: x["name"]):
        if isinstance(t["rows"], dict):
            row_items = sorted(t["rows"].items())
            nrows = len(row_items)
        else:
            row_items = [(i, v) for i, v in enumerate(t["rows"])]
            nrows = len(row_items)
        cols = t["columns"] or (args.columns.split(",") if args.columns else None) \
               or [f"col{i}" for i in range(max((len(v) for _, v in row_items), default=2))]
        for _, vals in row_items:
            d = {}
            for i, v in enumerate(vals):
                if i < len(cols):
                    d[cols[i]] = v
                else:
                    d[f"col{i}"] = v
            out_rows.append(d)
        kind = "WITHOUT ROWID" if t.get("no_rowid") else "rowid"
        print(f"# table {t['name']} [{kind}]: {nrows} rows recovered"
              + (f" (schema root={t['root']})" if t.get("root") else ""), file=sys.stderr)

    if args.out:
        with open(args.out, "w") as f:
            json.dump(out_rows, f)
            f.write("\n")
        print(f"# wrote {len(out_rows)} rows -> {args.out}", file=sys.stderr)
    else:
        print(json.dumps(out_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())