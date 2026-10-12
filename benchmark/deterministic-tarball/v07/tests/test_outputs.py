import gzip
import io
import os
import pathlib
import subprocess
import tarfile


BUILD_SCRIPT = pathlib.Path("/app/build.sh")
ARCHIVE_PATH = pathlib.Path("/app/release.tar.gz")


def run_build(epoch: int) -> bytes:
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    subprocess.run([str(BUILD_SCRIPT)], check=True, env=env)
    return ARCHIVE_PATH.read_bytes()


def load_archive(epoch: int):
    archive_bytes = run_build(epoch)
    tar_bytes = gzip.decompress(archive_bytes)
    archive = tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:")
    return archive_bytes, tar_bytes, archive


def names_map(archive: tarfile.TarFile):
    result = {}
    for member in archive.getmembers():
        name = member.name
        if name == ".":
            continue
        if name.startswith("./"):
            name = name[2:]
        result[name] = member
    return result


def read_member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    extracted = archive.extractfile(member)
    assert extracted is not None
    return extracted.read()


def test_build_script_exists_and_is_executable():
    assert BUILD_SCRIPT.exists()
    assert os.access(BUILD_SCRIPT, os.X_OK)


def test_archive_is_deterministic_for_same_epoch_and_changes_for_new_epoch():
    first = run_build(946684800)
    second = run_build(946684800)
    third = run_build(946684801)

    assert first == second
    assert first != third


def test_archive_contents_metadata_and_scoped_normalization():
    archive_bytes, tar_bytes, archive = load_archive(946684800)
    try:
        assert archive_bytes.startswith(b"\x1f\x8b\x08\x00\x00\x00\x00\x00")
        assert tar_bytes != archive_bytes

        members = names_map(archive)
        names = list(members)

        assert names == sorted(names)

        required_paths = [
            "README.md",
            "pnpm-lock.yaml",
            "poetry.lock",
            "scripts/release.sh",
            "config/legacy.env",
            "notes/external-crlf.txt",
            "packages/app-shell/dist/app.js",
            "packages/app-shell/dist/assets/build-info.json",
            "packages/app-shell/dist/assets/chunk-120.js",
            "packages/inventory-service/dist/wheels/inventory_service-1.4.2-py3-none-any.whl",
            "packages/inventory-service/dist/data/export.csv",
            "packages/inventory-service/dist/data/generated-90.txt",
            "packages/inventory-service/dist/data/mixed.bin",
            "packages/reporting-cli/dist/templates/default.yaml",
            "packages/reporting-cli/dist/reports/report-60.txt",
            "packages/shared-ui/docs/guide.txt",
        ]
        for path in required_paths:
            assert path in members, path

        excluded_paths = [
            ".git/HEAD",
            "packages/app-shell/.venv/bin/activate",
            "packages/app-shell/coverage/html/index.html",
            "packages/app-shell/tmp/cache/session.log",
            "packages/app-shell/.cache/state/store.json",
            "packages/app-shell/dist/tmp/debug.tmp",
            "packages/app-shell/secrets/deploy.key",
            "packages/inventory-service/coverage/raw/coverage.log",
            "packages/inventory-service/.venv/lib/site.py",
            "packages/inventory-service/temp/jobs/run.log",
            "packages/inventory-service/src/__pycache__/main.cpython-312.pyc",
            "packages/inventory-service/src/module.o",
            "packages/inventory-service/keys/service.pem",
            "packages/reporting-cli/coverage/unit/index.txt",
            "packages/reporting-cli/.venv/cache/wheels.txt",
            "packages/reporting-cli/tmp/output/build.tmp",
        ]
        for path in excluded_paths:
            assert path not in members, path

        normalized = {
            "packages/app-shell/src/index.ts": b'export const main = () => "app-shell";\n',
            "packages/app-shell/README.md": b"# App Shell\n\nWindows endings here.\n",
            "packages/app-shell/src/file with spaces.txt": b"with spaces\n",
            "packages/app-shell/src/file$special!chars.md": b"special chars\n",
            "packages/app-shell/dist/assets/build-info.json": b'{\n  "build": "2026-06-03",\n  "target": "prod"\n}\n',
            "packages/reporting-cli/dist/templates/default.yaml": b"title: weekly summary\nowner: ops\n",
            "packages/reporting-cli/dist/reports/report-60.txt": b"report 060\n",
        }
        for path, expected in normalized.items():
            assert read_member_bytes(archive, members[path]) == expected

        unchanged_outside_manifest = {
            "config/legacy.env": b"LEGACY=1\r\nKEEP_CRLF=1\r\n",
            "notes/external-crlf.txt": b"outside manifest stays crlf\r\nsecond line\r\n",
            "packages/shared-ui/docs/guide.txt": b"shared ui is not manifest-scoped\r\n",
            "vendor/reference-data/README.txt": b"vendor readme\r\n",
        }
        for path, expected in unchanged_outside_manifest.items():
            assert read_member_bytes(archive, members[path]) == expected

        assert read_member_bytes(archive, members["packages/inventory-service/dist/data/mixed.bin"]) == b"Text line\nBinary: \x00\x01\x02\n"

        long_name = (
            "packages/app-shell/dist/assets/"
            "release_notes_for_a_very_large_generated_artifact_that_should_still_be_kept_even_when_"
            "the_tree_contains_hundreds_of_files_and_complex_paths_to_exercise_gnu_tar_handling_with_"
            "long_names_and_monorepo_layouts.txt"
        )
        assert read_member_bytes(archive, members[long_name]) == b"long generated artifact\n"

        deep_path = "packages/inventory-service/dist/deep" + "/nested" * 22 + "/final.txt"
        assert deep_path in members
        assert read_member_bytes(archive, members[deep_path]) == b"deep inventory payload\n"

        symlink = members["packages/reporting-cli/current-config"]
        assert symlink.issym()
        assert symlink.linkname == "../../config/reporting.yml"

        host_link = members["packages/reporting-cli/host-link"]
        assert host_link.issym()
        assert host_link.linkname == "/etc/hostname"

        assert members["scripts/release.sh"].mode == 0o755
        assert members["packages/inventory-service/src/main.py"].mode == 0o755
        assert members["packages/reporting-cli/bin/report.sh"].mode == 0o755
        assert members["packages/app-shell/src/readonly.txt"].mode == 0o644
        assert members["config/reporting.yml"].mode == 0o644
        assert members["packages/app-shell/dist"].mode == 0o755

        for path, member in members.items():
            assert member.uid == 0, path
            assert member.gid == 0, path
            assert member.mtime == 946684800, path
    finally:
        archive.close()
