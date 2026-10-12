#!/usr/bin/env python3
"""Raw SQLite storage reader for damaged database files.

Purpose: extract as many structurally valid records as possible from a
SQLite file that ordinary tools refuse to open.  It does NOT depend on the
SQLite C library; it parses pages, btrees, cells, records, varints, serial
types, integers, IEEE-754 floats and text directly.

Modes
-----
  sqlite_raw.py FILE info
      Print the file header, per-page map and a consistency report.
      Detects truncation, zeroed regions, stray single-bit noise.

  sqlite_raw.py FILE dump [--root N] [--no-repair] [--columns a,b,c]
                         [--flat k1,k2 [--out out.json]]
      Walk table btrees (root page from sqlite_schema if readable, else
      --root N) and print one JSON object per record.  Cells that fail
      strict parsing are retried under minimal single-bit-flip repair.
      With --no-repair, broken cells are skipped and reported.
      --flat k1,k2 renames the columns to the task's JSON schema keys and
      (for a single-table dump) emits a bare list of objects; add --out
      FILE to write the deliverable directly.  Repair notes go to stderr.

  sqlite_raw.py FILE verify [--flat k1,k2] [--out out.json] [--no-repair]
      One-command end-to-end: recover schema + rows, rebuild the database
      from them, byte-diff against FILE, and print the classified verdict
      (writer-version stamp / single-bit flips / unexplained multi-bit
      diffs).  With --out (and --flat for a single table) also writes the
      deliverable JSON.  Exit code 0 = proven byte-exact modulo flips,
      1 = unexplained diffs remain.  This is the fastest correct path;
      use the per-mode commands below only when its report needs
      investigation.

  sqlite_raw.py FILE scan [--utf16] [--min-str N] [--contains SUBSTR]
      Forget headers entirely: scan every byte offset for anything that
      parses as a record (header size, serial types, data all consistent,
      at least one plausible text column).  Prints offset + values.
      Useful for zeroed regions, split fragments, broken page headers.
      --contains SUBSTR keeps only records whose text contains SUBSTR
      (e.g. the family's key prefix) -- the cheapest way to reject
      spurious mid-cell parses.

Notes
-----
* ALL parsing is wrapped so one bad page/cell never aborts the run.
* The walker returns rows in btree key order (pointer-array order on a
  leaf page), which is the natural table-scan order of the original DB.
* Repairs are only attempted when a cell fails strict validation, and only
  candidates that restore full consistency are accepted.  If more than one
  candidate survives, the row is marked "repair_ambiguous" -- resolve
  externally (see SKILL.md verification section).
"""
import json
import os
import sys
import struct

