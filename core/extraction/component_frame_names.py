"""Find component name candidates within closed frame segments."""

from itertools import combinations

from ezdxf.math import Vec3

def frame_columns(document, pins, targets, tolerance):
    """Return unambiguous closed LINE cells; never invent missing boundary pieces."""
    jobs = []
    for target in pins:
        if target["handle"] not in targets or target["point"] is None:
            continue
        axis, point = target["axis"], target["point"]
        if abs(axis.z) > tolerance:
            continue  # First version supports frame planes parallel to WCS XY only.
        normal = Vec3(-axis.y, axis.x)
        x, y = point.dot(normal), point.dot(axis)
        vertical, horizontal = [], []
        for entity in document.modelspace().query("LINE"):
            a, b = Vec3(entity.dxf.start), Vec3(entity.dxf.end)
            if max(abs(a.z-point.z), abs(b.z-point.z)) > tolerance:
                continue
            ax, ay, bx, by = a.dot(normal), a.dot(axis), b.dot(normal), b.dot(axis)
            if abs(ax-bx) <= tolerance and abs(ay-by) > tolerance:
                vertical.append((ax, min(ay, by), max(ay, by), entity.dxf.handle))
            if abs(ay-by) <= tolerance and abs(ax-bx) > tolerance:
                horizontal.append((ay, min(ax, bx), max(ax, bx), entity.dxf.handle))
        matches = []
        for first, second in combinations(vertical, 2):
            left, right = sorted((first, second))
            lx, low, high, _ = left
            rx = right[0]
            if not (lx+tolerance < x < rx-tolerance and low+tolerance < y < high-tolerance):
                continue
            if max(abs(low-second[1]), abs(high-second[2]), abs(low-first[1]), abs(high-first[2])) > tolerance:
                continue
            caps = [[h for h in horizontal if abs(h[0]-end) <= tolerance
                     and h[1] <= lx+tolerance and h[2] >= rx-tolerance] for end in (low, high)]
            if any(len(end) != 1 for end in caps):
                continue
            bottom, top = caps[0][0], caps[1][0]
            if max(abs(bottom[i]-top[i]) for i in (1, 2)) > tolerance:
                continue
            walls = sorted(v for v in vertical if abs(v[1]-low) <= tolerance
                           and abs(v[2]-high) <= tolerance and bottom[1]-tolerance <= v[0] <= bottom[2]+tolerance)
            # Two outside walls plus at least one real through-divider establish sides.
            if len(walls) < 3 or abs(walls[0][0]-bottom[1]) > tolerance or abs(walls[-1][0]-bottom[2]) > tolerance:
                continue
            if any(lx+tolerance < v[0] < rx-tolerance for v in walls):
                continue  # Only adjacent boundaries define a side; do not cross a divider.
            if any(low+tolerance < h[0] < high-tolerance and h[1] <= lx+tolerance
                   and h[2] >= rx-tolerance for h in horizontal):
                continue  # A complete internal transverse divider prevents inheritance.
            members = [p for p in pins if p["point"] is not None and abs(p["point"].z-point.z) <= tolerance
                       and lx+tolerance < p["point"].dot(normal) < rx-tolerance
                       and low+tolerance < p["point"].dot(axis) < high-tolerance]
            if any(p["tags"] != target["tags"] or p["axis"].cross(axis).magnitude > tolerance for p in members):
                continue
            headers = [p for p in members if p["visible"]]
            if len(headers) != 1 or len(headers[0]["visible"]) != 1:
                continue  # Count title sources, even if two sources have the same text.
            head = headers[0]
            # Geometry uses the same SPEC R7 tolerance; no extra gap/spacing threshold.
            evidence = {"side_lines": [left[3], right[3]], "end_lines": [bottom[3], top[3]],
                        "outer_lines": [walls[0][3], walls[-1][3]],
                        "through_dividers": [v[3] for v in walls[1:-1]],
                        "LINK_axis_offset": (target["mid"]-head["mid"]).cross(axis).magnitude}
            matches.append((members, evidence, target["handle"]))
        if len(matches) == 1:
            jobs.extend(matches)  # Multiple enclosing cells are not resolved by choosing the smallest.
    return jobs
