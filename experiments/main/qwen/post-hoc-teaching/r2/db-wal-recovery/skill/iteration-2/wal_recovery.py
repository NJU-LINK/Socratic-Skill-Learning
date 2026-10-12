#!/usr/bin/env python3
"""SQLite WAL Recovery Tool"""
import struct, sys, os, json, sqlite3, shutil, base64, argparse

WAL_MAGIC_V1 = 0x377F0682
WAL_MAGIC_V2 = 0x377F0683
WAL_HEADER_SIZE = 32
WAL_FRAME_HEADER_SIZE = 24

def read_file(path):
    with open(path, 'rb') as f: return f.read()

def write_file(path, data):
    with open(path, 'wb') as f: f.write(data)

def check_wal_magic(data):
    if len(data) < 4: return None
    magic = struct.unpack('>I', data[:4])[0]
    return magic if magic in (WAL_MAGIC_V1, WAL_MAGIC_V2) else None

def detect_and_reverse_encoding(data):
    if check_wal_magic(data): return data, "none"
    # base64
    try:
        b64 = base64.b64decode(data.strip())
        if check_wal_magic(b64): return b64, "base64"
        for key in range(1, 256):
            result = bytes([b ^ key for b in b64])
            if check_wal_magic(result): return result, f"base64+xor(0x{key:02x})"
    except: pass
    # single-byte XOR
    for key in range(1, 256):
        result = bytes([b ^ key for b in data])
        if check_wal_magic(result): return result, f"xor(0x{key:02x})"
    # bit inversion
    result = bytes([(~b) & 0xFF for b in data])
    if check_wal_magic(result): return result, "bit_invert"
    # byte swap 16
    r = bytearray(len(data))
    for i in range(0, len(data)-1, 2): r[i]=data[i+1]; r[i+1]=data[i]
    if len(data)%2: r[-1]=data[-1]
    if check_wal_magic(bytes(r)): return bytes(r), "byte_swap_16"
    # byte swap 32
    r = bytearray(len(data))
    for i in range(0, len(data)-3, 4): r[i:i+4]=data[i:i+4][::-1]
    rem = len(data)%4
    if rem: r[-rem:]=data[-rem:]
    if check_wal_magic(bytes(r)): return bytes(r), "byte_swap_32"
    # combinations
    for key in range(1, 256):
        xored = bytes([b ^ key for b in data])
        r = bytearray(len(xored))
        for i in range(0, len(xored)-1, 2): r[i]=xored[i+1]; r[i+1]=xored[i]
        if len(xored)%2: r[-1]=xored[-1]
        if check_wal_magic(bytes(r)): return bytes(r), f"xor(0x{key:02x})+byte_swap_16"
    return None, None

def wal_checksum(data, use_le=True, init_s0=0, init_s1=0):
    s0, s1 = init_s0 & 0xFFFFFFFF, init_s1 & 0xFFFFFFFF
    n = len(data) // 8 * 8
    if use_le:
        for i in range(0, n, 8):
            x = struct.unpack('<I', data[i:i+4])[0]
            y = struct.unpack('<I', data[i+4:i+8])[0]
            s0 = (s0 + x + s1) & 0xFFFFFFFF
            s1 = (s1 + y + s0) & 0xFFFFFFFF
    else:
        for i in range(0, n, 8):
            x = struct.unpack('>I', data[i:i+4])[0]
            y = struct.unpack('>I', data[i+4:i+8])[0]
            s0 = (s0 + x + s1) & 0xFFFFFFFF
            s1 = (s1 + y + s0) & 0xFFFFFFFF
    return s0, s1

def parse_wal_header(data):
    if len(data) < WAL_HEADER_SIZE: return None
    magic = struct.unpack('>I', data[0:4])[0]
    if magic not in (WAL_MAGIC_V1, WAL_MAGIC_V2): return None
    return {
        'magic': magic, 'version': struct.unpack('>I', data[4:8])[0],
        'page_size': struct.unpack('>I', data[8:12])[0],
        'checkpoint_seq': struct.unpack('>I', data[12:16])[0],
        'salt1': struct.unpack('>I', data[16:20])[0],
        'salt2': struct.unpack('>I', data[20:24])[0],
        'checksum1': struct.unpack('>I', data[24:28])[0],
        'checksum2': struct.unpack('>I', data[28:32])[0],
    }