# --------------------------------------------------------------------------
# varint
# --------------------------------------------------------------------------
def get_varint(buf, i):
    """Decode SQLite variable-length integer at buf[i:].
    Big-endian base-128: most-significant 7-bit group first, high bit set
    on every byte except the last.  Returns (value, next_i)."""
    v = 0
    while True:
        if i >= len(buf):
            raise ValueError("varint runs off end of buffer")
        b = buf[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not (b & 0x80):
            return v, i

def put_varint(v):
    """Encode value as SQLite varint (most-significant group first)."""
    groups = []
    while True:
        groups.append(v & 0x7F)
        v >>= 7
        if v == 0:
            break
    out = bytearray()
    for idx in range(len(groups) - 1, -1, -1):
        g = groups[idx]
        if idx != 0:                      # all but last group: cont bit
            g |= 0x80
        out.append(g)
    return bytes(out)

# --------------------------------------------------------------------------
# serial types
# --------------------------------------------------------------------------
# length in bytes of the value for a serial type code
def serial_len(st):
    if st == 0:
        return 0
    if 1 <= st <= 4:
        return st
    if st == 5:
        return 6
    if st in (6, 7):
        return 8
    if st in (8, 9):
        return 0
    if st >= 12:
        return (st - 12) // 2
    raise ValueError(f"reserved serial type {st}")

def serial_is_text(st):
    return st >= 13 and (st - 13) % 2 == 0

def serial_is_blob(st):
    return st >= 12 and (st - 12) % 2 == 0

def serial_is_float(st):
    return st == 7

def decode_value(st, raw, encoding):
    """Decode one record value from its serial type and raw bytes."""
    if st == 0:
        return None
    if st == 1:                       # 8-bit signed
        return int.from_bytes(raw, "big", signed=True)
    if st == 2:                       # 16-bit big-endian (signed per docs)
        return int.from_bytes(raw, "big", signed=True)
    if st == 3:                       # 24-bit signed
        return int.from_bytes(raw, "big", signed=True)
    if st == 4:                       # 32-bit big-endian (signed per docs)
        return int.from_bytes(raw, "big", signed=True)
    if st == 5:                       # 48-bit signed
        return int.from_bytes(raw, "big", signed=True)
    if st == 6:                       # 64-bit signed
        return int.from_bytes(raw, "big", signed=True)
    if st == 7:                       # IEEE-754 float64
        return struct.unpack(">d", raw)[0]
    if st == 8:
        return 0
    if st == 9:
        return 1
    if serial_is_text(st):
        txt = raw.decode(encoding,
                         "replace" if len(raw) % 2 == 0 else "strict")
        return txt
    return list(raw)                  # blob -> list of ints (JSON-safe)

def text_suspicious(v):
    """True when text contains >5% NUL/replacement chars: the bytes
    survived but the content region was zeroed or damaged."""
    if not isinstance(v, str) or not v:
        return False
    bad = sum(1 for ch in v if ch == "\x00" or ch == "\ufffd")
    if len(v) >= 20 and bad / len(v) > 0.05:
        return True
    return "\x00" in v

def decode_text(raw, enc):
    """Best-effort text decode; never raises."""
    try:
        return raw.decode(enc)
    except Exception:
        return raw.decode("utf-8", "replace")

def plausible_text(raw, enc):
    """Heuristic: text looks like real text, not noise.
    Accepts UTF-8/16 valid strings with >= 80% printable ASCII bytes."""
    try:
        s = raw.decode(enc)
    except Exception:
        return False
    if enc in ("utf-16-le", "utf-16-be"):
        return len(s) > 0
    if len(raw) == 0:
        return False
    printables = sum(1 for b in raw if 0x20 <= b <= 0x7E or b in (9, 10, 13))
    return s and printables / len(raw) >= 0.8

# --------------------------------------------------------------------------
# records (header + values), optionally with bit-flip repair
# --------------------------------------------------------------------------
class RecordError(Exception):
    pass

def parse_record(buf, i, encoding="utf-8", partial_ok=False, end=None):
    """Parse a record at buf[i:].  Returns (values, serials, next_i).
    Raises RecordError unless partial_ok.  If end is given the record must
    fit inside buf[i:end]."""
    limit = len(buf) if end is None else min(end, len(buf))
    start = i
    hsz, i = get_varint(buf, i)
    if hsz < 1:
        raise RecordError("header size < 1")
    serials = []
    header_end = start + hsz
    while i < header_end:
        st, i = get_varint(buf, i)
        if st not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9) and st < 12:
            raise RecordError(f"reserved serial type {st}")
        serials.append(st)
    if i != header_end:
        raise RecordError("header varints overshoot header size")
    values = []
    for st in serials:
        L = serial_len(st)
        if i + L > limit and not partial_ok:
            raise RecordError(f"value overruns boundary (serial {st}, need {L})")
        raw = buf[i:i + L]
        i += L
        try:
            values.append(decode_value(st, raw, encoding))
        except Exception as e:
            raise RecordError(f"value decode failed: {e}")
    return values, serials, i

