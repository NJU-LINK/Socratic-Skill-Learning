import hashlib
import io
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path


BUILD_SCRIPT = Path("/app/build.sh")
MANIFEST_PATH = Path("/app/src/release.manifest")
BUNDLE_PATH = Path("/app/out/release.bundle.tar.zst")

EXPECTED_ORDER = [
    "app/",
    "app/README.link",
    "app/bin/",
    "app/bin/launch.sh",
    "app/config/",
    "app/config/file with spaces.txt",
    "app/config/release.yaml",
    "app/config/runtime.env",
    "app/config/settings.json",
    "app/host.link",
    "app/scripts/",
    "app/scripts/build-index.py",
    "docs/",
    "docs/README.txt",
    "docs/guides/",
    "docs/guides/deep/",
    "docs/guides/deep/level_1/",
    "docs/guides/deep/level_1/level_2/",
    "docs/guides/deep/level_1/level_2/level_3/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/level_11/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/level_11/level_12/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/level_11/level_12/level_13/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/level_11/level_12/level_13/level_14/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/level_11/level_12/level_13/level_14/level_15/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/level_11/level_12/level_13/level_14/level_15/level_16/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/level_11/level_12/level_13/level_14/level_15/level_16/level_17/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/level_11/level_12/level_13/level_14/level_15/level_16/level_17/level_18/",
    "docs/guides/deep/level_1/level_2/level_3/level_4/level_5/level_6/level_7/level_8/level_9/level_10/level_11/level_12/level_13/level_14/level_15/level_16/level_17/level_18/notes.txt",
    "docs/guides/manifest_driven_release_bundle_with_a_filename_that_is_intentionally_long_to_exercise_gnu_tar_path_handling_and_reproducible_archive_ordering_across_nested_directories.txt",
    "docs/guides/packaging.md",
    "assets/images/logo.bin",
    "vendor/cache/.keep",
    "tmp/NOTICE.txt",
]

EXPECTED_ABSENT = {
    ".git/HEAD",
    "build/output/app.o",
    "vendor/cache/pkg-a/index.js",
    "vendor/cache/pkg-b/lock.json",
    "tmp/logs/runtime.log",
    "tmp/reports/daily.tmp",
    "app/config/secret.token",
    "modules/core/python/main.py",
}


