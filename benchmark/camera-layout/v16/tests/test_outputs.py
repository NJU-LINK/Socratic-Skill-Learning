import json, sys, math
sys.path.insert(0, "/app")
import camera_geom as cg

TOL = 1e-4

def load():
    with open("/app/output.json") as f:
        return json.load(f)

def load_fp():
    with open("/app/floor_plan.json") as f:
        return json.load(f)

def test_output_exists():
    r = load()
    assert "cameras" in r, "Missing cameras field"
    assert "coverage" in r, "Missing coverage field"
    assert len(r["cameras"]) > 0, "No cameras placed"
    assert r["total_cameras"] == len(r["cameras"])
    assert r["coverage"] >= 0.99, f"Coverage {r['coverage']} < 0.99"

def test_cameras_on_walls():
    r, fp = load(), load_fp()
    walls = fp["walls_coords"]
    for c in r["cameras"]:
        wi = c["wall_index"]
        x, y = c["x"], c["y"]
        wx1, wy1, wx2, wy2 = walls[wi]
        ok = cg.point_on_segment(x, y, wx1, wy1, wx2, wy2)
        assert ok, f"Camera ({x},{y}) not on wall {wi}"

def test_is_endpoint_valid():
    r, fp = load(), load_fp()
    walls = fp["walls_coords"]
    for c in r["cameras"]:
        x, y, wi, ep = c["x"], c["y"], c["wall_index"], c["is_endpoint"]
        wx1, wy1, wx2, wy2 = walls[wi]
        d1 = math.hypot(x - wx1, y - wy1)
        d2 = math.hypot(x - wx2, y - wy2)
        is_at_end = d1 < TOL or d2 < TOL
        assert ep == is_at_end, f"Camera at ({x},{y}) on wall {wi}: is_endpoint={ep} but actually {'at endpoint' if is_at_end else 'on wall body'}"

def test_full_coverage():
    r, fp = load(), load_fp()
    cams = [(c["x"], c["y"], c["wall_index"], c["is_endpoint"]) for c in r["cameras"]]
    cov, tot, _ = cg.compute_coverage(fp, cams)
    assert cov >= 0.99, f"Coverage too low: {cov*100:.1f}%"

def test_reasonable_camera_count():
    r = load()
    assert 1 <= r["total_cameras"] <= 8, f"Unreasonable camera count: {r['total_cameras']}"