# --------------------------------------------------------------------------
# cells
# --------------------------------------------------------------------------
def decode_cell(raw, start, boundary, encoding, resolver=None):
    """Decode one table-leaf cell (varint plen, varint rowid, record).
    resolver(pageno) -> bytes follows overflow chains when the record
    payload spills across pages.  Returns (plen, rowid, values, serials,
    cell_end).  Raises RecordError."""
    i = start
    plen, i = get_varint(raw, i)
    if plen < 1:
        raise RecordError("bad payload length")
    rowid, i = get_varint(raw, i)
    try:
        values, serials, i2 = parse_record(raw, i, encoding, end=boundary)
        record_size = i2 - i
        if record_size != plen:
            raise RecordError(f"plen={plen} but record header+data={record_size}")
        if i2 > boundary:
            raise RecordError("cell overruns next boundary")
        return plen, rowid, values, serials, i2
    except RecordError:
        if resolver is None:
            raise
        # overflow interpretation: K local payload bytes + 4-byte page no
        if boundary - i <= 4:
            raise
        trailer = raw[boundary - 4:boundary]
        nxt = int.from_bytes(trailer, "big")
        if nxt < 1:
            raise
        local = raw[i:boundary - 4]
        chain = []
        remaining = plen - len(local)
        hops = 0
        while remaining > 0 and nxt >= 1 and hops < 10000:
            page = resolver(nxt)
            if not page:
                raise RecordError(f"overflow page {nxt} unreadable")
            nxt = int.from_bytes(page[:4], "big")
            chunk = page[4:]
            chain.append(chunk)
            remaining -= len(chunk)
            hops += 1
        comb = (local + b"".join(chain))[:plen]
        if len(comb) != plen:
            raise RecordError("overflow chain shorter than payload")
        values, serials, i2 = parse_record(comb, 0, encoding)
        if i2 != plen:
            raise RecordError("combined overflow payload mismatch")
        return plen, rowid, values, serials, boundary

def repair_cell(raw, start, boundary, encoding, mut_bytes=None, validator=None):
    """Try minimal single-bit flips to make a broken cell parse.
    validator(vals, serials) -> int adds domain-aware score (schema rows:
    rootpage sanity, CREATE-prefix, balanced parens).  Returns
    (plen, rowid, values, serials, end, info) or raises RecordError."""
    # gather candidates: per byte, per bit -> flip and try strict decode
    cands = []
    nbytes = boundary - start
    span = min(nbytes, mut_bytes) if mut_bytes is not None else nbytes
    for pos in range(start, start + span):
        for bit in range(8):
            m = 1 << bit
            newbuf = bytearray(raw)
            newbuf[pos] ^= m
            try:
                plen, rowid, values, serials, end = decode_cell(
                    bytes(newbuf), start, boundary, encoding)
                total = 1 + len(put_varint(rowid)) + plen
                desc = {
                    "flip": (pos, bit),
                    "offset": pos,
                    "gap_ok": (end - start) == nbytes or total == nbytes,
                    "score": 0,
                    "vals": values,
                }
                cands.append((plen, rowid, values, serials, end, desc))
            except Exception:
                continue
    if not cands:
        raise RecordError("no single-bit repair parses")
    # prefer exact gap, then header-region flips, then plausible text,
    # then domain validator bonus
    for c in cands:
        d = c[5]
        # count plausible text columns
        pt = 0
        for v in d["vals"]:
            if isinstance(v, str) and v != "":
                pt += 1
        d["score"] += 100 if d["gap_ok"] else 0
        d["score"] += 10 * pt
        if validator is not None:
            try:
                d["score"] += validator(d["vals"], c[3])
            except Exception:
                pass
    cands.sort(key=lambda c: c[5]["score"], reverse=True)
    if len(cands) > 1 and cands[0][5]["score"] == cands[1][5]["score"]:
        res = cands[0]
        res[5]["ambiguous"] = True
        return res
    res = cands[0]
    res[5]["ambiguous"] = False
    return res

# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
def page_info(buf, pageno, page_size, base_is_header=False):
    """Summarize one page.  Returns dict."""
    off = (pageno - 1) * page_size
    raw = buf[off:off + page_size]
    hd = 100 if base_is_header else 0
    info = {"page": pageno, "offset": off}
    if len(raw) < hd + 8:
        info["note"] = "page missing/truncated"
        return info
    ptype = raw[hd]
    info["type"] = ptype
    ptype_names = {2: "interior_index", 5: "interior_table",
                   10: "leaf_index", 13: "leaf_table"}
    info["type_name"] = ptype_names.get(ptype, "unknown")
    if ptype in (5, 13):
        info["ncell"] = int.from_bytes(raw[hd + 3:hd + 5], "big")
        info["content_start"] = int.from_bytes(raw[hd + 5:hd + 7], "big")
    elif ptype in (2, 10):
        info["ncell"] = int.from_bytes(raw[hd + 3:hd + 5], "big")
        info["content_start"] = int.from_bytes(raw[hd + 5:hd + 7], "big")
    elif ptype == 0:
        info["note"] = "freelist/zeroed page"
    return info

