"""Preserve source wires and intermediate nodes in the netlist."""

from collections import defaultdict

from ezdxf.math import Vec3

def wire_connections(data, graph):
    """Preserve each candidate LINE and explicit interior contacts, without net cliques."""
    points, paths, evidence = {}, {}, defaultdict(set)
    # Endpoint indices 0/1 and affine parameters 0..1 are mathematical definitions.
    for line in data["lines"]:
        handle = line["id"]
        paths[handle] = []
        for side, point in enumerate(line["ends"]):
            key = f"end:{handle}:{side}"
            points[key] = Vec3(point)
            paths[handle].append(key)
            evidence[key].add(handle)
    for collection, prefix, hit_key in (("anchors", "p", "anchor_hits"),
                                        ("markers", "dot", "marker_hits")):
        for item in data[collection]:
            hits = graph[hit_key][item["id"]]
            if not hits:
                continue
            key = f'{prefix}:{item["id"]}'
            points[key] = Vec3(item["point"])
            evidence[key].add(item["id"])
            for wire in hits:
                paths[wire].append(key)
    parent = {key: key for key in points}
    keys = list(points)
    for index, key in enumerate(keys):
        for other in keys[:index]:
            if points[key].distance(points[other]) > data["tolerance"]:
                continue
            left, right = key, other
            while parent[left] != left:
                left = parent[left]
            while parent[right] != right:
                right = parent[right]
            parent[max(left, right)] = min(left, right)
    groups = defaultdict(list)
    for key in keys:
        root = key
        while parent[root] != root:
            root = parent[root]
        groups[root].append(key)
    nodes, rows = {}, []
    for group in groups.values():
        ports = sorted(key for key in group if key.startswith("p:"))
        node = ports[0] if ports else "j:" + min(group)
        for key in group:
            nodes[key] = node
        for port in ports[1:]:
            rows.append({"id": "join:" + port, "kind": "junction",
                         "ends": [node, port], "status": "candidate",
                         "source": sorted(set().union(*(evidence[k] for k in group)))})
    for line in data["lines"]:
        handle = line["id"]
        start, end = map(Vec3, line["ends"])
        direction = end - start
        ordered = sorted(paths[handle], key=lambda key: (points[key] - start).dot(direction))
        path = list(dict.fromkeys(nodes[key] for key in ordered))
        row = {"id": "w:" + handle, "kind": "wire", "status": "candidate",
               "ends": [path[0], path[-1]], "via": path[1:-1], "source": [handle]}
        row["port_ids"] = sorted(key for key in paths[handle] if key.startswith("p:"))
        row["marker_ids"] = sorted(key.removeprefix("dot:") for key in paths[handle] if key.startswith("dot:"))
        rows.append(row)
    return rows
