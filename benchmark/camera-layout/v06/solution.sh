#!/bin/bash
set -e
exec python3 << 'PYEOF'
import json, itertools, sys
sys.path.insert(0, "/app")
from camera_geom import point_in_polygon, compute_coverage

def solve(fp):
    walls = fp["walls_coords"]
    room = fp["room_boundary"]
    candidates = []
    for wi, (wx1, wy1, wx2, wy2) in enumerate(walls):
        for x, y in [(wx1, wy1), (wx2, wy2)]:
            if point_in_polygon(x, y, room):
                candidates.append((x, y, wi, True))
        for t in [0.25, 0.5, 0.75]:
            mx = wx1 + t * (wx2 - wx1)
            my = wy1 + t * (wy2 - wy1)
            candidates.append((mx, my, wi, False))

    for size in range(1, min(9, len(candidates) + 1)):
        best = None
        for combo in itertools.combinations(candidates, size):
            cams = list(combo)
            cov, tot, _ = compute_coverage(fp, cams)
            if cov >= 0.99:
                best = [{"x": round(cx, 4), "y": round(cy, 4), "wall_index": wi, "is_endpoint": ep}
                        for cx, cy, wi, ep in cams]
                break
        if best:
            return {"cameras": best, "coverage": round(cov, 4), "total_cameras": len(best)}
    return {"cameras": [], "coverage": 0.0, "total_cameras": 0}

fp = json.load(open("/app/floor_plan.json"))
result = solve(fp)
json.dump(result, open("/app/output.json", "w"), indent=2)
print(f"Cameras: {result['total_cameras']}, Coverage: {result['coverage']*100:.1f}%")
PYEOF