def cell_pointers(raw, hd, ncell, interior=False):
    """Parse the 2-byte cell-pointer array.  On interior pages the array
    starts at hd+12 (hd+8 holds the 4-byte rightmost child pointer)."""
    ptrs = []
    base = hd + (12 if interior else 8)
    for k in range(ncell):
        p = base + 2 * k
        if p + 2 > len(raw):
            break
        ptrs.append(int.from_bytes(raw[p:p + 2], "big"))
    return ptrs

def zero_run_stats(buf, page_size):
    """Report zero-run statistics: overall + longest run."""
    if not buf:
        return (0.0, 0, 0)
    zeros = buf.count(0)
    longest = cur = 0
    for b in buf:
        if b == 0:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return (zeros / len(buf), longest, len(buf))

# --------------------------------------------------------------------------
# btree walking
# --------------------------------------------------------------------------
def walk_table(buf, root, page_size, encoding, repair=True, validator=None,
               quiet=False):
    """Collect rows (rowid, values, serials, source_note) from a table btree.
    quiet=True suppresses per-cell diagnostics (used for internal schema
    probes whose failure is expected and handled)."""
    rows = []
    seen = set()

    def walk(pageno):
        if pageno in seen or pageno < 1:
            return
        seen.add(pageno)
        off = (pageno - 1) * page_size
        raw = buf[off:off + page_size]
        if not raw:
            return

        def resolver(pn):
            o = (pn - 1) * page_size
            b = buf[o:o + page_size]
            return b if len(b) == page_size else None

        hd = 100 if pageno == 1 else 0
        if hd + 8 > len(raw):
            return
        ptype = raw[hd]
        ncell = int.from_bytes(raw[hd + 3:hd + 5], "big")
        cstart = int.from_bytes(raw[hd + 5:hd + 7], "big")
        ptrs = cell_pointers(raw, hd, ncell, interior=(ptype in (2, 5)))
        if ptype == 5:                      # interior table
            # cells = 4-byte left-child page number + varint key
            right = int.from_bytes(raw[hd + 8:hd + 12], "big")
            for k in range(ncell):
                cp = ptrs[k] if k < len(ptrs) else None
                if cp is None or cp + 4 > len(raw):
                    continue
                walk(int.from_bytes(raw[cp:cp + 4], "big"))
            walk(right)
        elif ptype == 13:                   # leaf table
            # NOTE: content_start marks the start of the cell area; cells
            # physically extend to the next higher cell pointer, else to
            # the page end. content_start itself may be corrupted, so use
            # it only for sanity reporting.
            if not quiet and ptrs and min(ptrs) < cstart:
                sys.stderr.write(
                    f"[warn] page {pageno}: min cell ptr 0x{min(ptrs):04x} "
                    f"< content_start 0x{cstart:04x} "
                    f"(likely flipped content_start byte)\n")
            sorted_ptrs = sorted(set(ptrs))
            # first pass: strictly valid cells (needed for boundaries)
            good = {}
            for kk, cp in enumerate(ptrs):
                bigger = [b for b in sorted_ptrs if b > cp]
                boundary = min(bigger, default=len(raw))
                try:
                    plen, rowid, values, serials, end = decode_cell(
                        raw, cp, boundary, encoding, resolver=resolver)
                    note = "ok"
                    if any(text_suspicious(v) for v in values
                           if isinstance(v, str)):
                        note = "partial(zeroed-values?)"
                    good[cp] = (rowid, values, serials, end, note)
                except Exception:
                    pass
            # second pass: emit good cells, repair broken ones
            for kk, cp in enumerate(ptrs):
                if cp in good:
                    rowid, values, serials, end, note = good[cp]
                    rows.extend([(rowid, values, serials, note)])
                    continue
                bigger = [b for b in sorted_ptrs if b > cp]
                boundary = min(bigger, default=len(raw))
                rows_out = None
                # 1) content flip repair at the stated pointer
                if repair:
                    try:
                        res = repair_cell(raw, cp, boundary, encoding,
                                          validator=validator)
                        plen, rowid, values, serials, end = res[:5]
                        note = "ambiguous" if res[5].get("ambiguous") \
                            else f"repaired({res[5]['offset']:04x})"
                        rows_out = [(rowid, values, serials, note)]
                    except Exception:
                        rows_out = None
                # 2) pointer repair: the cell pointer itself may be damaged
                if rows_out is None and repair:
                    good_spans = sorted(
                        (s, e) for s, (_, _, _, e, _) in good.items())
                    cands = []
                    for t in range(max(int(cstart), cp - 16),
                                   min(cp + 17, len(raw))):
                        if any(s <= t < e for s, e in good_spans):
                            continue
                        try:
                            plen, rowid, values, serials, end = decode_cell(
                                raw, t, len(raw), encoding,
                                resolver=resolver)
                            if not (0 < rowid < 2 ** 31):
                                continue
                            pt = sum(1 for v in values
                                     if isinstance(v, str) and v != "")
                            adj = end == len(raw) or \
                                any(end == s for s in sorted_ptrs
                                    if s > t)
                            cands.append((t, rowid, values, serials, end,
                                          adj, pt))
                        except Exception:
                            continue
                    if cands:
                        cands.sort(key=lambda c: (c[5], c[6]),
                                   reverse=True)
                        t, rowid, values, serials, end, adj, pt = cands[0]
                        note = f"ptr-repaired({t:04x})"
                        if any(text_suspicious(v) for v in values
                               if isinstance(v, str)):
                            note += " (zeroed-values?)"
                        rows_out = [(rowid, values, serials, note)]
                if rows_out:
                    rows.extend(rows_out)
                else:
                    if not quiet:
                        sys.stderr.write(
                            f"[warn] page {pageno}: cell at 0x{cp:04x} "
                            f"unrecoverable\n")
        elif ptype in (2, 10):              # index btree: flag it
            if not quiet:
                note = f"index page {pageno} skipped (see scan for its records)"
            else:
                note = f"index page {pageno} skipped"
            rows.append((None, [note], [], "index"))
    walk(root)
    return rows