def determine_checksum_byte_order(data, header):
    header_data = data[:24]
    s0_le, s1_le = wal_checksum(header_data, use_le=True)
    if s0_le == header['checksum1'] and s1_le == header['checksum2']: return True
    s0_be, s1_be = wal_checksum(header_data, use_le=False)
    if s0_be == header['checksum1'] and s1_be == header['checksum2']: return False
    return True  # default

def parse_all_frames(data, page_size):
    """Parse frames using given page_size (may differ from header)."""
    frame_size = WAL_FRAME_HEADER_SIZE + page_size
    frames = []
    offset = WAL_HEADER_SIZE
    while offset + frame_size <= len(data):
        pn = struct.unpack('>I', data[offset:offset+4])[0]
        ds = struct.unpack('>I', data[offset+4:offset+8])[0]
        s1 = struct.unpack('>I', data[offset+8:offset+12])[0]
        s2 = struct.unpack('>I', data[offset+12:offset+16])[0]
        c1 = struct.unpack('>I', data[offset+16:offset+20])[0]
        c2 = struct.unpack('>I', data[offset+20:offset+24])[0]
        pd = data[offset+WAL_FRAME_HEADER_SIZE:offset+frame_size]
        frames.append({'page_number':pn,'db_size':ds,'salt1':s1,'salt2':s2,
                       'checksum1':c1,'checksum2':c2,'page_data':pd})
        offset += frame_size
    return frames

def validate_frames(frames, header, use_le):
    """Check if frames have valid checksums with given byte order."""
    if not frames: return False
    # Check header checksum
    header_data = b''  # We'll just check frame checksums
    # Compute expected header checksum
    hdr_raw = struct.pack('>IIIIII', header['magic'], header['version'],
        header['page_size'], header['checkpoint_seq'], header['salt1'], header['salt2'])
    hs0, hs1 = wal_checksum(hdr_raw, use_le=use_le)
    
    # Check first frame checksum (chained from header)
    fh = frames[0]
    fh_prefix = struct.pack('>II', fh['page_number'], fh['db_size'])
    check_data = fh_prefix + fh['page_data']
    s0, s1 = wal_checksum(check_data, use_le=use_le, init_s0=hs0, init_s1=hs1)
    
    # Allow salt mismatch (we'll fix that) but checksum must be close
    # Actually, if page_size is wrong, the checksum will be completely wrong
    # So we just check if the checksum matches
    return s0 == fh['checksum1'] and s1 == fh['checksum2']

def rebuild_wal(header, frames, use_le=True):
    hdr_data = struct.pack('>IIIIII', header['magic'], header['version'],
        header['page_size'], header['checkpoint_seq'], header['salt1'], header['salt2'])
    s0, s1 = wal_checksum(hdr_data, use_le=use_le)
    result = bytearray(hdr_data + struct.pack('>II', s0, s1))
    ps0, ps1 = s0, s1
    for fh in frames:
        if fh['page_number'] < 1: continue
        fh_prefix = struct.pack('>II', fh['page_number'], fh['db_size'])
        check_data = fh_prefix + fh['page_data']
        s0, s1 = wal_checksum(check_data, use_le=use_le, init_s0=ps0, init_s1=ps1)
        ps0, ps1 = s0, s1
        frame_hdr = struct.pack('>IIIIII', fh['page_number'], fh['db_size'],
            fh['salt1'], fh['salt2'], s0, s1)
        result.extend(frame_hdr)
        result.extend(fh['page_data'])
    return bytes(result)

def get_db_page_size(db_path):
    with open(db_path, 'rb') as f: header = f.read(100)
    if len(header) < 18: return 4096
    ps = struct.unpack('>H', header[16:18])[0]
    return 65536 if ps == 1 else ps

def apply_wal_to_db(db_path, wal_data):
    wal_path = db_path + '-wal'
    for p in [wal_path, db_path + '-shm']:
        if os.path.exists(p): os.remove(p)
    write_file(wal_path, wal_data)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=wal;")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.close()
        return True
    except Exception as e:
        print(f"  SQLite checkpoint failed: {e}")
        return False

def get_final_db_size(frames):
    """
    Extract final database size from the last commit frame.
    
    Frame db_size semantics:
    - db_size = 0: non-commit frame (intermediate write within transaction)
    - db_size > 0: commit frame (total pages in database after this transaction)
    
    The last commit frame's db_size is the authoritative final database size.
    This is how SQLite itself determines database size when reading a WAL.
    """
    final_size = 0
    for f in frames:
        if f['db_size'] > 0:
            final_size = f['db_size']
    return final_size

