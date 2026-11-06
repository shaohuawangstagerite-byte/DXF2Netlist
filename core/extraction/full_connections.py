"""Build connections from line endpoints and explicit junction evidence."""

from ezdxf.math import Vec3

from core.extraction.full_rules import segment_distance

def connect(data, mode="exact"):
    """Build direct contacts; R7 normalizes tails and R8 admits explicit segment points."""
    if mode not in {"exact", "ulp_endpoints", "explicit_points"}:
        raise ValueError("不支持的连接模式")
    # The nonzero tolerance is measured over the entire drawing by SPEC R7.
    tolerance = 0 if mode == "exact" else data["tolerance"]
    lines = data["lines"]
    ends = {line["id"]: [Vec3(p) for p in line["ends"]] for line in lines}
    contacts = {line["id"]: [set(), set()] for line in lines}
    links, hits = set(), {}
    for index, line in enumerate(lines):
        for other in lines[:index]:
            for side, point in enumerate(ends[line["id"]]):
                for other_side, other_point in enumerate(ends[other["id"]]):
                    if point.distance(other_point) <= tolerance:
                        links.add(tuple(sorted((line["id"], other["id"]))))
                        contacts[line["id"]][side].add("wire:" + other["id"])
                        contacts[other["id"]][other_side].add("wire:" + line["id"])
    for kind in ("anchors", "markers"):
        hits[kind] = {}
        for item in data[kind]:
            point, found = Vec3(item["point"]), set()
            for line in lines:
                if mode == "explicit_points" and segment_distance(point, *ends[line["id"]]) <= tolerance:
                    found.add(line["id"])
                for side, endpoint in enumerate(ends[line["id"]]):
                    if point.distance(endpoint) <= tolerance:
                        found.add(line["id"])
                        contacts[line["id"]][side].add(kind + ":" + item["id"])
            hits[kind][item["id"]] = sorted(found)
            # R8 only joins interiors sharing this explicit anchor or marker.
            if mode == "explicit_points":
                for wire in found:
                    for other in found:
                        if wire != other:
                            links.add(tuple(sorted((wire, other))))
    # Union-find consumes only justified wire links; components never imply end contact.
    parent = {line["id"]: line["id"] for line in lines}
    for left, right in sorted(links):
        while parent[left] != left:
            left = parent[left]
        while parent[right] != right:
            right = parent[right]
        left, right = sorted((left, right))
        parent[right] = left
    nets, line_net = {}, {}
    for line in lines:
        root = line["id"]
        while parent[root] != root:
            root = parent[root]
        nets.setdefault(root, []).append(line["id"])
        line_net[line["id"]] = root
    terminal_nets = {t["id"]: sorted({line_net[wire] for anchor in t["anchors"]
                                      for wire in hits["anchors"][anchor]}) for t in data["terminals"]}
    return {"source_sha256": data["source_sha256"], "spec_sha256": data["spec_sha256"],
            "mode": mode, "tolerance": tolerance, "wire_links": [list(pair) for pair in sorted(links)],
            "endpoint_contacts": {key: [sorted(side) for side in sides] for key, sides in contacts.items()},
            "anchor_hits": hits["anchors"], "marker_hits": hits["markers"],
            "nets": {key: sorted(wires) for key, wires in nets.items()}, "terminal_nets": terminal_nets,
            "connector_mating": data.get("connector_mating", {"pairs": [], "unresolved": []})}
