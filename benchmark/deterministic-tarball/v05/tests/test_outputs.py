import contextlib
import hashlib
import os
import pathlib
import stat
import subprocess
import tarfile


BUILD_SCRIPT = pathlib.Path("/app/build.sh")
SRC_DIR = pathlib.Path("/app/src")
ARCHIVE = pathlib.Path("/app/release.tar.zst")


def run_build(epoch):
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run([str(BUILD_SCRIPT)], check=True, env=env)
    return ARCHIVE.read_bytes()


def unpack_archive(tmp_path):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    subprocess.run(["zstd", "-d", "-q", "-o", str(tmp_path / "release.tar"), str(ARCHIVE)], check=True)
    with tarfile.open(tmp_path / "release.tar", "r") as tf:
        members = {member.name: member for member in tf.getmembers()}
    subprocess.run(["tar", "-xf", str(tmp_path / "release.tar"), "-C", str(extract_dir)], check=True)
    return extract_dir, members


@contextlib.contextmanager
def restore_files(*paths):
    snapshots = []
    for path in paths:
        snapshots.append((path, path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))
    try:
        yield
    finally:
        for path, data, mode in snapshots:
            path.write_bytes(data)
            path.chmod(mode)


def test_reproducible_archive_and_manifest_rules(tmp_path):
    assert BUILD_SCRIPT.exists(), "solution must create /app/build.sh"
    assert os.access(BUILD_SCRIPT, os.X_OK), "/app/build.sh must be executable"

    first = run_build(946684800)
    second = run_build(946684800)
    third = run_build(946684801)

    assert first == second, "same epoch should produce identical bytes"
    assert hashlib.sha256(first).digest() != hashlib.sha256(third).digest(), "different epoch should change archive"

    ARCHIVE.write_bytes(first)
    extract_dir, members = unpack_archive(tmp_path)

    names = set(members)
    assert "./notes/brief.secret" not in names
    assert "./ops/prod.secret" not in names
    assert "./src/main.o" not in names
    assert "./tmp/scratch.tmp" not in names
    assert "./node_modules/pkg/index.js" not in names
    assert "./.git/HEAD" not in names
    assert "./src/__pycache__/cache.pyc" not in names
    assert "./.cache/index" not in names

    assert (extract_dir / "docs/README.txt").read_bytes() == b"Line one\nLine two\n"
    assert (extract_dir / "db/schema.sql").read_bytes() == b"SELECT 1;\nSELECT 2;\n"
    assert (extract_dir / "templates/greeting.tmpl").read_bytes() == b"Hello, {{ name }}\n"
    assert (extract_dir / "config/service.yaml").read_bytes() == b"apiVersion: v1\nkind: ConfigMap\n"
    assert (extract_dir / "generated/app.min.js").read_bytes() == b"function main(){\n  return 42;\n}\n"

    assert (extract_dir / "config/runtime").read_bytes() == b"MODE=prod\r\nREGION=west\r\n"
    assert (extract_dir / "bin/runner.py").read_bytes() == b"#!/usr/bin/env python3\nprint(\"should not become executable\")\n"
    assert (extract_dir / "scripts/release-helper").read_bytes() == b"echo helper\n"
    assert (extract_dir / "scripts/ops-tool").read_bytes() == b"#!/bin/sh\necho keep me non-executable\n"
    assert (extract_dir / "assets/mixed.dat").read_bytes() == b"Text line\nBinary:\x00\x01\x02\n"

    assert stat.S_IMODE(members["./scripts/deploy.sh"].mode) == 0o755
    assert stat.S_IMODE(members["./scripts/release-helper"].mode) == 0o755
    assert stat.S_IMODE(members["./bin/runner.py"].mode) == 0o644
    assert stat.S_IMODE(members["./scripts/ops-tool"].mode) == 0o644
    assert stat.S_IMODE(members["./config/keep.env"].mode) == 0o644

    assert members["./src/readme-link"].issym()
    assert members["./src/readme-link"].linkname == "../docs/README.txt"
    assert members["./src/passwd-link"].issym()
    assert members["./src/passwd-link"].linkname == "/etc/passwd"

    for name, member in members.items():
        assert member.uid == 0
        assert member.gid == 0
        assert member.mtime == 946684800
        if member.isdir():
            assert stat.S_IMODE(member.mode) == 0o755


def test_build_follows_updated_packaging_manifests(tmp_path):
    exec_manifest = SRC_DIR / "packaging/executables.txt"
    text_manifest = SRC_DIR / "packaging/text-extensions.txt"
    runner = SRC_DIR / "bin/runner.py"
    deploy = SRC_DIR / "scripts/deploy.sh"
    release_helper = SRC_DIR / "scripts/release-helper"
    ops_tool = SRC_DIR / "scripts/ops-tool"
    schema = SRC_DIR / "db/schema.sql"
    greeting = SRC_DIR / "templates/greeting.tmpl"
    keep_env = SRC_DIR / "config/keep.env"

    with restore_files(
        exec_manifest,
        text_manifest,
        runner,
        deploy,
        release_helper,
        ops_tool,
        schema,
        greeting,
        keep_env,
    ):
        exec_manifest.write_text(
            "# changed during test\n"
            "bin/runner.py\n"
            "scripts/ops-tool\n",
            encoding="utf-8",
        )
        text_manifest.write_text(
            "txt\n"
            "md\n"
            "py\n"
            "sh\n"
            "c\n"
            "h\n"
            "js\n"
            "css\n"
            "html\n"
            "xml\n"
            "json\n"
            "yaml\n"
            "yml\n"
            "env\n",
            encoding="utf-8",
        )

        runner.chmod(0o644)
        deploy.chmod(0o755)
        release_helper.chmod(0o755)
        ops_tool.chmod(0o644)

        schema.write_bytes(b"SELECT 1;\r\nSELECT 2;\r\n")
        greeting.write_bytes(b"Hello, {{ name }}\r\n")
        keep_env.write_bytes(b"token=internal-use\r\n")

        run_build(946684800)
        extract_dir, members = unpack_archive(tmp_path)

    assert (extract_dir / "db/schema.sql").read_bytes() == b"SELECT 1;\r\nSELECT 2;\r\n"
    assert (extract_dir / "templates/greeting.tmpl").read_bytes() == b"Hello, {{ name }}\r\n"
    assert (extract_dir / "config/keep.env").read_bytes() == b"token=internal-use\n"

    assert stat.S_IMODE(members["./bin/runner.py"].mode) == 0o755
    assert stat.S_IMODE(members["./scripts/ops-tool"].mode) == 0o755
    assert stat.S_IMODE(members["./scripts/deploy.sh"].mode) == 0o644
    assert stat.S_IMODE(members["./scripts/release-helper"].mode) == 0o644
