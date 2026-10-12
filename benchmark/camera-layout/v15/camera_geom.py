import math


def line_intersect(p1, p2, q1, q2):
    (x1, y1), (x2, y2) = p1, p2
    (x3, y3), (x4, y4) = q1, q2
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1), t, u)
    return None


def point_on_segment(px, py, x1, y1, x2, y2, tol=1e-9):
    distance = math.dist((px, py), (x1, y1)) + math.dist((px, py), (x2, y2))
    return abs(distance - math.dist((x1, y1), (x2, y2))) < tol


def point_in_polygon(px, py, polygon):
    inside = False
    for index in range(len(polygon)):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % len(polygon)]
        if ((y1 > py) != (y2 > py)) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def line_segments_intersect_walls(x1, y1, x2, y2, walls, exclude_wall_idx=None):
    for wall_index, (wx1, wy1, wx2, wy2) in enumerate(walls):
        if exclude_wall_idx is not None and wall_index == exclude_wall_idx:
            continue
        if point_on_segment(x1, y1, wx1, wy1, wx2, wy2) and point_on_segment(
            x2, y2, wx1, wy1, wx2, wy2
        ):
            continue
        hit = line_intersect((x1, y1), (x2, y2), (wx1, wy1), (wx2, wy2))
        if hit is not None:
            _, _, t, u = hit
            if 1e-6 < t < 1 - 1e-6 and 1e-6 < u < 1 - 1e-6:
                return True
    return False


def line_segment_intersects_obstacles(x1, y1, x2, y2, obstacles):
    for ox, oy, width, height in obstacles:
        left, right = min(ox, ox + width), max(ox, ox + width)
        bottom, top = min(oy, oy + height), max(oy, oy + height)
        edges = [
            ((left, bottom), (right, bottom)),
            ((right, bottom), (right, top)),
            ((right, top), (left, top)),
            ((left, top), (left, bottom)),
        ]
        for edge_start, edge_end in edges:
            hit = line_intersect((x1, y1), (x2, y2), edge_start, edge_end)
            if hit is not None and 1e-6 < hit[2] < 1 - 1e-6:
                return True
    return False


def wall_normal(x1, y1, x2, y2, interior_point):
    nx = -(y2 - y1)
    ny = x2 - x1
    length = math.hypot(nx, ny)
    if length == 0:
        return (0, 1)
    nx /= length
    ny /= length
    mid_x = (x1 + x2) / 2
    mid_y = (y1 + y2) / 2
    if (interior_point[0] - mid_x) * nx + (interior_point[1] - mid_y) * ny < 0:
        nx, ny = -nx, -ny
    return (nx, ny)


def is_visible_from_camera(
    cx,
    cy,
    px,
    py,
    walls,
    obstacles,
    wall_idx,
    is_endpoint,
    interior_normals,
):
    segment_length = math.hypot(px - cx, py - cy)
    if segment_length < 1e-9:
        return True
    segment_normal = ((px - cx) / segment_length, (py - cy) / segment_length)
    if not is_endpoint:
        nx, ny = interior_normals[wall_idx]
        if segment_normal[0] * nx + segment_normal[1] * ny <= 0:
            return False
    if line_segments_intersect_walls(cx, cy, px, py, walls, exclude_wall_idx=wall_idx):
        return False
    return not line_segment_intersects_obstacles(cx, cy, px, py, obstacles)


def compute_coverage(floor_plan, cameras):
    walls = floor_plan["walls_coords"]
    room = floor_plan["room_boundary"]
    obstacles = floor_plan.get("obstacles", [])
    grid_size = floor_plan.get("grid_size", 0.5)
    min_x = min(point[0] for point in room)
    max_x = max(point[0] for point in room)
    min_y = min(point[1] for point in room)
    max_y = max(point[1] for point in room)

    interior_normals = []
    for wx1, wy1, wx2, wy2 in walls:
        center_x = (wx1 + wx2) / 2
        center_y = (wy1 + wy2) / 2
        interior_point = (center_x + 0.5, center_y + 0.5)
        if not point_in_polygon(*interior_point, room):
            interior_point = (center_x - 0.5, center_y + 0.5)
            if not point_in_polygon(*interior_point, room):
                interior_point = (center_x, center_y + 0.5)
        interior_normals.append(wall_normal(wx1, wy1, wx2, wy2, interior_point))

    total = 0
    covered = 0
    y = min_y + grid_size / 2
    while y < max_y:
        x = min_x + grid_size / 2
        while x < max_x:
            inside_obstacle = any(
                ox <= x <= ox + width and oy <= y <= oy + height
                for ox, oy, width, height in obstacles
            )
            if point_in_polygon(x, y, room) and not inside_obstacle:
                total += 1
                if any(
                    is_visible_from_camera(
                        camera_x,
                        camera_y,
                        x,
                        y,
                        walls,
                        obstacles,
                        wall_index,
                        is_endpoint,
                        interior_normals,
                    )
                    for camera_x, camera_y, wall_index, is_endpoint in cameras
                ):
                    covered += 1
            x += grid_size
        y += grid_size
    return covered / max(total, 1), total, covered
