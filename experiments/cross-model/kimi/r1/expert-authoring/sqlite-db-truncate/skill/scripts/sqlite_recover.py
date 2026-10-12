#!/usr/bin/env python3
"""Generic damaged-SQLite recovery helper.

Two complementary strategies (use both, merge results):

  1. Page scan (default): parse every page as a potential table b-tree leaf
     (type 0x0d) and decode each cell with strict validation. Works even when
     interior pages, the sqlite_master page, freelist links, or the 100-byte
     file header are damaged, because leaves are self-describing.
     Cells that fail strict validation are retried with every possible
     single-bit repair of their record header (targets random-bit-flip damage).

  2. Signature carve (--carve REGEX): find byte patterns (e.g. known key
     prefixes like 'testword') anywhere in the file -- including free space,
     freelist pages and truncated tails -- then search backwards a few bytes
     for a record start that strictly validates with a text field covering
     the match.

Usage:
  python3 sqlite_recover.py FILE
  python3 sqlite_recover.py FILE --carve testword
  python3 sqlite_recover.py FILE --page-size 4096 --encoding utf-8

Output: JSON lines to stdout, one per recovered record:
  {"src": "page2/cell3", "offset": 8176, "rowid": 5, "values": [...], "repaired": false}
The agent must still map columns to the case's JSON schema and write the
required output file itself.
"""
import argparse
import json
import re
import struct
import sys

VALID_PAGE_TYPES = {0x02, 0x05, 0x0A, 0x0D}
INT_SIZES = {1: 1, 2: 2, 3: 3, 4: 4, 5: 6, 6: 8}


def read_varint(b, i):
    """SQLite varint: 1-9 bytes, 7 bits/byte big-endian, 9th byte = 8 bits."""
    val = 0
    for k in range(8):
        if i + k >= len(b):
            raise ValueError("varint overruns buffer")
        c = b[i + k]
        val = (val << 7) | (c & 0x7F)
        if not (c & 0x80):
            return val, k + 1
    if i + 8 >= len(b):
        raise ValueError("varint overruns buffer")
    val = (val << 8) | b[i + 8]
    return val, 9


def serial_size(t):
    if t == 0 or t == 8 or t == 9:
        return 0
    if t in INT_SIZES:
        return INT_SIZES[t]
    if t == 7:
        return 8
    if t in (10, 11):
        raise ValueError("reserved serial type")
    return (t - 12) // 2 if t % 2 == 0 else (t - 13) // 2


def decode_value(t, data, encoding):
    if t == 0:
        return None
    if t in INT_SIZES:
        return int.from_bytes(data, "big", signed=True)
    if t == 7:
        return struct.unpack(">d", data)[0]
    if t == 8:
        return 0
    if t == 9:
        return 1
    if t % 2 == 0:  # blob
        return {"_blob_hex": data.hex()}
    return data.decode(encoding)  # raises on invalid -> record rejected


def parse_record(payload, encoding, strict_end=True, partial_ok=False):
    """Parse a record: (header-len varint, serial types..., values...).
    Returns (types, values). Raises if invalid. With partial_ok, returns the
    leading values that are complete (len(values) < len(types) => partial)."""
    hdrlen, n = read_varint(payload, 0)
    if hdrlen < n or hdrlen > len(payload):
        raise ValueError("bad header length")
    types = []
    i = n
    while i < hdrlen:
        t, m = read_varint(payload, i)
        serial_size(t)  # raises for reserved types
        types.append(t)
        i += m
    if i != hdrlen or not types:
        raise ValueError("serial types do not end at header boundary")
    values = []
    j = hdrlen
    for t in types:
        sz = serial_size(t)
        if j + sz > len(payload):
            if partial_ok and values:
                return types, values
            raise ValueError("value overruns payload")
        values.append(decode_value(t, payload[j:j + sz], encoding))
        j += sz
    if strict_end and j != len(payload):
        raise ValueError("payload size mismatch")
    return types, values


def _repair_rank(types, values):
    """Lower is better. Penalize control characters in text and uncommon
    integer widths (3/5/6 bytes) -- hallmarks of a coincidental bad repair."""
    penalty = 0
    for t, v in zip(types, values):
        if isinstance(v, str):
            penalty += 100 * sum(1 for ch in v if (ord(ch) < 32 and ch not in "\t\n\r") or ord(ch) == 127)
        if t in (3, 5):
            penalty += 10
    return penalty


