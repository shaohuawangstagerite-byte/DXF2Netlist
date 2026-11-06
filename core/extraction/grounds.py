"""Identify ground symbol candidates and retain their source evidence."""

from copy import deepcopy

from math import isfinite

from ezdxf.math import Vec3

def extract_ground_candidates(document, raw):
    """Find a wire stem and three shrinking, coaxial parallel bars in one layout."""
    source = raw.get("source", {})
    tolerance = raw.get("geometry", {}).get("tolerance")
    if (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float))
            or not isfinite(tolerance) or tolerance <= 0):
        raise ValueError("Ground extraction needs a positive finite geometry tolerance")
    if not isinstance(source.get("sha256"), str) or not source["sha256"].strip():
        raise ValueError("Ground extraction needs a nonempty source SHA256")
    # Contact and alignment tolerance is the existing SPEC R7 value, never a new size.
    tol = float(tolerance)
    lines = []
    for entity in document.layouts.get(source["layout"]):
        if entity.dxftype() != "LINE":
            continue
        start, end = Vec3(entity.dxf.start), Vec3(entity.dxf.end)
        vector = end - start
        length = vector.magnitude
        if not isfinite(length) or length <= tol:
            continue
        lines.append({"handle": entity.dxf.handle, "start": start, "end": end,
                      "center": (start + end) / 2, "length": length,
                      "direction": vector / length})
    wires = {}
    for edge in raw.get("connections", []):
        if edge["kind"] == "wire":
            for handle in edge.get("source", {}).get("handles", []):
                wires.setdefault(handle, set()).add(edge["id"])
    candidates = []
    for bar in lines:
        center, length, direction = bar["center"], bar["length"], bar["direction"]
        stems = []
        for line in lines:
            if line is bar or abs(line["direction"].dot(direction)) * length > tol:
                continue
            if center.distance(line["start"]) <= tol:
                stems.append((line, line["end"]))
            elif center.distance(line["end"]) <= tol:
                stems.append((line, line["start"]))
        # Multiple stems at the same contact are ambiguous, even if one is a wire.
        if len(stems) != 1:
            continue
        stem, far_end = stems[0]
        axis = (center - far_end).normalize()
        followers = []
        for line in lines:
            if line is bar or line is stem:
                continue
            if line["direction"].cross(direction).magnitude * length > tol:
                continue
            offset = line["center"] - center
            distance = offset.dot(axis)
            # The contacted bar's own length bounds this local motif's search area.
            if tol < distance <= length + tol and offset.cross(axis).magnitude <= tol:
                followers.append((distance, line))
        followers.sort(key=lambda item: item[0])
        # The supported ground symbol has three bars; extra bars are ambiguous.
        if len(followers) != 2:
            continue
        (first_distance, first), (last_distance, last) = followers
        if (last_distance - first_distance <= tol or length - first["length"] <= tol
                or first["length"] - last["length"] <= tol):
            continue
        handles = [bar["handle"], first["handle"], last["handle"]]
        candidates.append({"id": "ground:" + bar["handle"], "kind": "ground_reference",
            "ground_type": "three_bar", "status": "candidate", "potential": None,
            "wire_ids": sorted(wires.get(stem["handle"], set())),
            "source": dict(deepcopy(source), handles=[stem["handle"], *handles]),
            "evidence": {"bar_handles": handles, "stem_handle": stem["handle"],
                "attachment": "wire_endpoint_at_longest_bar_midpoint", "tolerance": tol}})
    return sorted(candidates, key=lambda candidate: candidate["id"])
