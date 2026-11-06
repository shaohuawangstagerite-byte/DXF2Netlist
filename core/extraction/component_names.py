"""Resolve component name candidates while preserving their evidence."""

from collections import Counter, defaultdict

import re

from core.extraction.component_frame_names import frame_columns

COMPONENT_MODE = "LINK_axis_visible_header_candidates"

def resolve_component_names(document, data):
    """Keep title candidates; warn on hidden changes and stop on repeated numbers."""
    counts = Counter(t["insert"] for t in data["terminals"])
    tolerance, records, pins = data["tolerance"], {}, []
    for insert in document.modelspace().query("INSERT"):
        handle = insert.dxf.handle
        if handle not in counts:
            continue
        visible = [a for a in insert.attribs if a.dxf.tag.upper() in {"TAG1", "TAG2"}
                   and a.dxf.text.strip() and not a.is_invisible]
        names = {a.dxf.text for a in visible}
        records[handle] = {"name": next(iter(names)) if len(names) == 1 else None,
                           "status": "visible_TAG" if len(names) == 1 else "unresolved_name",
                           "header_insert": handle if len(names) == 1 else None,
                            "header_attributes": [a.dxf.handle for a in visible] if len(names) == 1 else [],
                            "warnings": []}
        links = {a.dxf.tag.upper(): a for a in insert.attribs if re.fullmatch(r"X[1248]LINK", a.dxf.tag.upper())}
        # One numbered terminal and opposing LINK tags are SPEC R13's structural predicate.
        if counts[handle] != 1 or set(links) not in ({"X1LINK", "X4LINK"}, {"X2LINK", "X8LINK"}):
            continue
        anchors = [a for a in insert.attribs if re.fullmatch(r"X[1248]TERM\d+", a.dxf.tag.upper())]
        tags = tuple(sorted(links))
        first, second = [links[tag].ocs().to_wcs(links[tag].dxf.insert) for tag in tags]
        if first.distance(second) <= tolerance:
            continue
        # Two is the midpoint divisor, not a drawing-dependent dimension.
        pins.append({"handle": handle, "tags": tags, "axis": (second - first).normalize(),
                     "mid": (first + second) / 2, "visible": visible,
                     "point": anchors[0].ocs().to_wcs(anchors[0].dxf.insert) if len(anchors) == 1 else None,
                     "number": next((a.dxf.text.strip() for a in insert.attribs
                                     if re.fullmatch(r"TERM\d+", a.dxf.tag.upper())), ""),
                     "hidden_tags": tuple(sorted((a.dxf.tag.upper(), a.dxf.text.strip())
                                          for a in insert.attribs if a.dxf.tag.upper() in {"TAG1", "TAG2"}
                                          and a.is_invisible and a.dxf.text.strip()))})
    parent = {p["handle"]: p["handle"] for p in pins}
    for index, pin in enumerate(pins):
        for other in pins[:index]:
            # All spatial and parallelism margins use the SPEC R7 value.
            if pin["tags"] != other["tags"] or pin["axis"].cross(other["axis"]).magnitude > tolerance:
                continue
            if (other["mid"] - pin["mid"]).cross(pin["axis"]).magnitude > tolerance:
                continue
            left, right = pin["handle"], other["handle"]
            while parent[left] != left:
                left = parent[left]
            while parent[right] != right:
                right = parent[right]
            parent[right] = left
    columns = defaultdict(list)
    for pin in pins:
        root = pin["handle"]
        while parent[root] != root:
            root = parent[root]
        columns[root].append(pin)
    missing = {p["handle"] for column in columns.values() if not any(p["visible"] for p in column) for p in column}
    jobs = [(column, None, None) for column in columns.values()]
    jobs.extend(frame_columns(document, pins, missing, tolerance))
    for column, frame, target in jobs:
        axis, signs = column[0]["axis"], set()
        for pin in column:
            for tag in pin["visible"]:
                offset = (tag.ocs().to_wcs(tag.get_placement()[1]) - pin["mid"]).dot(axis)
                # -1/0/1 represent direction, not a fitted drawing constant.
                signs.add(1 if offset > tolerance else -1 if offset < -tolerance else 0)
        if signs not in ({1}, {-1}):
            for pin in column:
                if not pin["visible"] and (frame is None or pin["handle"] == target):
                    records[pin["handle"]]["status"] = "unresolved_header_direction" if signs else "unresolved_no_visible_header"
            continue
        ordered = sorted(column, key=lambda p: p["mid"].dot(axis), reverse=signs == {1})
        # Equal positions cannot establish a unique column order.
        if any(abs(a["mid"].dot(axis) - b["mid"].dot(axis)) <= tolerance for a, b in zip(ordered, ordered[1:])):
            for pin in column:
                if not pin["visible"] and (frame is None or pin["handle"] == target):
                    records[pin["handle"]]["status"] = "ambiguous_column_order"
            continue
        header, hidden_tags, previous_hidden, conflict = None, None, None, None
        name_warnings = []
        seen_numbers = {}
        for pin in ordered:
            own = records[pin["handle"]].copy()
            if pin["visible"]:
                header = own if own["name"] is not None else None
                hidden_tags, previous_hidden, conflict = None, None, None
                name_warnings = []
                seen_numbers = {}
            elif header is not None:
                if conflict is None and pin["number"] and pin["number"] in seen_numbers:
                    conflict = {"reason": "repeated_terminal_number",
                                "previous_insert": seen_numbers[pin["number"]],
                                "insert": pin["handle"], "header_insert": header["header_insert"]}
                if (conflict is None and pin["hidden_tags"] and hidden_tags is not None
                        and pin["hidden_tags"] != hidden_tags):
                    name_warnings.append({"reason": "hidden_TAG_changed", "previous_insert": previous_hidden,
                        "insert": pin["handle"], "header_insert": header["header_insert"],
                        "previous_tags": list(hidden_tags), "current_tags": list(pin["hidden_tags"])})
                if conflict is not None:
                    own.update(status="unresolved_name_conflict", name_conflict=conflict, warnings=list(name_warnings))
                else:
                    own = {**header, "status": "collinear_LINK_header_candidate",
                                              "warnings": list(name_warnings)}
                    # Hidden TAGs may be stale. Compare them with each other, not with the visible head.
                    if pin["hidden_tags"]:
                        hidden_tags, previous_hidden = pin["hidden_tags"], pin["handle"]
            if header is not None and pin["number"]:
                seen_numbers.setdefault(pin["number"], pin["handle"])
            if frame is None or pin["handle"] == target:
                if frame is not None and own["status"] == "collinear_LINK_header_candidate":
                    own.update(status="frame_segment_header_candidate", frame=frame,
                               warnings=[{"reason": "LINK_axis_offset", "header_insert": own["header_insert"],
                                          "offset": frame["LINK_axis_offset"]}] + list(own["warnings"]))
                records[pin["handle"]] = own
    return records
