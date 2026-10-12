# SQLite WAL Format Reference

## File Structure

```
+-------------------+
| WAL Header (32B)  |
+-------------------+
| Frame 1 Header    |  24 bytes
| Frame 1 Data      |  page_size bytes
+-------------------+
| Frame 2 Header    |  24 bytes
| Frame 2 Data      |  page_size bytes
+-------------------+
| ...               |
+-------------------+
| Frame N Header    |  24 bytes
| Frame N Data      |  page_size bytes
+-------------------+
```

Total file size = 32 + N * (24 + page_size)

## WAL Header (32 bytes)

| Offset | Size | Field                  | Description                              |
|--------|------|------------------------|------------------------------------------|
| 0      | 4    | Magic Number           | 0x377f0682 (BE) or 0x377f0683 (LE)      |
| 4      | 4    | File Format Version    | Typically 3007000 (SQLite 3.7.0+)       |
| 8      | 4    | Database Page Size     | e.g., 1024, 4096                         |
| 12     | 4    | Checkpoint Sequence    | Incremented on each checkpoint           |
| 16     | 4    | Salt-1                 | Random value, changes per WAL            |
| 20     | 4    | Salt-2                 | Random value, changes per WAL            |
| 24     | 4    | Checksum-1             | Checksum of header bytes 0-23            |
| 28     | 4    | Checksum-2             | (continuation)                           |

## Frame Header (24 bytes)

| Offset | Size | Field                  | Description                              |
|--------|------|------------------------|------------------------------------------|
| 0      | 4    | Page Number            | Which DB page this frame replaces (1-based)|
| 4      | 4    | Database Size          | 0 for non-commit; total pages for commit |
| 8      | 4    | Salt-1                 | Must match WAL header Salt-1             |
| 12     | 4    | Salt-2                 | Must match WAL header Salt-2             |
| 16     | 4    | Checksum-1             | Running checksum                         |
| 20     | 4    | Checksum-2             | (continuation)                           |

## Frame Data

Exactly `page_size` bytes. This is a complete database page that replaces the page at `page_number` in the base database.

## Checksum Algorithm

```
Input: data bytes (must be multiple of 8), initial s1, s2
Process data as big-endian uint32 pairs:
  for each 8-byte chunk (x, y):
    s1 = (s1 + x + y) mod 2^32
    s2 = (s2 + s1) mod 2^32
Output: (s1, s2)
```

**WAL header checksum:** Computed over bytes 0-23 with s1=0, s2=0.

**Frame checksum:** Running checksum. Input is frame header bytes 0-15 concatenated with frame data. Uses the previous checksum values as initial s1, s2 (or the header checksum for the first frame).

## Magic Number Byte Order

- `0x377f0682`: Checksums use big-endian byte order
- `0x377f0683`: Checksums use little-endian byte order

Most implementations use big-endian (0x377f0682).

## Page Size

Must be a power of 2 between 512 and 65536. Common values: 1024, 4096.
Read from the base database header at offset 16-17 (big-endian uint16).
Value 1 means 65536 (SQLite 3.7.1+).

## Checkpoint

When SQLite checkpoints a WAL:
1. All committed frames are written to the main database file
2. The WAL file is truncated or deleted
3. The checkpoint sequence number increments

A TRUNCATE checkpoint resets the WAL to empty state.
A PASSIVE checkpoint writes pages but doesn't reset the WAL.
A FULL checkpoint waits for readers to finish before resetting.
