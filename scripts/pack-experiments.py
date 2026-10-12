#!/usr/bin/env python3
"""Rebuild verified trajectory archives; --prune removes verified source copies.

Before rebuilding an existing release, restore all trajectories with
`python3 scripts/unpack-experiments.py --all`. Retained example trajectories,
metadata, scores, and frozen Skills are never pruned.
"""

import argparse
import gzip
import importlib.util
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile

REPOSITORY = Path(__file__).resolve().parent.parent
ARCHIVES = REPOSITORY / "experiments/archives"
GROUPS = {
    "main-qwen": "experiments/main/qwen",
    "cross-model-deepseek": "experiments/cross-model/deepseek",
    "cross-model-kimi": "experiments/cross-model/kimi",
    "review-g5": "experiments/review-intervals/g5",
    "review-g20": "experiments/review-intervals/g20",
}
RETAINED = (
    "experiments/main/qwen/fixed-window-ssl/r1/html-finance-verify/",
    "experiments/main/qwen/issue-guided-ssl/r1/html-finance-verify/",
)
LIMIT = 95 * 1048576
spec = importlib.util.spec_from_file_location("unpack_experiments", REPOSITORY / "scripts/unpack-experiments.py")
unpack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(unpack)


def inventory():
    result = []
    for path in sorted((REPOSITORY / "experiments").rglob("*.jsonl")):
        name = path.relative_to(REPOSITORY).as_posix()
        unpack.checked_path(REPOSITORY, name)
        if not path.is_file():
            raise ValueError(f"Expected regular trajectory file: {path}")
        with path.open("rb") as stream:
            checksum = unpack.digest(stream)
        result.append({"path": name, "size": path.stat().st_size, "sha256": checksum})
    if not result:
        raise ValueError("No trajectories found; restore --all before rebuilding")
    manifest_path = ARCHIVES / "manifest.json"
    if manifest_path.exists():
        old = unpack.load_manifest(manifest_path)
        expected = old["retained_files"] + [item for group in old["groups"]
                    for archive in group["archives"] for item in archive["files"]]
        if sorted(expected, key=lambda item: item["path"]) != result:
            raise ValueError("Trajectory inventory differs from the release manifest; restore --all first")
    return result


def make_archive(name, files):
    target = ARCHIVES / f"{name}.tar.gz"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=ARCHIVES, delete=False) as raw:
            temporary = Path(raw.name)
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as bundle:
                    for item in files:
                        source = unpack.checked_path(REPOSITORY, item["path"])
                        member = tarfile.TarInfo(item["path"])
                        member.size = item["size"]
                        member.mode = 0o644
                        with source.open("rb") as stream:
                            bundle.addfile(member, stream)
        with temporary.open("rb") as stream:
            checksum = unpack.digest(stream)
        archive = {"path": temporary.relative_to(REPOSITORY).as_posix(),
                   "size": temporary.stat().st_size, "sha256": checksum, "files": files}
        unpack.verify_archive(REPOSITORY, archive)
        if archive["size"] >= LIMIT:
            return None
        temporary.replace(target)
        temporary = None
        archive["path"] = target.relative_to(REPOSITORY).as_posix()
        return archive
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def split_key(group, name, replicate=False):
    parts = PurePosixPath(name).parts
    if group == "main-qwen":
        return f"{parts[3]}-{parts[4]}" if replicate else parts[3]
    if group.startswith("cross-model-"):
        return f"{parts[4]}-{parts[3]}" if replicate else parts[4]
    return parts[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prune", action="store_true", help="remove sources only after byte verification")
    arguments = parser.parse_args()
    all_files = inventory()
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    retained = [item for item in all_files if item["path"].startswith(RETAINED)]
    grouped = []
    archived = []
    for identifier, prefix in GROUPS.items():
        files = [item for item in all_files if item["path"].startswith(prefix + "/") and item not in retained]
        archive = make_archive(identifier, files)
        if archive is None:
            pieces = {}
            for item in files:
                pieces.setdefault(split_key(identifier, item["path"]), []).append(item)
            archives = []
            for key, members in sorted(pieces.items()):
                archive = make_archive(f"{identifier}--{key}", members)
                if archive is None:
                    replicates = {}
                    for item in members:
                        replicates.setdefault(split_key(identifier, item["path"], replicate=True), []).append(item)
                    for replicate, trajectories in sorted(replicates.items()):
                        archive = make_archive(f"{identifier}--{replicate}", trajectories)
                        if archive is None:
                            raise ValueError(f"Split archive {identifier}--{replicate} still reaches 95 MiB")
                        archives.append(archive)
                else:
                    archives.append(archive)
        else:
            archives = [archive]
        total = sum(archive["size"] for archive in archives)
        original = sum(item["size"] for item in files)
        print(f"{identifier}: {len(files)} files, {original / 1048576:.2f} -> {total / 1048576:.2f} MiB", flush=True)
        grouped.append({"id": identifier, "path_prefix": prefix, "file_count": len(files),
                        "original_bytes": original, "archives": archives})
        archived.extend(files)
    if {item["path"] for item in all_files} != {item["path"] for item in archived + retained}:
        raise ValueError("Some trajectory paths do not belong to a known group")
    manifest_path = ARCHIVES / "manifest.json"
    previous = unpack.load_manifest(manifest_path) if manifest_path.exists() else None
    source_commit = (previous["source_commit"] if previous
                     else subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True).strip())
    manifest = {"schema_version": 1, "source_commit": source_commit,
                "compression": "gzip", "path_root": "repository",
                "groups": grouped, "retained_files": retained}
    # Recheck every original before writing the manifest or deleting any source.
    for item in all_files:
        with unpack.checked_path(REPOSITORY, item["path"]).open("rb") as stream:
            if unpack.digest(stream) != item["sha256"]:
                raise ValueError(f"Source changed while archiving: {item['path']}")
    with tempfile.NamedTemporaryFile(mode="w", dir=ARCHIVES, encoding="utf-8", delete=False) as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
        output.write("\n")
        temporary_manifest = Path(output.name)
    temporary_manifest.replace(manifest_path)
    if previous:
        current_paths = {archive["path"] for group in grouped for archive in group["archives"]}
        old_paths = {archive["path"] for group in previous["groups"] for archive in group["archives"]}
        for name in sorted(old_paths - current_paths):
            unpack.checked_path(REPOSITORY, name).unlink()
    if arguments.prune:
        for item in archived:
            unpack.checked_path(REPOSITORY, item["path"]).unlink()
        for directory in sorted({(REPOSITORY / item["path"]).parent for item in archived}):
            if directory.name in {"heldout", "train", "skill-formation"} and not any(directory.iterdir()):
                directory.rmdir()
        print(f"Pruned {len(archived)} verified trajectories; retained {len(retained)} example files.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, tarfile.TarError) as error:
        raise SystemExit(f"Error: {error}")
