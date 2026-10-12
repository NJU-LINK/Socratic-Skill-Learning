#!/usr/bin/env python3
"""
Cross-validate peaks.csv against mag.csv.

Usage:
    python3 verify_peaks.py [--mag data/mag.csv] [--peaks data/peaks.csv] [--k 3]

Checks:
  1. peaks.csv has correct header and one row per frame.
  2. For every frame, the listed bins are the true top-k by magnitude.
  3. Magnitudes are in descending order (with correct tie-breaking).
"""
import argparse
import csv
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mag", default="data/mag.csv")
    ap.add_argument("--peaks", default="data/peaks.csv")
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()

    # Load mag.csv
    mag = {}  # frame -> [(val, bin), ...]
    with open(args.mag) as f:
        reader = csv.DictReader(f)
        for row in reader:
            fr = int(row["frame"])
            bn = int(row["bin"])
            vl = float(row["val"])
            mag.setdefault(fr, []).append((vl, bn))

    # Load peaks.csv
    peaks = {}
    with open(args.peaks) as f:
        reader = csv.DictReader(f)
        peak_cols = [c for c in reader.fieldnames if c != "frame"]
        if len(peak_cols) != args.k:
            print(f"FAIL: peaks.csv has {len(peak_cols)} bin columns, expected {args.k}")
            sys.exit(1)
        for row in reader:
            fr = int(row["frame"])
            bins = [int(row[c]) for c in peak_cols]
            peaks[fr] = bins

    # Validate
    ok = fail = 0
    for fr in sorted(mag.keys()):
        entries = sorted(mag[fr], key=lambda x: (-x[0], x[1]))
        expected = [e[1] for e in entries[: args.k]]
        actual = peaks.get(fr)
        if actual is None:
            print(f"FAIL: frame {fr} missing from peaks.csv")
            fail += 1
        elif actual != expected:
            print(f"FAIL: frame {fr}: expected {expected}, got {actual}")
            fail += 1
        else:
            ok += 1

    extra = set(peaks.keys()) - set(mag.keys())
    if extra:
        print(f"FAIL: peaks.csv has {len(extra)} extra frames: {sorted(extra)[:5]}...")
        fail += len(extra)

    print(f"\nResult: {ok} ok, {fail} fail out of {ok + fail} frames")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