# --------------------------------------------------------------------------
# schema handling
# --------------------------------------------------------------------------
def schema_validator(vals, serials, n_pages=128):
    """Domain-aware score for candidate sqlite_schema rows.
    Shape: (type, name, tbl_name, rootpage, sql)."""
    score = 0
    try:
        if len(vals) < 4 or len(serials) < 5:
            return -50
        typ, name, tbl, root = vals[0], vals[1], vals[2], vals[3]
        if not isinstance(typ, str) or typ not in (
                "table", "index", "view", "trigger"):
            return -50
        if not isinstance(name, str) or not name:
            return -50
        if isinstance(root, int) and 1 <= root <= n_pages:
            score += 40
        else:
            score -= 50
        sql = vals[4] if len(vals) > 4 else ""
        if isinstance(sql, str):
            if sql.lstrip().upper().startswith("CREATE"):
                score += 20
            if name in sql:
                score += 10
            if sql.count("(") == 1 and sql.count(")") == 1 and \
                    sql.rstrip().endswith(")"):
                score += 20
    except Exception:
        return -50
    return score

def find_schema_rows(buf, page_size, encoding, repair=True):
    """Best-effort parse of sqlite_schema from page 1.
    Returns list of (type, name, tbl_name, rootpage, sql) or []."""
    rows = []
    try:
        rows = walk_table(buf, 1, page_size, encoding, repair=False,
                          quiet=True)
    except Exception:
        rows = []
    def run(rows):
        out = []
        for rowid, values, serials, note in rows:
            if isinstance(values, list) and len(values) >= 5 and values[0] in \
                    ("table", "index", "view", "trigger"):
                try:
                    root = int(values[3])
                    out.append(tuple(values[:5]) + (root,))
                except Exception:
                    out.append(tuple(values[:5]) + (0,))
        return out
    out = run(rows)
    if not out and repair:
        # retry with repair enabled and schema-aware candidate scoring
        try:
            rows = walk_table(buf, 1, page_size, encoding, repair=True,
                              validator=schema_validator, quiet=True)
            out = run(rows)
        except Exception:
            pass
    return out

