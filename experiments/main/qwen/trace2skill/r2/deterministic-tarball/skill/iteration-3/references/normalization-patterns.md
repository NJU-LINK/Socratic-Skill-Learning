# Normalization Patterns for Deterministic Archives

## Table of Contents
- Staging Directory Setup
- Embedded Python for .distignore and Normalization
- Python Logic Details

## Staging Directory Setup
```bash
STAGING=$(mktemp -d)
chmod 0755 "$STAGING"
# ... copy and transform files into $STAGING ...
```

## Embedded Python for .distignore and Normalization
Use a Python heredoc inside the bash build script to handle gitignore-style pattern matching, binary-vs-text detection, CRLF→LF conversion, and permission classification. These tasks are error-prone in pure shell but straightforward with Python's `os.walk`, `fnmatch`, and binary I/O.

## Python Logic Details
- **Parse .distignore**: 
  - Trailing `/` = directory pattern.
  - Patterns with `/` (besides trailing) are root-relative.
  - Others match at any level.
  - Strip leading `**/`.
- **Filter directories**: Filter `dirnames` in-place during `os.walk` to prune excluded directories.
- **Binary detection**: Read first 8KB, check for `b'\x00'`.
- **Line endings**: `content.replace(b'\r\n', b'\n').replace(b'\r', b'\n')` for text files only.
- **Permissions**: `0755` if shebang (first 2 bytes == `b'#!'`) or any execute bit set; `0644` otherwise.
- **Exclusions**: Exclude regular files with `(mode & 0o7777) == 0o600`.
