#!/usr/bin/env python3
"""Copy generated documents to deterministic, semantically opaque filenames."""

import hashlib
import sys
from pathlib import Path


NAME_SALT = "financial-document-processor-v2"


def opaque_name(original_name: str) -> str:
    original = Path(original_name)
    digest = hashlib.sha256(
        f"{NAME_SALT}\0{original.name}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{digest}{original.suffix.lower()}"


def randomize_directory(source_dir: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()

    for source in sorted(source_dir.iterdir()):
        if not source.is_file():
            continue
        name = opaque_name(source.name)
        if name in names:
            raise RuntimeError(f"opaque filename collision: {name}")
        names.add(name)
        (destination_dir / name).write_bytes(source.read_bytes())


if __name__ == "__main__":
    if len(sys.argv) == 3:
        source = Path(sys.argv[1])
        destination = Path(sys.argv[2])
    elif len(sys.argv) == 1:
        source = Path("/tmp/original_documents")
        destination = Path("/app/documents")
    else:
        raise SystemExit("usage: randomize_filenames.py [SOURCE_DIR DESTINATION_DIR]")

    randomize_directory(source, destination)