def parse_create_sql(sql):
    """Extract [(column_name, declared_type), ...] from a CREATE TABLE."""
    if not sql or "(" not in sql:
        return []
    body = sql[sql.index("(") + 1:]
    depth = 0
    end = len(body)
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    cols = []
    for part in body[:end].split(","):
        part = part.strip().replace("\n", " ")
        tokens = part.split()
        if not tokens:
            continue
        name = tokens[0].lstrip("(").rstrip(")").strip('"`[] ')
        decl = " ".join(tokens[1:])
        cols.append((name, decl))
    return cols

# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------
def mode_info(path):
    buf = open(path, "rb").read()
    print(f"file: {path}  size: {len(buf)} bytes")
    if len(buf) < 100:
        print("too short for a SQLite file; likely truncated to header only")
        pct, longest, total = zero_run_stats(buf, len(buf))
        print(f"zero bytes: {pct*100:.1f}%  longest run: {longest}/{total}")
        return
    magic = buf[:16]
    if magic != b"SQLite format 3\x00":
        print("WARNING: missing header magic")
    page_size = int.from_bytes(buf[16:18], "big")
    n_pages = int.from_bytes(buf[28:32], "big")
    enc = {1: "utf-8", 2: "utf-16-le", 3: "utf-16-be"}.get(
        int.from_bytes(buf[56:60], "big"), "utf-8")
    ver = buf[96:100].hex()
    print(f"header: page_size={page_size} pages={n_pages} "
          f"expected_size={page_size*n_pages} change_counter="
          f"{int.from_bytes(buf[24:28],'big')} schema_cookie="
          f"{int.from_bytes(buf[40:44],'big')} encoding={enc} "
          f"writer_version={ver}")
    if page_size % 2 or page_size < 512 or page_size > 65536 or \
            page_size & (page_size - 1):
        print("WARNING: page size not a power of two in [512,65536]")
    if len(buf) % page_size:
        print(f"WARNING: file size not a multiple of page size "
              f"(truncation? {len(buf)} % {page_size} != 0)")
    if page_size * n_pages != len(buf):
        print(f"WARNING: header claims {page_size*n_pages} bytes but file has "
              f"{len(buf)} (truncated or trailer present)")
    nz = sum(1 for b in buf if b)
    print(f"nonzero bytes: {nz}/{len(buf)} ({nz/len(buf)*100:.1f}%)")
    single_bit = sum(1 for b in buf if b in (1, 2, 4, 8, 16, 32, 64, 128))
    print(f"single-bit-valued bytes: {single_bit} (flip noise if in "
          f"otherwise-zero regions)")
    for pageno in range(1, min(n_pages, 256) + 1):
        info = page_info(buf, pageno, page_size, base_is_header=(pageno == 1))
        if "note" in info:
            print(f"page {pageno}: {info.get('note')}")
            continue
        p = (pageno - 1) * page_size
        raw = buf[p:p + page_size]
        zr = zero_run_stats(raw, page_size)
        print(f"page {pageno}: type={info.get('type_name')} "
              f"ncell={info.get('ncell')} content_start="
              f"{info.get('content_start')} zero%={zr[0]*100:.1f}")