def run_build(source_date_epoch=None):
    env = os.environ.copy()
    if source_date_epoch is None:
        env.pop("SOURCE_DATE_EPOCH", None)
    else:
        env["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    subprocess.run([str(BUILD_SCRIPT)], check=True, env=env)
    assert BUNDLE_PATH.exists()
    return BUNDLE_PATH.read_bytes()


def load_members():
    tar_bytes = subprocess.check_output(["zstd", "-dc", str(BUNDLE_PATH)])
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        members = archive.getmembers()
        payloads = {}
        for member in members:
            if member.isfile():
                payloads[member.name] = archive.extractfile(member).read()
        return members, payloads


def archive_names(members):
    names = []
    for member in members:
        name = member.name
        if member.isdir() and not name.endswith("/"):
            name += "/"
        names.append(name)
    return names


def looks_text(data):
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def normalized_mode(path):
    if path.is_dir() and not path.is_symlink():
        return 0o755
    if path.is_symlink():
        return None
    path_mode = stat.S_IMODE(os.lstat(path).st_mode)
    data = path.read_bytes()
    if data.startswith(b"#!") or (path_mode & 0o111):
        return 0o755
    return 0o644


def manifest_rules(manifest_text):
    rules = []
    current_mtime = None
    for raw_line in manifest_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        command, value = line.split(None, 1)
        if command == "set-mtime":
            current_mtime = int(value)
        else:
            rules.append((command, value, current_mtime))
    return rules


def glob_match(path_text, pattern):
    normalized_path = path_text.rstrip("/")
    normalized_pattern = pattern.rstrip("/")
    return Path(normalized_path).match(normalized_pattern)


def walk_entry(root, entry):
    rel = entry.relative_to(root).as_posix()
    if entry.is_dir() and not entry.is_symlink():
        items = [rel + "/"]
        for child in sorted(entry.iterdir(), key=lambda item: item.name):
            items.extend(walk_entry(root, child))
        return items
    return [rel]


def collect_all_paths(root):
    items = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        items.extend(walk_entry(root, child))
    return items


def expand_include(root, pattern, known_paths):
    exact = root / pattern.rstrip("/")
    if pattern.endswith("/"):
        if exact.exists() and exact.is_dir() and not exact.is_symlink():
            return walk_entry(root, exact)
        return []
    if exact.exists() or exact.is_symlink():
        return walk_entry(root, exact)
    return [path_text for path_text in known_paths if glob_match(path_text, pattern)]


def selected_paths_and_mtimes(source_date_epoch):
    src_root = Path("/app/src")
    known_paths = collect_all_paths(src_root)
    selected = []
    selected_set = set()
    mtimes = {}
    for kind, pattern, explicit_mtime in manifest_rules(MANIFEST_PATH.read_text(encoding="utf-8")):
        matches = expand_include(src_root, pattern, known_paths)
        if kind == "include":
            for path_text in matches:
                if path_text in selected_set:
                    selected.remove(path_text)
                else:
                    selected_set.add(path_text)
                selected.append(path_text)
                mtimes[path_text] = explicit_mtime if explicit_mtime is not None else source_date_epoch
        else:
            for path_text in matches:
                if path_text in selected_set:
                    selected.remove(path_text)
                    selected_set.remove(path_text)
                mtimes.pop(path_text, None)
    return selected, mtimes


def build_reference_bundle(source_date_epoch):
    src_root = Path("/app/src")
    selected, mtimes = selected_paths_and_mtimes(source_date_epoch)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()

        for path_text in selected:
            source = src_root / path_text.rstrip("/")
            target = stage_dir / path_text.rstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            mtime = mtimes[path_text]

            if path_text.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                os.chmod(target, 0o755)
                os.utime(target, (mtime, mtime))
                continue

            if source.is_symlink():
                os.symlink(os.readlink(source), target)
                os.utime(target, (mtime, mtime), follow_symlinks=False)
                continue

            data = source.read_bytes()
            if looks_text(data):
                data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            target.write_bytes(data)
            os.chmod(target, normalized_mode(source))
            os.utime(target, (mtime, mtime))

        for path_text in selected:
            if path_text.endswith("/"):
                target = stage_dir / path_text.rstrip("/")
                os.chmod(target, 0o755)
                os.utime(target, (mtimes[path_text], mtimes[path_text]))

        list_path = tmp_path / "archive.list"
        with list_path.open("wb") as handle:
            for path_text in selected:
                handle.write(path_text.rstrip("/").encode("utf-8"))
                handle.write(b"\0")

        tar_path = tmp_path / "release.bundle.tar"
        subprocess.run(
            [
                "tar",
                "--format=gnu",
                "--owner=0",
                "--group=0",
                "--numeric-owner",
                "--no-recursion",
                "--null",
                "-C",
                str(stage_dir),
                "-T",
                str(list_path),
                "-cf",
                str(tar_path),
            ],
            check=True,
        )
        bundle_path = tmp_path / "release.bundle.tar.zst"
        subprocess.run(
            [
                "zstd",
                "-19",
                "--single-thread",
                "--no-check",
                "-f",
                str(tar_path),
                "-o",
                str(bundle_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return bundle_path.read_bytes()


def test_build_script_exists_and_is_executable():
    assert BUILD_SCRIPT.exists()
    assert os.access(BUILD_SCRIPT, os.X_OK)


def test_bundle_matches_manifest_order_and_contents():
    run_build(946684800)
    members, payloads = load_members()
    names = archive_names(members)

    assert names == EXPECTED_ORDER
    assert EXPECTED_ABSENT.isdisjoint(names)

    assert payloads["app/config/runtime.env"] == b"APP_ENV=production\nLOG_LEVEL=info\n"
    assert payloads["app/config/settings.json"] == b"{\n  \"service\": \"release-bundle\",\n  \"port\": 8080\n}\n"
    assert payloads["app/config/file with spaces.txt"] == b"plain text with spaces\nand windows line endings\n"
    assert payloads["docs/README.txt"] == b"Release notes\n==============\nReady for shipment.\n"
    assert payloads["tmp/NOTICE.txt"] == b"temporary notice\nkeep this in bundle\n"
    assert payloads["assets/images/logo.bin"] == b"binary\x00payload\x01\n"

    symlinks = {member.name: member.linkname for member in members if member.issym()}
    assert symlinks["app/README.link"] == "../docs/README.txt"
    assert symlinks["app/host.link"] == "/etc/hostname"


def test_bundle_metadata_is_normalized():
    run_build(1234567890)
    members, _ = load_members()
    by_name = {member.name: member for member in members}

    for member in members:
        assert member.uid == 0
        assert member.gid == 0
        assert member.uname == ""
        assert member.gname == ""
        assert member.mtime == 1712345678

    assert by_name["app"].mode == 0o755
    assert by_name["app/bin/launch.sh"].mode == 0o755
    assert by_name["app/scripts/build-index.py"].mode == 0o755
    assert by_name["app/config/runtime.env"].mode == 0o644
    assert by_name["assets/images/logo.bin"].mode == 0o644


def test_build_is_reproducible_for_same_inputs():
    first = hashlib.sha256(run_build(946684800)).hexdigest()
    second = hashlib.sha256(run_build(946684800)).hexdigest()
    assert first == second


def test_bundle_bytes_match_required_gnu_tar_and_zstd_invocation():
    actual = run_build(946684800)
    expected = build_reference_bundle(946684800)
    assert hashlib.sha256(actual).hexdigest() == hashlib.sha256(expected).hexdigest()
    assert actual == expected


def test_source_date_epoch_fallback_changes_output_without_manifest_timestamp(tmp_path):
    original_manifest = MANIFEST_PATH.read_text(encoding="utf-8")
    backup_path = tmp_path / "release.manifest.backup"
    backup_path.write_text(original_manifest, encoding="utf-8")
    try:
        MANIFEST_PATH.write_text(
            "\n".join(
                line for line in original_manifest.splitlines() if not line.startswith("set-mtime ")
            )
            + "\n",
            encoding="utf-8",
        )
        first = hashlib.sha256(run_build(946684800)).hexdigest()
        second = hashlib.sha256(run_build(946684801)).hexdigest()
        assert first != second
    finally:
        shutil.copyfile(backup_path, MANIFEST_PATH)
