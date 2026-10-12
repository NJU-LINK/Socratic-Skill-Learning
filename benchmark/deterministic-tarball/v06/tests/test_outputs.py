import hashlib
import os
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path


APP = Path("/app")
ARCHIVE = APP / "sdk-snapshot.tar.zst"


def run_build(epoch=None):
    env = os.environ.copy()
    if epoch is None:
        env.pop("SOURCE_DATE_EPOCH", None)
    else:
        env["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run(["/app/build.sh"], check=True, env=env)
    return ARCHIVE.read_bytes()


def read_archive_members():
    result = subprocess.run(
        ["tar", "--zstd", "-tvf", str(ARCHIVE)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


@contextmanager
def open_archive_tar():
    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = Path(tmpdir) / "sdk-snapshot.tar"
        with tar_path.open("wb") as fh:
            subprocess.run(["zstd", "-dc", str(ARCHIVE)], check=True, stdout=fh)
        with tarfile.open(tar_path, mode="r:") as tf:
            yield tf


def test_build_script_exists_and_is_executable():
    path = APP / "build.sh"
    assert path.exists()
    assert os.access(path, os.X_OK)


def test_reproducible_with_same_epoch_and_changes_with_different_epoch():
    first = run_build(1704067200)
    second = run_build(1704067200)
    third = run_build(1704067201)

    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()
    assert first != third


def test_archive_is_pax_and_uses_sdk_root():
    run_build(1704067200)
    with open_archive_tar() as tf:
        members = list(tf)

    names = [member.name for member in members]
    assert members[0].name == "sdk"
    assert all(member.name == "sdk" or member.name.startswith("sdk/") for member in members)
    assert len(names) == len(set(names))
    assert any(member.pax_headers for member in members if "artifact-manifest-with-a-name" in member.name)


def test_exclusions_and_symlink_preservation():
    run_build(1704067200)
    with open_archive_tar() as tf:
        members = {member.name: member for member in tf}

    forbidden = {
        "sdk/.git",
        "sdk/.git/HEAD",
        "sdk/cache",
        "sdk/cache/generated/indexes/current.json",
        "sdk/tmp",
        "sdk/tmp/session/build.tmp",
        "sdk/tools/helper.o",
        "sdk/keys/release.token",
        "sdk/src/__pycache__/sdk.cpython-312.pyc",
    }
    for name in forbidden:
        assert name not in members

    expected_links = {
        "sdk/bin/sdk": "../versions/2025.04/bin/sdk-env.sh",
        "sdk/bin/default-sdk": "sdk",
        "sdk/bin/current-sdk": "default-sdk",
        "sdk/lib/libseedsdk.so.4": "../versions/2025.04/lib/libseedsdk.so.4.2.1",
        "sdk/lib/libseedsdk.so": "libseedsdk.so.4",
        "sdk/include/current": "../../versions/2025.04/include/sdk",
        "sdk/examples/build-cache": "../tmp/session",
        "sdk/examples/dev-token-link": "../keys/release.token",
        "sdk/docs/latest-release-notes": "../docs/missing-release-notes.txt",
        "sdk/docs/system-sdk.conf": "/opt/runtime/global-sdk.conf",
        "sdk/docs/long-manifest-link": "../versions/2025.04/share/components-with-very-long-identifiers-for-pax-validation/sdk-assets-that-should-still-be-addressable-by-links/release-build-containing-another-level-of-length-stress/artifact-manifest-with-a-name-that-exceeds-the-usual-ustar-comfort-zone-and-requires-pax-handling.txt",
        "sdk/examples/duplicate-long-manifest-link": "../docs/long-manifest-link",
    }
    for name, target in expected_links.items():
        assert name in members
        assert members[name].issym()
        assert members[name].linkname == target


def test_regular_file_normalization_and_modes():
    run_build(1704067200)
    with open_archive_tar() as tf:
        members = {member.name: member for member in tf}
        sdk_env = tf.extractfile(members["sdk/versions/2025.04/bin/sdk-env.sh"]).read()
        api_h = tf.extractfile(members["sdk/versions/2025.04/include/sdk/api.h"]).read()
        guide = tf.extractfile(members["sdk/versions/2025.04/share/doc/sdk/guide.txt"]).read()
        plugin = tf.extractfile(members["sdk/libexec/plugin.bin"]).read()

    assert b"\r" not in sdk_env
    assert b"\r" not in api_h
    assert b"\r" not in guide
    assert members["sdk/versions/2025.04/bin/sdk-env.sh"].mode & 0o777 == 0o755
    assert members["sdk/libexec/plugin.bin"].mode & 0o777 == 0o755
    assert members["sdk/docs/NOTES.md"].mode & 0o777 == 0o644
    assert members["sdk/docs/old-manifest.txt"].mode & 0o777 == 0o644
    assert members["sdk/docs/future-manifest.txt"].mode & 0o777 == 0o644
    assert plugin.startswith(b"Text before binary\n\x00\x01\x02after\n")


def test_member_order_is_lexical_and_locale_independent():
    run_build(1704067200)
    names = []
    with open_archive_tar() as tf:
        for member in tf:
            names.append(member.name)

    assert names == sorted(names)


def test_directory_entries_are_usable_and_owned_by_root_group_root():
    run_build(1704067200)
    with open_archive_tar() as tf:
        directories = [member for member in tf if member.isdir()]

    assert directories
    for directory in directories:
        assert directory.mode & 0o777 == 0o755
        assert directory.uid == 0
        assert directory.gid == 0


def test_archive_listing_shows_symlink_entries_not_dereferenced_targets():
    run_build(1704067200)
    listing = read_archive_members()

    assert any("sdk/bin/current-sdk -> default-sdk" in line for line in listing)
    assert any("sdk/examples/dev-token-link -> ../keys/release.token" in line for line in listing)
    assert not any("sdk/cache/generated/indexes/current.json" in line for line in listing)
