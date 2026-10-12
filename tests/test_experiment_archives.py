"""Offline tests for verified experiment archive restoration.

Run: python3 -m unittest discover -s tests -p 'test_experiment_archives.py'
"""

import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("unpack_experiments", ROOT / "scripts/unpack-experiments.py")
unpack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(unpack)


class ArchiveRestorationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.source = self.root / "source"
        self.destination = self.root / "destination"
        (self.source / "experiments/archives").mkdir(parents=True)
        self.name = "experiments/main/qwen/fixed-window-ssl/r1/task/train/iteration-1.jsonl"
        self.data = b'{"i":0,"role":"user","text":"example"}\n'

    def archive(self, members=None, records=None):
        if members is None:
            member = tarfile.TarInfo(self.name)
            member.size = len(self.data)
            members = [(member, self.data)]
        path = self.source / "experiments/archives/test.tar.gz"
        with tarfile.open(path, "w:gz") as bundle:
            for member, data in members:
                bundle.addfile(member, io.BytesIO(data) if data is not None else None)
        if records is None:
            records = [{"path": self.name, "size": len(self.data),
                        "sha256": hashlib.sha256(self.data).hexdigest()}]
        return {"path": "experiments/archives/test.tar.gz", "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "files": records}

    def test_round_trip_and_repeat_skip_identical_content(self):
        archive = self.archive()
        self.assertEqual(unpack.restore(self.source, self.destination, [archive]), (1, 0))
        self.assertEqual((self.destination / self.name).read_bytes(), self.data)
        self.assertEqual(unpack.restore(self.source, self.destination, [archive]), (0, 1))

    def test_different_existing_content_blocks_all_writes(self):
        archive = self.archive()
        existing = self.destination / self.name
        existing.parent.mkdir(parents=True)
        different = b"x" * len(self.data)
        existing.write_bytes(different)
        with self.assertRaisesRegex(ValueError, "overwrite different content"):
            unpack.restore(self.source, self.destination, [archive])
        self.assertEqual(existing.read_bytes(), different)

    def test_archive_checksum_failure_creates_no_output(self):
        archive = self.archive()
        archive["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Archive checksum mismatch"):
            unpack.restore(self.source, self.destination, [archive])
        self.assertFalse(self.destination.exists())

    def test_member_checksum_failure_creates_no_output(self):
        archive = self.archive()
        archive["files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Trajectory checksum mismatch"):
            unpack.restore(self.source, self.destination, [archive])
        self.assertFalse(self.destination.exists())

    def test_missing_and_duplicate_members_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing manifest files"):
            unpack.restore(self.source, self.destination, [self.archive(members=[])])
        member = tarfile.TarInfo(self.name)
        member.size = len(self.data)
        duplicate = self.archive(members=[(member, self.data), (member, self.data)])
        with self.assertRaisesRegex(ValueError, "Unexpected archive member"):
            unpack.restore(self.source, self.destination, [duplicate])

    def test_unsafe_paths_are_rejected(self):
        for name in ["/tmp/outside.jsonl", "experiments/../../outside.jsonl",
                     "experiments//bad.jsonl", "experiments/./bad.jsonl",
                     "experiments\\bad.jsonl"]:
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                member.size = 1
                archive = self.archive(members=[(member, b"x")], records=[
                    {"path": name, "size": 1, "sha256": hashlib.sha256(b"x").hexdigest()}])
                with self.assertRaisesRegex(ValueError, "Unsafe archive path"):
                    unpack.restore(self.source, self.destination, [archive])

    def test_symlink_and_hardlink_members_are_rejected(self):
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE]:
            with self.subTest(kind=kind):
                member = tarfile.TarInfo(self.name)
                member.type = kind
                member.linkname = "/tmp/outside.jsonl"
                archive = self.archive(members=[(member, None)])
                with self.assertRaisesRegex(ValueError, "Unexpected archive member"):
                    unpack.restore(self.source, self.destination, [archive])

    def test_destination_symlink_ancestor_is_rejected(self):
        archive = self.archive()
        outside = self.root / "outside"
        outside.mkdir()
        self.destination.mkdir()
        (self.destination / "experiments").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Refusing symlink"):
            unpack.restore(self.source, self.destination, [archive])
        self.assertEqual(list(outside.iterdir()), [])

    def test_source_archive_symlink_is_rejected(self):
        archive = self.archive()
        path = self.source / archive["path"]
        actual = self.root / "archive.tar.gz"
        path.replace(actual)
        path.symlink_to(actual)
        with self.assertRaisesRegex(ValueError, "Refusing symlink"):
            unpack.restore(self.source, self.destination, [archive])

    def test_unexpected_member_and_cross_archive_duplicate_are_rejected(self):
        member = tarfile.TarInfo("experiments/extra.jsonl")
        member.size = 1
        archive = self.archive(members=[(member, b"x")])
        with self.assertRaisesRegex(ValueError, "Unexpected archive member"):
            unpack.restore(self.source, self.destination, [archive])
        archive = self.archive()
        with self.assertRaisesRegex(ValueError, "Duplicate path across selected archives"):
            unpack.restore(self.source, self.destination, [archive, archive])
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