def apply_pages_manually(db_path, frames, page_size, final_db_size=None):
    """
    Manually apply WAL frames to database file.
    
    Uses db_size from commit frames to determine final database size,
    not max(page_number), which can be wrong if pages were freed.
    """
    if final_db_size is None:
        final_db_size = get_final_db_size(frames)
    
    # Collect the LAST version of each page (frames are in WAL order)
    page_updates = {}
    for fh in frames:
        page_updates[fh['page_number']] = fh['page_data']
    
    # Determine if we're creating from scratch or patching
    if os.path.exists(db_path):
        db_data = bytearray(read_file(db_path))
        db_pages = len(db_data) // page_size
    else:
        # No base DB — create empty database of the right size
        db_data = bytearray(final_db_size * page_size)
        db_pages = 0
    
    # Apply page updates, but only for pages within final_db_size
    for pn, pd in page_updates.items():
        if pn < 1 or pn > final_db_size:
            continue  # skip pages outside final database (freed pages)
        offset = (pn - 1) * page_size
        # Extend if needed
        if offset + page_size > len(db_data):
            db_data.extend(b'\x00' * (offset + page_size - len(db_data)))
        db_data[offset:offset+page_size] = pd
    
    # Fix SQLite header fields if we have page 1
    if len(db_data) >= 100:
        # Offset 24: change counter — increment to force schema reload
        old_cc = struct.unpack('>I', db_data[24:28])[0]
        struct.pack_into('>I', db_data, 24, old_cc + 1)
        # Offset 28: database size in pages
        struct.pack_into('>I', db_data, 28, final_db_size)
        # Offset 32-35: first freelist trunk page — clear if we added pages
        struct.pack_into('>I', db_data, 32, 0)
        # Offset 36-39: total freelist pages — clear
        struct.pack_into('>I', db_data, 36, 0)
        # Offset 92-95: version-valid-for — match change counter
        struct.pack_into('>I', db_data, 92, old_cc + 1)
    
    write_file(db_path, bytes(db_data))
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=DELETE;")
        conn.close()
        return True
    except: return False

def extract_data(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = [r[0] for r in c.fetchall()]
    all_data = {}
    for t in tables:
        c.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in c.fetchall()]
        c.execute(f"SELECT * FROM {t}")
        all_data[t] = [{cols[i]: row[i] for i in range(len(cols))} for row in c.fetchall()]
    conn.close()
    return all_data, tables

def format_output(all_data, tables):
    dt = [t for t in tables if not t.startswith('sqlite_')]
    if len(dt) == 1:
        recs = all_data[dt[0]]
        if recs and 'id' in recs[0]: recs.sort(key=lambda r: r['id'])
        return recs
    else:
        result = {}
        for t in dt:
            recs = all_data[t]
            if recs and 'id' in recs[0]: recs.sort(key=lambda r: r['id'])
            result[t] = recs
        return result

