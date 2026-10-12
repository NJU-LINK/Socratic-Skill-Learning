#!/usr/bin/env python3
"""
Independent verifier for peaks.csv against mag.csv.
Recomputes top-k from mag.csv using numpy and compares with peaks.csv.
"""
import csv
import sys
import numpy as np

def main():
    mag_p, peaks_p, k = (sys.argv[1:] + ["data/mag.csv", "data/peaks.csv", "3"])[:3]
    k = int(k)
    
    # Load mag.csv into memory: {frame: [(bin, val), ...]}
    frames = {}
    with open(mag_p) as f:
        r = csv.reader(f)
        next(r)  # skip header
        for row in r:
            fr = int(row[0])
            b = int(row[1])
            v = float(row[2])
            frames.setdefault(fr, []).append((b, v))
    
    bad = 0
    with open(peaks_p) as f:
        r = csv.reader(f)
        next(r)  # skip header
        for row in r:
            fr = int(row[0])
            got = [int(x) for x in row[1:1+k]]
            
            # Recompute expected: sort by (-value, bin) and take top k
            ranked = sorted(frames[fr], key=lambda bv: (-bv[1], bv[0]))
            exp = [b for b, _ in ranked[:k]]
            
            if got != exp:
                # Tolerate true ties: check if values match
                vals = dict(frames[fr])
                got_vals = [vals.get(g, 0) for g in got]
                exp_vals = [v for _, v in ranked[:k]]
                if got_vals != exp_vals:
                    bad += 1
                    print(f"frame {fr}: got {got}, expect {exp}")
    
    print(f"MISMATCHES: {bad}, frames checked: {len(frames)}")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