def try_parse_record(payload, encoding, allow_repair=True):
    """Strict parse; on failure retry every single-bit repair of the record
    header region (bit flips in serial types are a common damage). Several
    repairs may coincidentally validate, so rank by plausibility and flag
    ambiguity. Returns (types, values, repair_status) where repair_status is
    None (strict ok), 'ok' (single best repair) or 'AMBIGUOUS' (tie)."""
    try:
        t, v = parse_record(payload, encoding)
        return t, v, None
    except (ValueError, UnicodeDecodeError, struct.error):
        pass
    if not allow_repair or len(payload) > 4096:
        raise ValueError("unparseable record")
    cands = {}
    for pos in range(min(len(payload), 24)):
        for bit in range(8):
            patched = bytearray(payload)
            patched[pos] ^= (1 << bit)
            try:
                t, v = parse_record(bytes(patched), encoding)
            except (ValueError, UnicodeDecodeError, struct.error):
                continue
            key = json.dumps([t, v], sort_keys=True)
            cands.setdefault(key, (_repair_rank(t, v), t, v))
    if not cands:
        raise ValueError("unparseable record")
    best_rank = min(c[0] for c in cands.values())
    best = [c for c in cands.values() if c[0] == best_rank]
    _, t, v = best[0]
    return t, v, ("AMBIGUOUS" if len(best) > 1 else "ok")


def plausible_page_size(data):
    """Page size from header field 16-17; if corrupt, pick the power of two
    that divides the file and puts valid b-tree type bytes at page starts."""
    if len(data) >= 100:
        ps = struct.unpack(">H", data[16:18])[0]
        ps = 65536 if ps == 1 else ps
        if ps in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
            return ps
    best, best_score = 4096, -1.0
    for ps in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
        probes = hits = 0
        for off in range(ps, len(data) - 1, ps):  # skip page 1 (header shift)
            probes += 1
            if data[off] in VALID_PAGE_TYPES:
                hits += 1
        if probes:
            ratio = hits / probes
            # prefer highest ratio; on ties prefer the SMALLER page size
            # (a too-large size also scores perfectly when it divides evenly)
            if ratio > best_score + 1e-9 or (ratio >= best_score - 1e-9 and ps < best):
                best, best_score = ps, ratio
    return best


def page_bytes(data, pageno, ps):
    """1-based page fetch; page content padded with zeros if beyond EOF."""
    start = (pageno - 1) * ps
    chunk = data[start:start + ps]
    return chunk + b"\x00" * (ps - len(chunk))


def parse_leaf_cell(page, off, usable, fetch):
    """Decode a table-leaf cell at page offset `off`. Returns
    (rowid, payload, end_off) following overflow chains when needed."""
    plen, n1 = read_varint(page, off)
    if plen > 0x0FFFFFFF:
        raise ValueError("implausible payload length")
    rowid, n2 = read_varint(page, off + n1)
    hdr = n1 + n2
    x = usable - 35
    if plen <= x:
        payload = page[off + hdr: off + hdr + plen]
    else:
        m = ((usable - 12) * 32) // 255 - 23
        k = m + (plen - m) % (usable - 4)
        local = k if k <= x else m
        payload = bytearray(page[off + hdr: off + hdr + local])
        ovf = int.from_bytes(page[off + hdr + local: off + hdr + local + 4], "big")
        remaining = plen - local
        seen = set()
        while remaining > 0:
            if ovf == 0 or ovf in seen:
                raise ValueError("broken overflow chain")
            seen.add(ovf)
            opg = fetch(ovf)
            ovf = int.from_bytes(opg[0:4], "big")
            take = min(remaining, usable - 4)
            payload += opg[4:4 + take]
            remaining -= take
        payload = bytes(payload)
    if len(payload) != plen:
        raise ValueError("payload truncated")
    return rowid, payload, off + hdr + min(plen, x)


def scan_pages(data, ps, encoding, repair=True):
    """Yield dicts for every strictly-validatable leaf cell in the file."""
    usable = ps  # assumes 0 reserved bytes; adjust here if header byte 20 != 0
    fetch = lambda p: page_bytes(data, p, ps)
    npages = len(data) // ps
    for pno in range(1, npages + 1):
        page = page_bytes(data, pno, ps)
        hdr = 100 if pno == 1 else 0
        if len(page) < hdr + 8 or page[hdr] != 0x0D:
            continue
        ncells = struct.unpack(">H", page[hdr + 3:hdr + 5])[0]
        if hdr + 8 + 2 * ncells > ps:
            continue  # corrupt cell count -> carving will handle this page
        for ci in range(ncells):
            off = struct.unpack(">H", page[hdr + 8 + 2 * ci: hdr + 10 + 2 * ci])[0]
            if off + 2 > ps:
                continue
            rec = {"src": "page%d/cell%d" % (pno, ci), "offset": (pno - 1) * ps + off,
                   "page": pno, "repaired": False}
            try:
                rowid, payload, _ = parse_leaf_cell(page, off, usable, fetch)
                types, values, status = try_parse_record(payload, encoding, repair)
                rec.update(rowid=rowid, types=types, values=values,
                           repaired=bool(status), repair_status=status)
            except (ValueError, UnicodeDecodeError, struct.error) as e:
                rec.update(error=str(e))
            yield rec


