"""Measure and classify drawing entities using structural rules."""

from collections import Counter

from fnmatch import fnmatchcase

import math

import re

DEFAULT_SCALE = 1

# 64 ULP 是本脚本的浮点运算裕量，按单层4×4变换及距离计算的运算量选取；
# 只归一化浮点尾数，不修补图纸间隙，整图实测的容差和未匹配距离写入报告。
FLOAT_ULPS = 64

def segment_distance(point, start, end):
    """Return clamped 3D point-to-segment distance, including zero-length segments."""
    direction = end - start
    length_squared = direction.dot(direction)
    # 0 和 1 是线段仿射参数区间的数学定义，不是图纸容差。
    parameter = max(0, min(1, (point - start).dot(direction) / length_squared)) if length_squared else 0
    return point.distance(start + direction * parameter)

def probe(document):
    """Measure generic attribute/geometry candidates without asserting electrical meaning."""
    model = document.modelspace()
    lines = list(model.query("LINE"))
    endpoints = [tuple(point) for line in lines for point in (line.dxf.start, line.dxf.end)]
    anchors, terminals, markers, duplicate_tags = [], [], [], 0
    missing_definitions, displaced_anchors, empty_labels, unpaired_labels = 0, [], 0, 0
    unpaired_anchors, tag_families, directions = 0, Counter(), Counter()
    for insert in model.query("INSERT"):
        attributes = {a.dxf.tag.upper(): a for a in insert.attribs}
        duplicate_tags += len(insert.attribs) - len(attributes)
        definitions = {a.dxf.tag.upper(): a for a in document.blocks[insert.dxf.name].query("ATTDEF")}
        local_anchors = {}
        for tag, attribute in attributes.items():
            match = re.fullmatch(r"X(\d)TERM(\d+)", tag)
            if not match:
                continue
            direction, suffix = match.groups()
            point = attribute.ocs().to_wcs(attribute.dxf.insert)
            anchor = {"insert": insert, "attribute": attribute, "suffix": suffix, "point": point}
            anchors.append(anchor)
            local_anchors.setdefault(suffix, []).append(anchor)
            directions[direction] += 1
            tag_families[insert.dxf.name] += 1
            if tag not in definitions:
                missing_definitions += 1
            else:
                definition = definitions[tag]
                expected = insert.matrix44().transform(definition.ocs().to_wcs(definition.dxf.insert))
                displaced_anchors.append(point.distance(expected))
        labels = {tag[4:]: a for tag, a in attributes.items() if re.fullmatch(r"TERM\d+", tag)}
        for suffix, label in labels.items():
            empty_labels += not bool(label.dxf.text.strip())
            unpaired_labels += suffix not in local_anchors
            if suffix in local_anchors and label.dxf.text.strip():
                terminals.append({"insert": insert, "label": label, "anchors": local_anchors[suffix]})
        unpaired_anchors += sum(len(values) for key, values in local_anchors.items() if key not in labels)
        graphics = [e for e in document.blocks[insert.dxf.name] if e.dxftype() != "ATTDEF"]
        # 同心圆候选按结构识别；不写死块名、圆数量或半径。
        if graphics and not insert.attribs and all(e.dxftype() == "CIRCLE" for e in graphics):
            centers = {tuple(e.ocs().to_wcs(e.dxf.center)) for e in graphics}
            if len(centers) == DEFAULT_SCALE:
                point = insert.matrix44().transform(next(iter(centers)))
                markers.append({"insert": insert, "point": point, "circles": len(graphics)})
    nearest = [min((math.dist(anchor["point"], p) for p in endpoints), default=math.inf) for anchor in anchors]
    definition_distances = Counter(format(value, ".3g") for value in displaced_anchors)
    nearest_distances = Counter(format(value, ".3g") for value in nearest)
    nearest_segments = [min((segment_distance(anchor["point"], line.dxf.start, line.dxf.end)
                            for line in lines), default=math.inf) for anchor in anchors]
    patterns = [value.strip().upper() for insert in model.query("INSERT") for a in insert.attribs
                if a.dxf.tag.upper() == "WIRELAYS" for value in a.dxf.text.split(",") if value.strip()]
    wire_type_layers = {layer.dxf.name for layer in document.layers if layer.has_extension_dict
                        and "ACADE_WIRETYPE" in layer.get_extension_dict().dictionary}
    summary = {"line_count": len(lines), "connection_attribute_count": len(anchors),
               "terminal_pair_count": len(terminals), "connection_directions": dict(directions),
               "connection_blocks": dict(tag_families), "duplicate_attribute_tags": duplicate_tags,
               "missing_anchor_definitions": missing_definitions, "empty_terminal_labels": empty_labels,
               "unpaired_terminal_labels": unpaired_labels, "unpaired_connection_attributes": unpaired_anchors,
               "definition_position_distance_histogram": dict(definition_distances),
               "nearest_line_endpoint_distance_histogram": dict(nearest_distances),
               "nearest_line_segment_distance_histogram": dict(Counter(format(d, ".3g") for d in nearest_segments)),
               "circle_only_concentric_marker_count": len(markers),
               "marker_circle_counts": dict(Counter(m["circles"] for m in markers)),
               "wire_type_layers": sorted(wire_type_layers), "wire_layer_patterns": patterns,
               "pattern_matched_lines": sum(any(fnmatchcase(line.dxf.layer.upper(), p) for p in patterns) for line in lines),
               "wire_type_layer_lines": sum(line.dxf.layer in wire_type_layers for line in lines),
               "header_LUPREC": document.header.get("$LUPREC"),
               "endpoint_z_counts": dict(Counter(str(p[2]) for p in endpoints))}
    return {"summary": summary, "lines": lines, "anchors": anchors, "terminals": terminals,
            "markers": markers, "nearest": nearest, "nearest_segments": nearest_segments,
            "definition_distances": displaced_anchors, "wire_type_layers": wire_type_layers}

