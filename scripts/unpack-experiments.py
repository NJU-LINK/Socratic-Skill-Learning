#!/usr/bin/env python3
"""List or restore archived experiment trajectories using only Python's stdlib."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile
import tempfile

REPOSITORY = Path(__file__).resolve().parent.parent
MANIFEST = REPOSITORY / "experiments/archives/manifest.json"
CHUNK = 1024 * 1024


def digest(stream):
    result = hashlib.sha256()
    while chunk := stream.read(CHUNK):
        result.update(chunk)
    return result.hexdigest()


def checked_path(root, name):
    """Reject absolute/ambiguous paths and existing symlink ancestors."""
    path = PurePosixPath(name)
    if (not name.startswith("experiments/") or str(path) != name
            or ".." in path.parts or "\\" in name or path.is_absolute()):
        raise ValueError(f"Unsafe archive path: {name!r}")
    target = root
    for part in path.parts:
        target /= part
        if target.is_symlink():
            raise ValueError(f"Refusing symlink: {target}")
    return target


def load_manifest(path=MANIFEST):
    with path.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported archive manifest version")
    identifiers = [group["id"] for group in manifest["groups"]]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate group in archive manifest")
    return manifest


def verify_archive(source_root, archive):
    path = checked_path(source_root, archive["path"])
    if not path.is_file() or path.stat().st_size != archive["size"]:
        raise ValueError(f"Missing archive or size mismatch: {path}")
    with path.open("rb") as stream:
        if digest(stream) != archive["sha256"]:
            raise ValueError(f"Archive checksum mismatch: {path}")
    expected = {}
    for item in archive["files"]:
        checked_path(source_root, item["path"])
        if not item["path"].endswith(".jsonl") or item["path"] in expected:
            raise ValueError(f"Invalid or duplicate manifest path: {item['path']}")
        expected[item["path"]] = item
    seen = set()
    with tarfile.open(path, "r:gz") as bundle:
        for member in bundle:
            checked_path(source_root, member.name)
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise ValueError(f"Unexpected archive member: {member.name}")
            item = expected[member.name]
            if member.size != item["size"]:
                raise ValueError(f"Trajectory size mismatch: {member.name}")
            with bundle.extractfile(member) as stream:
                if digest(stream) != item["sha256"]:
                    raise ValueError(f"Trajectory checksum mismatch: {member.name}")
            seen.add(member.name)
    if seen != set(expected):
        raise ValueError(f"Archive is missing manifest files: {path}")


def restore(source_root, destination, archives):
    """Validate every selected archive and collision before creating files."""
    destination = destination.resolve()
    existing = set()
    selected = set()
    for archive in archives:
        verify_archive(source_root, archive)
        for item in archive["files"]:
            name = item["path"]
            if name in selected:
                raise ValueError(f"Duplicate path across selected archives: {name}")
            selected.add(name)
            target = checked_path(destination, name)
            if target.exists():
                if not target.is_file() or target.stat().st_size != item["size"]:
                    raise ValueError(f"Refusing to overwrite different content: {target}")
                with target.open("rb") as stream:
                    if digest(stream) != item["sha256"]:
                        raise ValueError(f"Refusing to overwrite different content: {target}")
                existing.add(name)
    written = 0
    for archive in archives:
        with tarfile.open(checked_path(source_root, archive["path"]), "r:gz") as bundle:
            for member in bundle:
                if member.name in existing:
                    continue
                target = checked_path(destination, member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                # Write to a same-directory temporary file, then link without replacing.
                # A concurrent file creation, including a symlink, cannot be overwritten.
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                        temporary = Path(output.name)
                        with bundle.extractfile(member) as stream:
                            while chunk := stream.read(CHUNK):
                                output.write(chunk)
                    os.chmod(temporary, 0o644)
                    checked_path(destination, member.name)
                    os.link(temporary, target)
                    written += 1
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
    return written, len(existing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--list", action="store_true", help="list available groups and sizes")
    choice.add_argument("--group", action="append", help="restore a named group (repeatable)")
    choice.add_argument("--all", action="store_true", help="restore every archived trajectory")
    parser.add_argument("--destination", type=Path, default=REPOSITORY,
                        help="restore under this directory (default: repository root)")
    arguments = parser.parse_args()
    try:
        manifest = load_manifest()
        groups = manifest["groups"]
        if arguments.list:
            for group in groups:
                total = sum(archive["size"] for archive in group["archives"])
                print(f"{group['id']}: {group['file_count']} files, "
                      f"{total / 1048576:.2f} MiB compressed, "
                      f"{group['original_bytes'] / 1048576:.2f} MiB original")
            print(f"{len(manifest['retained_files'])} example trajectories remain directly readable.")
            return 0
        if arguments.group:
            unknown = set(arguments.group) - {group["id"] for group in groups}
            if unknown:
                raise ValueError(f"Unknown archive group(s): {', '.join(sorted(unknown))}")
            groups = [group for group in groups if group["id"] in arguments.group]
        archives = [archive for group in groups for archive in group["archives"]]
        written, existing = restore(REPOSITORY, arguments.destination, archives)
        print(f"Restored {written} trajectories; {existing} identical files already present.")
        return 0
    except (ValueError, OSError, tarfile.TarError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