def _has_nul(values):
    return any(isinstance(v, str) and "\x00" in v for v in values)


def carve(data, pattern, ps, encoding, max_back=48, repair=True):
    """Find regex matches, walk backwards to a strictly-validating cell start
    whose record contains a text field covering the match. Cell payload is
    fetched page-aware (overflow chains followed), never by raw file slicing."""
    rx = re.compile(pattern if isinstance(pattern, bytes) else pattern.encode())
    fetch = lambda p: page_bytes(data, p, ps)
    out = []
    for match in rx.finditer(data):
        m0 = match.start()
        hit = None
        for start in range(max(0, m0 - max_back), m0 + 1):
            pno = start // ps + 1
            off = start % ps
            if pno == 1 and off < 100:
                continue  # cells on page 1 start after the file header
            page = fetch(pno)
            try:
                rowid, payload, _ = parse_leaf_cell(page, off, ps, fetch)
                try:
                    types, values, status = try_parse_record(payload, encoding, repair)
                except ValueError:
                    # only when the file truly ends inside this cell: keep the
                    # leading values that survive (trailing ones never existed)
                    plen0, n1 = read_varint(data, start)
                    _, n2 = read_varint(data, start + n1)
                    avail = max(0, len(data) - (start + n1 + n2))
                    if avail >= plen0:
                        continue  # failed validation for another reason
                    types, values = parse_record(payload[:avail], encoding,
                                                 strict_end=False, partial_ok=True)
                    status = "partial"
                if _has_nul(values):
                    continue
            except (ValueError, UnicodeDecodeError, struct.error):
                continue
            # the carved record must explain the match: a text field covering
            # m0 within the cell's local (contiguous, same-page) payload bytes
            try:
                hdrlen, _ = read_varint(payload, 0)
                plen, n1 = read_varint(data, start)
                _, n2 = read_varint(data, start + n1)
            except ValueError:
                continue
            page_end = (start // ps + 1) * ps
            pos = start + n1 + n2 + hdrlen
            ok = False
            for t, v in zip(types, values):
                sz = serial_size(t)
                if (isinstance(v, str) and pos <= m0
                        and match.end() <= min(pos + sz, page_end)):
                    ok = True
                pos += sz
            if ok:
                hit = {"src": "carve@%d" % start, "offset": start, "rowid": rowid,
                       "types": types, "values": values,
                       "repaired": bool(status), "repair_status": status}
                break
        out.append(hit if hit else {"src": "carve@%d" % m0, "offset": m0,
                                    "error": "no valid record start found for match"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--carve", help="byte regex of a known key/signature, e.g. 'testword'")
    ap.add_argument("--page-size", type=int, default=None)
    ap.add_argument("--encoding", default=None, help="utf-8 (default), utf-16-le, utf-16-be")
    ap.add_argument("--no-repair", action="store_true", help="disable single-bit header repair")
    args = ap.parse_args()

    data = open(args.file, "rb").read()
    ps = args.page_size or plausible_page_size(data)
    enc = args.encoding
    if enc is None and len(data) >= 60:
        enc = {1: "utf-8", 2: "utf-16-le", 3: "utf-16-be"}.get(
            struct.unpack(">I", data[56:60])[0], "utf-8")
    enc = enc or "utf-8"
    magic_ok = data[:16] == b"SQLite format 3\x00"
    print(json.dumps({"file": args.file, "bytes": len(data), "page_size": ps,
                      "pages_present": len(data) / ps, "encoding": enc,
                      "sqlite_magic_ok": magic_ok,
                      "truncated": len(data) % ps != 0}), file=sys.stderr)

    results = scan_pages(data, ps, enc, repair=not args.no_repair)
    for r in results:
        print(json.dumps(r))
    if args.carve:
        for r in carve(data, args.carve, ps, enc, repair=not args.no_repair):
            r["src"] = "carve:" + r["src"]
            print(json.dumps(r))


if __name__ == "__main__":
    main()
