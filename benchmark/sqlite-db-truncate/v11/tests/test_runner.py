#!/usr/bin/env python3
"""Standalone test runner that emulates pytest output format.
Dynamically loads a test file and runs all test_* functions.
No third-party packages required."""

import importlib.util
import sys
import time
import traceback


def run_tests(test_file):
    spec = importlib.util.spec_from_file_location("test_module", test_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    test_fns = []
    for name in sorted(dir(mod)):
        if name.startswith("test_"):
            fn = getattr(mod, name)
            if callable(fn):
                test_fns.append((name, fn))

    module_name = test_file.rsplit("/", 1)[-1].replace(".py", "")

    passed = 0
    failed = 0
    errors = 0
    start_time = time.time()

    for name, fn in test_fns:
        try:
            fn()
            print(f"{module_name}::{name} PASSED")
            passed += 1
        except AssertionError as e:
            msg = str(e) if str(e) else "assertion failed"
            print(f"{module_name}::{name} FAILED")
            print(f"  AssertionError: {msg}")
            failed += 1
        except Exception as e:
            print(f"{module_name}::{name} FAILED")
            print(f"  {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1

    elapsed = time.time() - start_time
    total = len(test_fns)
    status = "PASSED" if failed == 0 else "FAILED"
    print(f"\n{'='*70}")
    print(f"test session results: {passed} passed, {failed} failed "
          f"out of {total} tests ({elapsed:.2f}s)")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_runner.py <test_file.py>")
        sys.exit(1)
    run_tests(sys.argv[1])
