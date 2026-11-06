"""Validate extracted geometry and connectivity independently."""

import math

def compare(data, result):
    """Reconstruct direct contacts independently, then derive nets with BFS."""
    if result["mode"] not in {"exact", "ulp_endpoints", "explicit_points"}:
        raise ValueError("比较器遇到未支持的规则")
    # Zero distance is the exact-endpoint definition, not an empirical tolerance.
    tolerance = 0 if result["mode"] == "exact" else data["tolerance"]
    endpoints = [(line["id"], side, p) for line in data["lines"] for side, p in enumerate(line["ends"])]
    contacts = {line["id"]: [set(), set()] for line in data["lines"]}
    links, hits = set(), {}
    for index, (wire, side, p) in enumerate(endpoints):
        for other, other_side, q in endpoints[:index]:
            if wire != other and math.dist(p, q) <= tolerance:
                links.add(tuple(sorted((wire, other))))
                contacts[wire][side].add("wire:" + other)
                contacts[other][other_side].add("wire:" + wire)
    for kind in ("anchors", "markers"):
        hits[kind] = {}
        for item in data[kind]:
            found = set()
            for wire, side, p in endpoints:
                if math.dist(item["point"], p) <= tolerance:
                    found.add(wire)
                    contacts[wire][side].add(kind + ":" + item["id"])
            if result["mode"] == "explicit_points":
                for line in data["lines"]:
                    start, end = line["ends"]
                    direction = [b - a for a, b in zip(start, end)]
                    offset = [p - a for p, a in zip(item["point"], start)]
                    length_squared = sum(d * d for d in direction)
                    # 0..1 is the segment's affine parameter domain, not drawing tolerance.
                    parameter = max(0, min(1, sum(v * d for v, d in zip(offset, direction)) / length_squared)) if length_squared else 0
                    residual_squared = sum((v - parameter * d) ** 2 for v, d in zip(offset, direction))
                    if residual_squared <= tolerance ** 2:
                        found.add(line["id"])
                for wire in found:
                    for other in found:
                        if wire != other:
                            links.add(tuple(sorted((wire, other))))
            hits[kind][item["id"]] = sorted(found)
    adjacency = {line["id"]: set() for line in data["lines"]}
    for left, right in links:
        adjacency[left].add(right)
        adjacency[right].add(left)
    pending, nets, wire_net = set(adjacency), {}, {}
    while pending:
        component, frontier = set(), [min(pending)]
        while frontier:
            wire = frontier.pop()
            if wire not in component:
                component.add(wire)
                frontier.extend(adjacency[wire] - component)
        root = min(component)
        nets[root] = sorted(component)
        wire_net.update(dict.fromkeys(component, root))
        pending -= component
    expected = {"source_sha256": data["source_sha256"], "spec_sha256": data["spec_sha256"],
                "mode": result["mode"], "tolerance": tolerance, "wire_links": [list(p) for p in sorted(links)],
                "endpoint_contacts": {key: [sorted(s) for s in sides] for key, sides in contacts.items()},
                "anchor_hits": hits["anchors"], "marker_hits": hits["markers"], "nets": nets,
                "terminal_nets": {t["id"]: sorted({wire_net[wire] for anchor in t["anchors"]
                                  for wire in hits["anchors"][anchor]}) for t in data["terminals"]}}
    differences = [key for key, value in expected.items() if result.get(key) != value]
    return {"passed": not differences, "differences": differences, "checked_wires": len(data["lines"]),
            "checked_anchors": len(data["anchors"]), "checked_markers": len(data["markers"]),
            "checked_terminals": len(data["terminals"])}