def recover(db_path=None, wal_path=None, output_path=None, work_dir='/app'):
    if db_path is None or wal_path is None:
        dbs, wals = [], []
        for f in sorted(os.listdir(work_dir)):
            fp = os.path.join(work_dir, f)
            if not os.path.isfile(fp): continue
            if f.endswith('.db') and not f.endswith('-wal') and not f.endswith('-shm') and not f.endswith('-journal'):
                dbs.append(fp)
            if f.endswith('.db-wal') or (f.endswith('-wal') and not f.endswith('-shm')):
                wals.append(fp)
        if db_path is None:
            if not dbs:
                # No database file found - will reconstruct from WAL alone
                print("No database file found, will reconstruct from WAL")
                db_path = os.path.join(work_dir, 'reconstructed.db')
            else:
                db_path = dbs[0]
        if wal_path is None:
            if not wals:
                print("No WAL. Extracting base data only.")
                all_data, tables = extract_data(db_path)
                result = format_output(all_data, tables)
                if output_path: write_file(output_path, json.dumps(result, indent=2, default=str).encode())
                else: print(json.dumps(result, indent=2, default=str))
                return True
            wal_path = wals[0]
    if output_path is None: output_path = os.path.join(work_dir, 'recovered.json')
    
    print(f"DB: {db_path}, WAL: {wal_path}")
    
    # Handle case where database doesn't exist (no base DB)
    if not os.path.exists(db_path):
        print("No base database found, will reconstruct from WAL")
        # We'll get page_size from WAL header after decoding
        db_page_size = None
    else:
        db_page_size = get_db_page_size(db_path)
        print(f"DB page size: {db_page_size}")
    
    # Decode
    raw = read_file(wal_path)
    print(f"Raw WAL: {len(raw)} bytes")
    decoded, encoding = detect_and_reverse_encoding(raw)
    if decoded is None: print("ERROR: Cannot decode WAL"); return False
    print(f"Encoding: {encoding}, decoded: {len(decoded)} bytes")
    
    # Parse header
    header = parse_wal_header(decoded)
    if header is None: print("ERROR: Invalid WAL header"); return False
    use_le = determine_checksum_byte_order(decoded, header)
    print(f"Checksum order: {'LE' if use_le else 'BE'}")
    
    # If no base DB, use WAL header's page_size
    if db_page_size is None:
        db_page_size = header['page_size']
        print(f"Using WAL page_size: {db_page_size}")
    
    # Try parsing frames with header's page_size
    wal_page_size = header['page_size']
    frames = parse_all_frames(decoded, wal_page_size)
    print(f"Frames (page_size={wal_page_size}): {len(frames)}")
    
    # If page size doesn't match DB, try with DB page size
    if wal_page_size != db_page_size:
        print(f"WAL page_size ({wal_page_size}) != DB page_size ({db_page_size})")
        db_frames = parse_all_frames(decoded, db_page_size)
        print(f"Frames (page_size={db_page_size}): {len(db_frames)}")
        
        # Validate which set of frames is correct
        header_valid = validate_frames(frames, header, use_le)
        db_frames_valid = validate_frames(db_frames, header, use_le)
        
        if not header_valid and db_frames_valid:
            print(f"Using DB page_size ({db_page_size}) for frame parsing")
            frames = db_frames
            header['page_size'] = db_page_size
        elif header_valid:
            print(f"Header page_size ({wal_page_size}) produces valid frames, using it")
        else:
            # Neither validates; try DB page size as best guess
            print(f"Neither page size validates; using DB page_size ({db_page_size})")
            frames = db_frames
            header['page_size'] = db_page_size
    
    for f in frames:
        print(f"  page={f['page_number']}, db_size={f['db_size']}")
    
    # Extract final database size from last commit frame
    final_db_size = get_final_db_size(frames)
    print(f"Final db_size from WAL: {final_db_size} pages")
    
    # Repair: fix salts and rebuild checksums
    for f in frames:
        f['salt1'] = header['salt1']
        f['salt2'] = header['salt2']
    repaired = rebuild_wal(header, frames, use_le=use_le)
    print(f"Rebuilt WAL: {len(repaired)} bytes")
    
    # Apply
    work_db = db_path + '.recovery_tmp'
    has_base_db = os.path.exists(db_path)
    
    if has_base_db:
        shutil.copy2(db_path, work_db)
        for s in ['-wal','-shm','-journal']:
            p = work_db + s
            if os.path.exists(p): os.remove(p)
        
        success = apply_wal_to_db(work_db, repaired)
        if not success:
            print("Trying manual apply...")
            shutil.copy2(db_path, work_db)
            for s in ['-wal','-shm','-journal']:
                p = work_db + s
                if os.path.exists(p): os.remove(p)
            success = apply_pages_manually(work_db, frames, header['page_size'], final_db_size)
    else:
        # No base DB — must reconstruct from WAL frames
        print("Reconstructing database from WAL frames...")
        success = apply_pages_manually(work_db, frames, header['page_size'], final_db_size)
    
    if not success:
        print("ERROR: Apply failed")
        return False
    
    # Extract
    all_data, tables = extract_data(work_db)
    total = sum(len(v) for v in all_data.values())
    print(f"Records: {total}")
    for t in tables: print(f"  {t}: {len(all_data[t])}")
    
    # Output
    result = format_output(all_data, tables)
    write_file(output_path, json.dumps(result, indent=2, default=str).encode())
    print(f"Output: {output_path}")
    
    # Update original
    shutil.copy2(work_db, db_path)
    for s in ['-wal','-shm','-journal']:
        for p in [db_path+s, work_db+s]:
            if os.path.exists(p): os.remove(p)
    if os.path.exists(work_db): os.remove(work_db)
    print("Done!")
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', help='DB path')
    parser.add_argument('--wal', help='WAL path')
    parser.add_argument('--output', '-o', help='Output JSON')
    parser.add_argument('--dir', '-d', default='/app')
    args = parser.parse_args()
    ok = recover(args.db, args.wal, args.output, args.dir)
    sys.exit(0 if ok else 1)
