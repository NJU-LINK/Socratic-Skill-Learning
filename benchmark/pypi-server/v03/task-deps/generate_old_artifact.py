import shutil
import subprocess
import sys
from pathlib import Path


PACKAGE_ROOT = Path("/tmp/vectorops-0.0.9")
DIST_DIR = PACKAGE_ROOT / "dist"
TARGET_DIR = Path("/srv/pypi-packages")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    shutil.rmtree(PACKAGE_ROOT, ignore_errors=True)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    write(
        PACKAGE_ROOT / "vectorops" / "__init__.py",
        "def dotproduct(a, b):\n    return sum(x * y for x, y in zip(a, b))\n",
    )
    write(
        PACKAGE_ROOT / "setup.py",
        "from setuptools import setup\n\n"
        "setup(\n"
        "    name='vectorops',\n"
        "    version='0.0.9',\n"
        "    description='Legacy vector operations package',\n"
        "    packages=['vectorops'],\n"
        ")\n",
    )

    subprocess.run(
        [sys.executable, "setup.py", "bdist_wheel"],
        cwd=PACKAGE_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    wheel_path = next(DIST_DIR.glob("vectorops-0.0.9-*.whl"))
    shutil.copy2(wheel_path, TARGET_DIR / wheel_path.name)
    shutil.rmtree(PACKAGE_ROOT, ignore_errors=True)


if __name__ == "__main__":
    main()
