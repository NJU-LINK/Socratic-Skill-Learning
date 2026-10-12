from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent


def main() -> None:
    subprocess.run(
        ["wat2wasm", str(ROOT / "sample_module.wat"), "-o", str(ROOT / "module.wasm")],
        check=True,
    )
    subprocess.run(
        [
            "gcc",
            "-shared",
            "-fPIC",
            "-O2",
            str(ROOT / "sample_transform.c"),
            "-o",
            str(ROOT / "libcompute.so"),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
