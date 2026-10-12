import base64
import csv
import hashlib
import os
from pathlib import Path
import tarfile
import zipfile


NAME = "vectorops"
VERSION = "0.1.0"
DIST_INFO = f"{NAME}-{VERSION}.dist-info"


def _root():
    return Path(__file__).resolve().parent


def _metadata_text():
    return "\n".join(
        [
            "Metadata-Version: 2.1",
            f"Name: {NAME}",
            f"Version: {VERSION}",
            "Summary: Vector operations package",
            "Author: Task Author",
            "",
        ]
    )


def _package_files():
    package_root = _root() / "src" / NAME
    return sorted(path for path in package_root.rglob("*") if path.is_file())


def _wheel_name():
    return f"{NAME}-{VERSION}-py3-none-any.whl"


def _sdist_name():
    return f"{NAME}-{VERSION}.tar.gz"


def _dist_info_dir(metadata_directory):
    dist_info_dir = Path(metadata_directory) / DIST_INFO
    dist_info_dir.mkdir(parents=True, exist_ok=True)
    (dist_info_dir / "METADATA").write_text(_metadata_text(), encoding="utf-8")
    (dist_info_dir / "WHEEL").write_text(
        "\n".join(
            [
                "Wheel-Version: 1.0",
                "Generator: vectorops-backend",
                "Root-Is-Purelib: true",
                "Tag: py3-none-any",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (dist_info_dir / "top_level.txt").write_text(f"{NAME}\n", encoding="utf-8")
    return dist_info_dir


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    return _dist_info_dir(metadata_directory).name


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    wheel_directory = Path(wheel_directory)
    wheel_directory.mkdir(parents=True, exist_ok=True)
    wheel_path = wheel_directory / _wheel_name()
    records = []

    def add_bytes(archive, arcname, payload):
        archive.writestr(arcname, payload)
        digest = hashlib.sha256(payload).digest()
        records.append(
            (
                arcname,
                "sha256=" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
                str(len(payload)),
            )
        )

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _package_files():
            arcname = path.relative_to(_root() / "src").as_posix()
            add_bytes(archive, arcname, path.read_bytes())

        add_bytes(archive, f"{DIST_INFO}/METADATA", _metadata_text().encode("utf-8"))
        add_bytes(
            archive,
            f"{DIST_INFO}/WHEEL",
            "\n".join(
                [
                    "Wheel-Version: 1.0",
                    "Generator: vectorops-backend",
                    "Root-Is-Purelib: true",
                    "Tag: py3-none-any",
                    "",
                ]
            ).encode("utf-8"),
        )
        add_bytes(archive, f"{DIST_INFO}/top_level.txt", f"{NAME}\n".encode("utf-8"))

        record_lines = []
        for row in records:
            record_lines.append(",".join(row))
        record_lines.append(f"{DIST_INFO}/RECORD,,")
        archive.writestr(f"{DIST_INFO}/RECORD", "\n".join(record_lines).encode("utf-8"))

    return wheel_path.name


def build_sdist(sdist_directory, config_settings=None):
    sdist_directory = Path(sdist_directory)
    sdist_directory.mkdir(parents=True, exist_ok=True)
    sdist_path = sdist_directory / _sdist_name()
    prefix = f"{NAME}-{VERSION}"
    files = [
        _root() / "pyproject.toml",
        _root() / "README.md",
        _root() / "backend.py",
    ]
    files.extend(_package_files())

    with tarfile.open(sdist_path, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=f"{prefix}/{path.relative_to(_root()).as_posix()}")

    return sdist_path.name