def classify(document, facts):
    """Trace LINE candidates only through endpoints or explicit attribute/marker evidence."""
    model = document.modelspace()
    if any(len(layout) for layout in document.layouts if layout.name != model.name):
        raise ValueError("整图分类仅支持全部实体位于Model的输入，不能遗漏非空纸空间")
    if any(document.blocks[i.dxf.name].query("INSERT") or i.mcount != DEFAULT_SCALE for i in model.query("INSERT")):
        raise ValueError("输入包含不支持的嵌套或阵列，不能只分类顶层实例")
    lines = facts["lines"]
    all_points = [p for line in lines for p in (line.dxf.start, line.dxf.end)]
    all_points += [a["point"] for a in facts["anchors"]] + [m["point"] for m in facts["markers"]]
    magnitude = max((abs(v) for point in all_points for v in point), default=DEFAULT_SCALE)
    tolerance = math.ulp(magnitude) * FLOAT_ULPS
    adjacent = {index: set() for index in range(len(lines))}
    for index, line in enumerate(lines):
        for other in range(index):
            if any(a.distance(b) <= tolerance for a in (line.dxf.start, line.dxf.end)
                   for b in (lines[other].dxf.start, lines[other].dxf.end)):
                adjacent[index].add(other)
                adjacent[other].add(index)
    hits = []
    marker_hits = []
    for item in facts["anchors"] + facts["markers"]:
        found = {index for index, line in enumerate(lines)
                 if segment_distance(item["point"], line.dxf.start, line.dxf.end) <= tolerance}
        hits.append(found)
        if "circles" in item:
            marker_hits.append(found)
        # 同一个明确属性点或圆心才连接其命中的线；普通线段内部交叉不触发传播。
        for index in found:
            adjacent[index].update(found - {index})
    anchor_hits = hits[:len(facts["anchors"])]
    seeds = set().union(*anchor_hits) if anchor_hits else set()
    selected, frontier = set(), list(seeds)
    while frontier:
        index = frontier.pop()
        if index not in selected:
            selected.add(index)
            frontier.extend(adjacent[index] - selected)
    matched_anchors = sum(bool(values) for values in anchor_hits)
    selected_lines = [line for index, line in enumerate(lines) if index in selected]
    layers = Counter(line.dxf.layer for line in selected_lines)
    summary = {"floating_tolerance": tolerance, "floating_ULP_budget": FLOAT_ULPS,
               "matched_connection_attributes": matched_anchors,
               "unmatched_connection_attributes": len(anchor_hits) - matched_anchors,
               "direct_attribute_seed_lines": len(seeds), "wire_candidate_lines": len(selected),
               "unclassified_model_lines": len(lines) - len(selected), "candidate_layers": dict(layers),
               "candidate_lines_on_wire_type_layers": sum(l.dxf.layer in facts["wire_type_layers"] for l in selected_lines),
               "concentric_marker_line_hit_counts": dict(Counter(len(h) for h in marker_hits)),
               "connection_attributes_off_definition": sum(d > tolerance for d in facts["definition_distances"]),
               "smallest_unmatched_segment_distance": min((d for d in facts["nearest_segments"] if d > tolerance), default=None),
               "wire_components": 0}
    pending = selected.copy()
    while pending:
        frontier = [pending.pop()]
        summary["wire_components"] += 1
        while frontier:
            neighbors = adjacent[frontier.pop()] & pending
            pending.difference_update(neighbors)
            frontier.extend(neighbors)
    return {"summary": summary, "wire_lines": selected_lines, "anchor_hits": anchor_hits,
            "marker_hits": marker_hits, "tolerance": tolerance}
