"""Collect supported connector shapes and their source geometry."""

from collections import defaultdict

from math import isfinite

import re

from ezdxf.lldxf.const import DXFError

def _shape_profile(insert, anchor, tolerance):
    """按图元结构识别单个符号；不支持或证据不完整时明确拒绝。"""
    # 1 个引线、4 个矩形顶点、2 个边端点来自几何定义，不是图纸尺寸。
    if insert.mcount != 1:
        raise ValueError("array_insert")
    source = [e for e in insert.doc.blocks[insert.dxf.name] if e.dxftype() != "ATTDEF"]
    skipped = []
    shapes = list(insert.virtual_entities(skipped_entity_callback=lambda e, reason: skipped.append(reason)))
    kinds = sorted(e.dxftype() for e in shapes)
    if skipped or kinds not in (["ARC", "LINE"], ["LINE", "LWPOLYLINE", "SOLID"]):
        raise ValueError("unsupported_or_skipped_geometry:" + ",".join(kinds))
    line = next(e for e in shapes if e.dxftype() == "LINE")
    ends = (line.dxf.start, line.dxf.end)
    if sum(anchor.distance(p) <= tolerance for p in ends) != 1:
        raise ValueError("anchor_not_at_one_lead_end")
    body = max(ends, key=anchor.distance)
    axis = (body - anchor).normalize()
    if kinds == ["ARC", "LINE"]:
        arc = next(e for e in shapes if e.dxftype() == "ARC")
        mouth = arc.ocs().to_wcs(arc.dxf.center)
        # 半圆的两端中点等于圆心；360 度是一整周，2 是中点除数。
        sweep = (arc.dxf.end_angle - arc.dxf.start_angle) % 360
        middle = next(arc.vertices([arc.dxf.start_angle + sweep / 2]))
        if ((arc.start_point + arc.end_point) / 2).distance(mouth) > tolerance:
            raise ValueError("socket_not_semicircle")
        if middle.distance(body) > tolerance or (mouth - body).dot(axis) <= tolerance:
            raise ValueError("socket_lead_not_at_arc_back")
        if (mouth - body).cross(axis).magnitude > tolerance:
            raise ValueError("socket_axis_off_center")
        if abs((arc.end_point - arc.start_point).dot(axis)) > tolerance:
            raise ValueError("socket_opening_not_perpendicular")
        plane_points = [anchor, body, mouth, arc.start_point, arc.end_point, middle]
        width, role = arc.dxf.radius, "socket"
    else:
        poly = next(e for e in shapes if e.dxftype() == "LWPOLYLINE")
        vertices = list(poly.vertices_in_wcs())
        if not poly.closed or len(vertices) != 4 or any(any(p[2:]) for p in poly.get_points()):
            raise ValueError("pin_not_straight_closed_quadrilateral")
        edges = [vertices[(i + 1) % 4] - p for i, p in enumerate(vertices)]
        if min(e.magnitude for e in edges) <= tolerance:
            raise ValueError("pin_degenerate_rectangle")
        if ((edges[0] + edges[2]).magnitude > tolerance or
                (edges[1] + edges[3]).magnitude > tolerance or
                abs(edges[0].normalize().dot(edges[1])) > tolerance):
            raise ValueError("pin_not_rectangle")
        solid = next(e for e in shapes if e.dxftype() == "SOLID")
        filled = list(solid.wcs_vertices())
        if len(filled) != 4 or any(sum(v.distance(p) <= tolerance for p in filled) != 1 for v in vertices):
            raise ValueError("pin_fill_does_not_match_outline")
        normal = edges[0].cross(edges[1]).normalize()
        if abs((anchor - vertices[0]).dot(normal)) > tolerance:
            raise ValueError("pin_lead_off_plane")
        positions = [(v - anchor).dot(axis) for v in vertices]
        front = [v for v, q in zip(vertices, positions) if abs(q - max(positions)) <= tolerance]
        back = [v for v, q in zip(vertices, positions) if abs(q - min(positions)) <= tolerance]
        if len(front) != 2 or len(back) != 2 or ((back[0] + back[1]) / 2).distance(body) > tolerance:
            raise ValueError("pin_lead_not_at_rear_edge_center")
        mouth, width, role = (front[0] + front[1]) / 2, front[0].distance(front[1]) / 2, "pin"
        plane_points = [anchor, body, *vertices]
    if width <= tolerance:
        raise ValueError("opening_has_no_width")
    if not all(isfinite(v) for p in [*plane_points, axis] for v in p) or not isfinite(width):
        raise ValueError("non_finite_geometry")
    if max(p.z for p in plane_points) - min(p.z for p in plane_points) > tolerance:
        raise ValueError("unsupported_tilted_plane")
    return {"insert": insert.dxf.handle, "role": role, "mouth": list(mouth),
            "axis": list(axis), "half_width": width,
            "shape_handles": [e.dxf.handle for e in source]}

def collect_connector_shapes(document, facts, tolerance):
    """收集单编号 LINK 符号；只返回特征和拒绝原因，不修改模型。"""
    if not isfinite(tolerance) or tolerance <= 0:
        raise ValueError("positive_finite_tolerance_required")
    terminals, anchors = defaultdict(list), defaultdict(list)
    for terminal in facts["terminals"]:
        terminals[terminal["insert"].dxf.handle].append(terminal)
    for anchor in facts["anchors"]:
        anchors[anchor["insert"].dxf.handle].append(anchor)
    profiles, unresolved = [], []
    for handle, numbered in terminals.items():
        insert = numbered[0]["insert"]
        links = [a.dxf.tag.upper() for a in insert.attribs if re.fullmatch(r"X[1248]LINK", a.dxf.tag.upper())]
        # 多端触点等不满足连接器入口结构，不进入本规则。
        if len(numbered) != 1 or set(links) not in ({"X1LINK", "X4LINK"}, {"X2LINK", "X8LINK"}):
            continue
        try:
            tags = [a.dxf.tag.upper() for a in insert.attribs]
            if len(anchors[handle]) != 1 or len(tags) != len(set(tags)):
                raise ValueError("ambiguous_anchor_or_attribute")
            anchor = anchors[handle][0]
            profile = _shape_profile(insert, anchor["point"], tolerance)
            profiles.append({**profile, "port": anchor["attribute"].dxf.handle,
                             "layout": insert.get_layout().name})
        except (ValueError, TypeError, ArithmeticError, DXFError) as error:
            unresolved.append({"insert": handle, "reason": str(error)})
    return {"profiles": profiles, "unresolved": unresolved}