def mode_dump(path, root=None, repair=True, columns=None, flat=None,
              out=None):
    buf = open(path, "rb").read()
    if len(buf) < 100 or buf[:16] != b"SQLite format 3\x00":
        print("not a sqlite file header; try 'scan'", file=sys.stderr)
        sys.exit(2)
    page_size = int.from_bytes(buf[16:18], "big")
    enc = {1: "utf-8", 2: "utf-16-le", 3: "utf-16-be"}.get(
        int.from_bytes(buf[56:60], "big"), "utf-8")
    schema = find_schema_rows(buf, page_size, enc, repair=repair)
    tables = [s for s in schema if s[0] == "table" and s[1] != "sqlite_sequence"]
    colinfo = {}
    for t in tables:
        cols = parse_create_sql(t[4])
        colinfo[t[1]] = (t[5], cols)      # name -> (rootpage, cols)
    roots = []
    if root is not None:
        roots = [(columns or "root", root)]
    elif tables:
        for name, (rp, cols) in colinfo.items():
            roots.append((name, rp))
    else:
        print("no usable schema; supply --root N (and --columns)", file=sys.stderr)
        sys.exit(3)
    result = {}
    for name, rp in roots:
        rows = walk_table(buf, rp, page_size, enc, repair=repair)
        try:
            rows.sort(key=lambda r: r[0] if isinstance(r[0], int)
                      else 2 ** 32)
        except Exception:
            pass
        names = None
        if colinfo.get(name):
            names = [c[0] for c in colinfo[name][1]]
        elif isinstance(columns, str):
            names = columns.split(",")
        result[name] = []
        flatkeys = flat.split(",") if isinstance(flat, str) else None
        for rowid, values, serials, note in rows:
            if note == "index":
                if not isinstance(out, str):
                    print(json.dumps({"__index_page__": values[0]}))
                continue
            rec = None
            if flatkeys:
                if isinstance(values, list) and len(values) == len(flatkeys):
                    rec = {k: v for k, v in zip(flatkeys, values)}
            elif names and isinstance(values, list):
                if len(names) == len(values):
                    rec = {k: v for k, v in zip(names, values)}
            if rec is None and not flatkeys:
                rec = {"__raw__": values}
            if rec is None:
                sys.stderr.write(
                    f"[warn] table {name}: row values do not match flat keys"
                    f" {flatkeys} -> {values}\n")
                continue
            if note != "ok":
                sys.stderr.write(
                    f"[note] {name}: row {values!r} <- {note}\n")
            result[name].append(rec)
    # output: single table + flat keys -> bare list (the deliverable shape);
    # otherwise a {table: rows} object.
    if flatkeys and len(result) == 1:
        payload = next(iter(result.values()))
    else:
        payload = result
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if isinstance(out, str):
        with open(out, "w") as f:
            f.write(text + "\n")
        sys.stderr.write(
            f"[out] wrote {len(text.splitlines())} lines to {out}\n")
    else:
        print(text)

def mode_scan(path, encoding="utf-8", min_str=4, max_off=None,
              contains=None):
    """Scan every offset for self-consistent records with plausible text.
    ``contains`` (optional) keeps only records where some text value
    contains the given substring: a strong filter against spurious
    mid-cell parses (use the family's known key pattern, e.g. "testword")."""
    buf = open(path, "rb").read()
    hits = 0
    n = len(buf) if max_off is None else min(max_off, len(buf))
    i = 0
    while i < n:
        try:
            hsz, j0 = get_varint(buf, i)
        except Exception:
            i += 1
            continue
        if hsz < 1:
            i += 1
            continue
        header_end = i + hsz
        j = j0
        serials = []
        try:
            while j < header_end:
                st, j = get_varint(buf, j)
                serials.append(st)
        except Exception:
            i += 1
            continue
        if j != header_end or not serials:
            i += 1
            continue
        vals = []
        k = j
        ok = True
        for st in serials:
            try:
                L = serial_len(st)
            except Exception:
                ok = False
                break
            if k + L > len(buf):
                ok = False
                break
            rawv = buf[k:k + L]
            k += L
            if serial_is_text(st):
                if not plausible_text(rawv, encoding):
                    ok = False
                    break
                vals.append(decode_text(rawv, encoding))
            else:
                vals.append(decode_value(st, rawv, encoding))
        if not ok:
            i += 1
            continue
        # require at least one plausible text column with min length
        if not any(isinstance(v, str) and len(v) >= min_str for v in vals):
            i += 1
            continue
        if contains is not None and not any(
                isinstance(v, str) and contains in v for v in vals):
            i += 1
            continue
        hits += 1
        print(f"0x{i:05x} ({i}): {json.dumps(vals, ensure_ascii=False)}")
        i = k - 1                # skip this record's span (dedupe)
        if hits >= 5000:
            print("...>5000 hits; restrict via max_off/min-str if needed")
            break
    print(f"# hits: {hits}")

def mode_verify(path, flat=None, out=None, repair=True, **ignored):
    """Recover schema + rows, rebuild, byte-diff, report verdict.
    Returns exit code 0 (proven) / 1 (unexplained) / 2 (bad file)
    / 3 (no tables)."""
    buf = open(path, "rb").read()
    if len(buf) < 100 or buf[:16] != b"SQLite format 3\x00":
        sys.stderr.write("not a sqlite file header; nothing to verify\n")
        return 2
    page_size = int.from_bytes(buf[16:18], "big")
    enc = {1: "utf-8", 2: "utf-16-le", 3: "utf-16-be"}.get(
        int.from_bytes(buf[56:60], "big"), "utf-8")
    utf16 = enc in ("utf-16-le", "utf-16-be")
    if utf16:
        sys.stderr.write(
            "[note] database text encoding is UTF-16: a rebuild would "
            "change the storage encoding, so the byte-level regen verdict "
            "does not apply. Rows are still gated by the record oracles; "
            "validate keys/counts via `dump` and deliver.\n")
    schema = find_schema_rows(buf, page_size, enc, repair=repair)
    tables = [s for s in schema
              if s[0] == "table" and s[1] != "sqlite_sequence"]
    colinfo = {}
    for t in tables:
        cols = parse_create_sql(t[4])
        if cols:
            colinfo[t[1]] = (t[5], cols, t[4])   # name -> (root, cols, sql)
    if not colinfo:
        sys.stderr.write("no recoverable user tables; fall back to "
                         "dump/scan/info and the hypothesis workflow\n")
        return 3
    flatkeys = flat.split(",") if isinstance(flat, str) else None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import regen_check as rc
    except Exception:
        rc = None
        sys.stderr.write("regen_check.py not importable\n")
    overall = 0
    deliver = {}
    for name, (rootp, cols, sql_txt) in colinfo.items():
        names = [c[0] for c in cols]
        rows = walk_table(buf, rootp, page_size, enc, repair=repair)
        try:
            rows.sort(key=lambda r: r[0] if isinstance(r[0], int)
                      else 2 ** 32)
        except Exception:
            pass
        rowlists = []
        records = []
        for rowid, values, serials, note in rows:
            if note == "index" or not isinstance(values, list):
                continue
            if note != "ok":
                sys.stderr.write(f"[note] {name}: {values!r} <- {note}\n")
            if len(values) != len(cols):
                sys.stderr.write(
                    f"[warn] {name}: row {values!r} carries {len(values)} "
                    f"values vs schema {len(cols)} columns (rowid alias?) - "
                    f"row excluded from regeneration\n")
                continue
            rowlists.append([
                bytes(v) if isinstance(v, list) and v
                else v for v in values])
            if flatkeys and len(flatkeys) == len(values):
                records.append({k: v for k, v in zip(flatkeys, values)})
            else:
                records.append({k: v for k, v in zip(names, values)})
        print(f"--- table {name}: {len(rowlists)} rows / {len(cols)} "
              f"columns / root page {rootp}")
        if rc is not None and not utf16:
            overall = max(overall, rc.run(path, rowlists, sql_txt, name))
        elif rc is None:
            overall = 1
        deliver[name] = records
    if isinstance(out, str):
        payload = (next(iter(deliver.values()))
                   if flatkeys and len(deliver) == 1 else deliver)
        with open(out, "w") as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        sys.stderr.write(f"[out] wrote {out}\n")
    return overall


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help") or (
            len(args) >= 2 and args[1] in ("-h", "--help", "help")):
        print(__doc__)
        sys.exit(0)
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    path, mode = args[0], args[1]
    if mode == "info":
        return mode_info(path)
    kwargs = {}
    i = 2
    while i < len(args):
        a = args[i]
        if a == "--no-repair":
            kwargs["repair"] = False
        elif a == "--root":
            kwargs["root"] = int(args[i + 1]); i += 1
        elif a == "--columns":
            kwargs["columns"] = args[i + 1]; i += 1
        elif a == "--utf16":
            kwargs["encoding"] = "utf-16-le"
        elif a == "--min-str":
            kwargs["min_str"] = int(args[i + 1]); i += 1
        elif a == "--contains":
            kwargs["contains"] = args[i + 1]; i += 1
        elif a == "--flat":
            kwargs["flat"] = args[i + 1]; i += 1
        elif a == "--out":
            kwargs["out"] = args[i + 1]; i += 1
        i += 1
    if mode == "dump":
        return mode_dump(path, **kwargs)
    if mode == "scan":
        return mode_scan(path, **kwargs)
    if mode == "verify":
        return mode_verify(path, **kwargs)
    print("unknown mode", mode)
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    sys.exit(main() or 0)